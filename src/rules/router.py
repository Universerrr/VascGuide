"""路由判定流水线（P0a~P8）—— 确定性代码，禁止 LLM。

依据：`.workbuddy/spec/VascCase字段设计表.xlsx`
      · Sheet `06_路由决策流水线`（P0a~P8 执行顺序 + 依据规则）
      · Sheet `03_P1-P8判定映射`（每步所需字段）
      · 表2 覆盖规则 O01~O29（阈值口径）

执行语义（务必遵守）：
    自上而下求值，**命中即短路返回**；上一步的判定结果影响后续步是否仍需判定。
    P0a/P0b 是「前置预处理」，不产生路由，只做语义与多标签治理。
    P1 急诊 → P2 特殊病变 → P3 复杂解剖 → P4 严重合并症 → P5 证据冲突 →
    P6 字段缺失 → P7/P8 指南。优先级 急诊 > 复杂 > 指南。

返回值：
    ``RouteResult`` —— 结构化路由结论 + 逐步判定轨迹（供审计落盘）。
本模块不得 import 任何 LLM 客户端（治理红线）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..models.enums import (
    AnatomyLevel,
    CKDStage,
    DiseaseCategory,
    EndoleakType,
    HeartFailureNYHA,
    MalignancyStatus,
    PriorRepair,
    RouteMode,
    RuptureStatus,
    SymptomAAA,
)
from .version import RULESET_VERSION

if TYPE_CHECKING:
    from ..models.preop.case import VascCase


# ===========================================================================
# 工程阈值（与表2 覆盖规则一一对应；改动须 bump 表2 版本号）
# ===========================================================================
NECK_LENGTH_THRESHOLD_MM = 15.0  # O15：瘤颈长度 < 15mm → 复杂解剖
NECK_ANGLE_THRESHOLD_DEG = 45.0  # O16：瘤颈成角 > 45° → 复杂解剖
ACCESS_DIAMETER_THRESHOLD_MM = 7.0  # O17：入路直径 < 7mm → 复杂解剖
NECK_THROMBUS_CALC_THRESHOLD_PCT = 50  # O18：瘤颈血栓/钙化 > 50% → 复杂解剖

# 特殊主动脉病种（P2 / O21）
SPECIAL_SUBTYPE_KEYWORDS: tuple[str, ...] = (
    "感染",
    "炎症",
    "囊状",
    "pau",
    "imh",
    "iaad",
    "假性动脉瘤",
    "遗传",
    "结缔组织",
    "瘘",
)

# 复杂解剖分型（P3 / O22）—— 枚举集判定，等价于原关键词匹配且无子串误判风险
COMPLEX_ANATOMY_LEVELS = frozenset(
    {
        AnatomyLevel.SHORT_NECK_INFRARENAL,
        AnatomyLevel.JUXTARENAL,
        AnatomyLevel.PARARENAL,
        AnatomyLevel.PARAVISCERAL,
        AnatomyLevel.TYPE_IV_TAAA,
    }
)

# 「肯定」取值：三态/四态枚举中唯一表示「有」的取值
AFFIRMATIVE_VALUE = "有"

# 复杂手术史 / 再次干预（P3 / O23）—— 与「无既往修复」相对
COMPLEX_PRIOR_REPAIR = frozenset({PriorRepair.FEVAR, PriorRepair.BEVAR, PriorRepair.OTHER})

# 术后并发症关键词（P3，需结合 prior_repair）
POSTOP_COMPLICATION_KEYWORDS: tuple[str, ...] = (
    "内漏",
    "瘤囊增大",
    "支架移位",
    "闭塞",
    "吻合口",
    "感染",
    "瘘",
    "再破裂",
)

# 低复杂度指南病种（P7 / O26）
GUIDELINE_CATEGORIES = frozenset(
    {
        DiseaseCategory.ASYMPTOMATIC,
        DiseaseCategory.ILIAC_ANEURYSM,
        DiseaseCategory.POSTOPERATIVE,
    }
)

# 置信度
BASE_CONFIDENCE = 0.90  # 正常基准
MISSING_PENALTY = 0.5  # 关键字段缺失时 ×0.5（O25）


# ===========================================================================
# 结构化输出
# ===========================================================================
@dataclass
class StepTrace:
    """单个判定步骤的轨迹记录（审计：含被否决项）。"""

    order: str  # P0a / P0b / P1 ~ P8
    condition: str  # 判定条件描述
    result: bool  # 该步求值结果
    rule_ref: str  # 依据覆盖规则编号
    note: str = ""  # 补充说明


@dataclass
class RouteResult:
    """路由结论 + 完整判定轨迹。"""

    route_mode: RouteMode
    reason: str
    urgency_triggered: bool
    is_special_lesion: bool
    complex_anatomy: bool
    severe_comorbidity: bool
    guideline_eligible: bool
    missing_critical_fields: list[str] = field(default_factory=list)
    confidence: float = BASE_CONFIDENCE
    manual_review_required: bool = False
    ruleset_version: str = RULESET_VERSION
    trace: list[StepTrace] = field(default_factory=list)


# ===========================================================================
# 各步判定（纯函数）
# ===========================================================================
def _is_truthy(v: object) -> bool:
    """三态/四态枚举 → 布尔：**仅「有」为真**。

    缺失 / 未提及 / 未描述 / **疑似** 一律不为真（「疑似感染」不等于「有感染」，O21）。

    ⚠️ 实现要点：按 ``value`` 比较，**不得用 ``is`` 身份比较**。事实层字段可能使用
    不同的枚举类（``YesNoUnknown`` / ``InfectionEvidence`` / ``Tortuosity``），
    ``v is YesNoUnknown.YES`` 在换类后会**静默返回 False**，导致 P2/P3 判定无声失效。
    """
    if v is None:
        return False
    return getattr(v, "value", v) == AFFIRMATIVE_VALUE


def collect_missing_critical_fields(case: VascCase) -> list[str]:
    """收集缺失的关键事实层字段（O25 / CRITICAL_FACT_FIELDS）。

    注意：只检查事实层字段——判定层由代码派生，必然存在，不可能缺失。
    """
    from ..models.preop.case import CRITICAL_FACT_FIELDS

    missing: list[str] = []
    for name in CRITICAL_FACT_FIELDS:
        value = getattr(case, name, None)
        if value is None:
            missing.append(name)
        elif isinstance(value, list) and len(value) == 0:
            # disease_category 为空列表，同样视为未识别
            missing.append(name)
    return missing


def step_p1_emergency(case: VascCase) -> tuple[bool, str]:
    """P1 急诊触发判定（O01~O10）。

    触发条件（任一为真）：
      1. urgency_flag 显式置位（O01，人工/系统指定，最高优先）；
      2. 破裂 / 疑似破裂（O02~R02）；
      3. AAA 归因性症状「有」（O03~O05）；
      4. 循环不稳 / 活动性出血 / 急性肢体缺血 / 灌注障碍 / 脓毒症（O06~O10）。
    """
    if case.urgency_flag:
        return True, "P1·O01 显式急症标志 urgency_flag 置位"

    if case.rupture_status in (RuptureStatus.CONFIRMED, RuptureStatus.SUSPECTED):
        return True, f"P1·O02 破裂状态 = {case.rupture_status.value}"

    if case.symptom_aaa_related is SymptomAAA.PRESENT:
        return True, "P1·O03 AAA 归因性症状 = 有"

    acute_signs = (
        ("hemodynamic_instability", "循环不稳", "O06"),
        ("active_hemorrhage", "活动性出血", "O07"),
        ("acute_limb_ischemia", "急性肢体缺血", "O08"),
        ("visceral_malperfusion", "重要器官灌注障碍", "O09"),
        ("septic_shock", "脓毒性休克", "O10"),
    )
    for attr, label, rule in acute_signs:
        if _is_truthy(getattr(case, attr, None)):
            return True, f"P1·{rule} {label} = 有"

    return False, "P1 无急诊触发"


def step_p2_special(case: VascCase) -> tuple[bool, str]:
    """P2 特殊主动脉病种 / 复杂病变（O21）。

    覆盖：感染性、炎症性、囊状、PAU、IMH、IAAD、假性动脉瘤、遗传/结缔组织、
          **活动性恶性肿瘤**、主动脉-肠瘘 / 腔静脉瘘，以及 disease_category 含
          「感染性/其他特殊」。

    注：``infection_evidence`` 取「疑似」时**不**触发本步（仅「有」为真，见
        :func:`_is_truthy`）；该口径待临床确认后可能调整。
    """
    if _is_truthy(case.infection_evidence):
        return True, "P2·O21 感染证据 = 有"
    if _is_truthy(case.inflammatory_evidence):
        return True, "P2·O21 炎症证据 = 有"
    if _is_truthy(case.genetic_syndrome):
        return True, "P2·O21 遗传/结缔组织病 = 有"
    if case.malignancy is MalignancyStatus.ACTIVE:
        return True, "P2·O21 合并活动性恶性肿瘤"

    pieces = [
        case.special_lesion_type or "",
        case.lesion_subtype or "",
        case.lesion_morphology or "",
    ]
    haystack = " ".join(pieces).lower()
    for kw in SPECIAL_SUBTYPE_KEYWORDS:
        if kw in haystack:
            return True, f"P2·O21 特殊病变线索命中「{kw}」"

    cats = set(case.disease_category or [])
    if DiseaseCategory.INFECTIOUS in cats:
        return True, "P2·O21 病种含「4感染性主动脉疾病」"
    if DiseaseCategory.OTHER_SPECIAL in cats:
        return True, "P2·O21 病种含「5其他特殊主动脉疾病」"

    if case.postop_complication and any(k in case.postop_complication for k in ("感染", "瘘")):
        return True, "P2·O21 术后感染/瘘并发症"

    return False, "P2 无特殊病变"


def step_p3_complex_anatomy(case: VascCase) -> tuple[bool, str]:
    """P3 复杂解剖 / 复杂手术 / 异常术后（O15~O20, O22, O23）。"""
    # O15 瘤颈长度
    if case.neck_length_mm is not None and case.neck_length_mm < NECK_LENGTH_THRESHOLD_MM:
        return True, f"P3·O15 瘤颈长度 {case.neck_length_mm}mm < {NECK_LENGTH_THRESHOLD_MM}mm"
    # O16 瘤颈成角
    if case.neck_angle_deg is not None and case.neck_angle_deg > NECK_ANGLE_THRESHOLD_DEG:
        return True, f"P3·O16 瘤颈成角 {case.neck_angle_deg}° > {NECK_ANGLE_THRESHOLD_DEG}°"
    # O17 入路直径
    if (
        case.access_diameter_mm is not None
        and case.access_diameter_mm < ACCESS_DIAMETER_THRESHOLD_MM
    ):
        return (
            True,
            f"P3·O17 入路直径 {case.access_diameter_mm}mm < {ACCESS_DIAMETER_THRESHOLD_MM}mm",
        )
    # O18 瘤颈血栓/钙化
    if (
        case.neck_thrombus_calc_pct is not None
        and case.neck_thrombus_calc_pct > NECK_THROMBUS_CALC_THRESHOLD_PCT
    ):
        return (
            True,
            f"P3·O18 瘤颈血栓/钙化 {case.neck_thrombus_calc_pct}% > {NECK_THROMBUS_CALC_THRESHOLD_PCT}%",
        )
    # O19 迂曲 / 极度成角
    if _is_truthy(case.tortuosity):
        return True, "P3·O19 迂曲/极度成角 = 有"
    # O20 生长速率
    if case.growth_rate_mm_per_year is not None and case.growth_rate_mm_per_year >= 10:
        return True, f"P3·O20 年增长率 {case.growth_rate_mm_per_year}mm/年 ≥ 10mm/年"
    # O22 复杂解剖分型（枚举集判定，无子串误判）
    if case.anatomy_level in COMPLEX_ANATOMY_LEVELS:
        return True, f"P3·O22 复杂解剖分型 = {case.anatomy_level.value}"

    # O23 复杂手术史 / 异常术后
    if case.prior_repair in COMPLEX_PRIOR_REPAIR:
        return True, f"P3·O23 既往修复史 = {case.prior_repair.value}（复杂再干预）"
    if case.prior_repair is PriorRepair.NONE and _is_truthy(case.complex_surgery_history):
        return True, "P3·O23 复杂手术/多次再干预史 = 有"
    if (
        case.prior_repair is PriorRepair.NONE
        and case.postop_complication
        and any(k in case.postop_complication for k in POSTOP_COMPLICATION_KEYWORDS)
    ):
        return True, f"P3 术后并发症：{case.postop_complication}"

    # AAA 合并髂动脉瘤（表1 L02 → 复杂）
    cats = set(case.disease_category or [])
    if DiseaseCategory.ASYMPTOMATIC in cats and DiseaseCategory.ILIAC_ANEURYSM in cats:
        return True, "P3·表1 L02 AAA 合并髂动脉瘤"

    return False, "P3 解剖/手术复杂度未达阈值"


def step_p4_comorbidity(case: VascCase) -> tuple[bool, str]:
    """P4 严重合并症（O11~O14）。"""
    nyha = case.heart_failure_nyha
    if nyha in (HeartFailureNYHA.III, HeartFailureNYHA.IV):
        return True, f"P4·O11 心衰 {nyha.value} 级 ≥ III"
    if _is_truthy(case.copd):
        return True, "P4·O12 COPD = 有"
    if case.ckd_stage in (CKDStage.S3, CKDStage.S4, CKDStage.S5):
        return True, f"P4·O13 CKD {case.ckd_stage.value} 期 ≥ 3"
    if _is_truthy(case.cad):
        return True, "P4·O14 冠心病 CAD = 有"
    return False, "P4 无严重合并症"


def step_p5_conflict(case: VascCase) -> tuple[bool, str]:
    """P5 证据冲突（O24）。"""
    if _is_truthy(case.evidence_conflict):
        return True, "P5·O24 指南与影像证据冲突"
    return False, "P5 无证据冲突"


def step_p6_missing(case: VascCase, missing: list[str]) -> tuple[bool, str]:
    """P6 关键字段缺失 / 病种无法识别（O25）。"""
    if missing:
        return True, f"P6·O25 关键字段缺失：{'、'.join(missing)}"
    if not case.disease_category:
        return True, "P6·O25 病种无法识别（disease_category 为空）"
    return False, "P6 关键字段齐全"


def step_p7_guideline(case: VascCase) -> tuple[bool, str]:
    """P7 低复杂度常规指南场景（O26）。"""
    cats = set(case.disease_category or [])
    if not (cats & GUIDELINE_CATEGORIES):
        return False, "P7 不属于常规指南病种"

    # 术后病种：内漏类型决定归属（表2 T10）
    #   无内漏 / 稳定Ⅱ型 → 指南；Ⅰ/Ⅲ型高危 → 已由 P3 拦截为复杂，
    #   此处仅对「非稳定内漏」显式否决。
    if DiseaseCategory.POSTOPERATIVE in cats and case.endoleak_type is not None:
        et = case.endoleak_type
        if et in (EndoleakType.NONE, EndoleakType.II):
            return True, f"P7·O26 术后随访内漏状态 = {et.value}（稳定）"
        return False, f"P7·O26 术后内漏类型 {et.value}（非稳定Ⅱ型）"

    hit = cats & GUIDELINE_CATEGORIES
    return True, f"P7·O26 低复杂度指南病种：{'、'.join(c.value for c in hit)}"


def step_p8_prerequisites(case: VascCase, missing: list[str]) -> tuple[bool, str]:
    """P8 全部适用前置条件已核实（O26, O27）。"""
    if missing:
        return False, f"P8 前置未满足：仍缺 {len(missing)} 个关键字段"
    return True, "P8·O27 前置条件齐备，资料完整"


# ===========================================================================
# 主流水线
# ===========================================================================
def route(case: VascCase) -> RouteResult:
    """执行 P0a~P8 完整流水线，返回路由结论与判定轨迹。

    ⚠️ 纯确定性函数：不读文件、不调网络、不依赖时间、不引入 LLM。
    """
    trace: list[StepTrace] = []

    # ---- P0a 语义预处理（O28）：非判定步，只登记 ----
    trace.append(
        StepTrace(
            "P0a",
            "语义预处理：否定/时态/归因/疑似",
            True,
            "O28",
            "事件时态与肯定/否定已在前置抽取层处理；本步仅登记。",
        )
    )
    # ---- P0b 多标签处理（O29）：保留全部标签，主模式由优先级仲裁 ----
    trace.append(
        StepTrace(
            "P0b",
            "多标签处理：保留全部标签，主模式取最高优先级",
            True,
            "O29",
            f"当前病种标签 {len(case.disease_category or [])} 个。",
        )
    )

    missing = collect_missing_critical_fields(case)

    # ---- P1 急诊 ----
    hit, note = step_p1_emergency(case)
    trace.append(StepTrace("P1", "是否存在急诊触发？", hit, "O01~O10", note))
    if hit:
        return _build(
            RouteMode.EMERGENCY,
            note,
            case,
            missing,
            trace,
            True,
            manual_review=False,
        )

    # ---- P2 特殊病变 ----
    hit, note = step_p2_special(case)
    trace.append(StepTrace("P2", "是否存在特殊主动脉病种或复杂病变？", hit, "O21", note))
    if hit:
        return _build(RouteMode.COMPLEX, note, case, missing, trace, False)

    # ---- P3 复杂解剖 / 复杂手术 / 异常术后 ----
    hit, note = step_p3_complex_anatomy(case)
    trace.append(StepTrace("P3", "是否复杂解剖/复杂手术/异常术后？", hit, "O15~O20,O22,O23", note))
    if hit:
        return _build(RouteMode.COMPLEX, note, case, missing, trace, False)

    # ---- P4 严重合并症 ----
    hit, note = step_p4_comorbidity(case)
    trace.append(StepTrace("P4", "是否存在严重合并症？", hit, "O11~O14", note))
    if hit:
        return _build(RouteMode.COMPLEX, note, case, missing, trace, False)

    # ---- P5 证据冲突 ----
    hit, note = step_p5_conflict(case)
    trace.append(StepTrace("P5", "指南与影像证据是否冲突？", hit, "O24", note))
    if hit:
        return _build(RouteMode.COMPLEX, note, case, missing, trace, False, manual_review=True)

    # ---- P6 关键字段缺失 ----
    hit, note = step_p6_missing(case, missing)
    trace.append(StepTrace("P6", "决策关键字段是否缺失/病种无法识别？", hit, "O25", note))
    if hit:
        return _build(RouteMode.COMPLEX, note, case, missing, trace, False, manual_review=True)

    # ---- P7 指南场景 ----
    hit, note = step_p7_guideline(case)
    trace.append(StepTrace("P7", "是否属于低复杂度常规指南场景？", hit, "O26", note))
    if not hit:
        # 非指南病种且 P1~P6 均未命中 —— 兜底为复杂（不得默认「稳定」）
        note_fallback = "P7 未命中指南病种，且急诊/复杂均未触发 → 兜底复杂模式"
        trace.append(StepTrace("P7b", "兜底判定", True, "O25", note_fallback))
        return _build(
            RouteMode.COMPLEX, note_fallback, case, missing, trace, False, manual_review=True
        )

    # ---- P8 前置条件核实 ----
    hit8, note8 = step_p8_prerequisites(case, missing)
    trace.append(StepTrace("P8", "全部适用前置条件是否已核实？", hit8, "O26,O27", note8))
    if hit8:
        return _build(RouteMode.GUIDELINE, note, case, missing, trace, False)
    return _build(RouteMode.COMPLEX, note8, case, missing, trace, False, manual_review=True)


def _build(
    mode: RouteMode,
    reason: str,
    case: VascCase,
    missing: list[str],
    trace: list[StepTrace],
    urgency_triggered: bool,
    *,
    manual_review: bool = False,
) -> RouteResult:
    """汇总派生字段并计算置信度。"""
    # 判定层标记（供 VascCase 回填，也供审计）
    is_special = any(t.order == "P2" and t.result for t in trace)
    complex_anat = any(t.order == "P3" and t.result for t in trace)
    severe_comorb = any(t.order == "P4" and t.result for t in trace)

    confidence = BASE_CONFIDENCE
    if missing:
        confidence *= MISSING_PENALTY
    confidence = round(confidence, 2)

    manual = manual_review or bool(missing) or _is_truthy(case.evidence_conflict)

    return RouteResult(
        route_mode=mode,
        reason=reason,
        urgency_triggered=urgency_triggered,
        is_special_lesion=is_special,
        complex_anatomy=complex_anat,
        severe_comorbidity=severe_comorb,
        guideline_eligible=(mode is RouteMode.GUIDELINE),
        missing_critical_fields=missing,
        confidence=confidence,
        manual_review_required=manual,
        ruleset_version=RULESET_VERSION,
        trace=trace,
    )


__all__ = [
    "ACCESS_DIAMETER_THRESHOLD_MM",
    "AFFIRMATIVE_VALUE",
    "BASE_CONFIDENCE",
    "COMPLEX_ANATOMY_LEVELS",
    "COMPLEX_PRIOR_REPAIR",
    "GUIDELINE_CATEGORIES",
    "MISSING_PENALTY",
    "NECK_ANGLE_THRESHOLD_DEG",
    "NECK_LENGTH_THRESHOLD_MM",
    "NECK_THROMBUS_CALC_THRESHOLD_PCT",
    "POSTOP_COMPLICATION_KEYWORDS",
    "SPECIAL_SUBTYPE_KEYWORDS",
    "RouteResult",
    "StepTrace",
    "collect_missing_critical_fields",
    "route",
]
