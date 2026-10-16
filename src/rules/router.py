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

note 文本契约（审计证据粒度，供渲染/审计层解析；改动须同步本契约）：
    **未命中**步骤的 ``note`` 形如 ``<结论句>（<检查项>；<检查项>；…）``，
    全角括号包裹、全角分号分隔。检查项分三类：
      · 数值判据：``<中文名> <值><单位> <比较符> <阈值><单位>``
        例：``瘤颈长度 25.0mm ≥ 15.0mm``
      · 布尔/三态：``<中文名> <取值>``；显式置位标志记 ``未置位``
      · 枚举/列表：``<中文名> <中文取值>``，多值以 ``、`` 连接，缺失记 ``未提及``
      · 字段缺失时，数值判据**只记 ``未提及``、不附比较符**——写成
        ``未提及 ≥ 15mm`` 是伪陈述（无值可比），会误导复核者。
    检查项内部如需补充说明，用全角逗号 ``，``（与项间分隔符 ``；`` 区分）。
    目的：使「该步为何**未**命中」可由第三方独立复核（对照值与阈值自行验算），
    而非只能采信结论句。命中步骤的 note 保持原有「编号 + 值 + 阈值」写法。

缺失值语义契约（**未提及 ≠ 无**，判定口径；改动须同步本契约）：
    ``None`` 代表「**未提及**」（没查 / 没写 / 抽取失败），与「**明确为否**」是
    两回事，不得合并处理：
      · 明确为否（``EndoleakType.NONE``「无内漏」、``PriorRepair.NONE``「无既往修复」
        等）是**已核实的事实**，可支撑**放行**判定；
      · 未提及是**数据缺口**，不得支撑任何「安全侧」结论，一律按**不确定**处理，
        走否决 / 兜底路径。
    实现纪律：**禁止用 ``if field is not None:`` 作放行守卫**。该写法会让 ``None``
    跌出分支、落到下游的放行出口，等价于把「没查」当成「查过了且正常」。
    正确写法是**白名单正列举**：只有明确取值才放行，其余（含 ``None``）落拒绝分支。
    反面教材（已修，table2@v1.6）：P7 术后内漏分支原用 ``and endoleak_type is not None``
    守卫，导致「内漏类型未提及」的随访病例被下游出口放行为指南模式 + 免人工复核。

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


def _fmt(value: object, unit: str = "") -> str:
    """把字段值渲染为 ``note`` 文本（**仅用于文案，不参与任何判定**）。

    规则：枚举取 ``value``（中文取值）；列表以 ``、`` 连接（空列表记 ``空``）；
    ``None`` 统一记 ``未提及``；``unit`` 仅用于数值字段拼接单位。
    """
    if value is None:
        return "未提及"
    if isinstance(value, (list, tuple)):
        return "、".join(_fmt(v) for v in value) or "空"
    return f"{getattr(value, 'value', value)}{unit}"


def _checks(*items: str) -> str:
    """把检查项拼成 ``note`` 契约要求的后缀 ``（…；…；…）``。

    分隔符与包裹符在此**唯一定义**，渲染层可按它切分（见模块文档 note 契约）。
    """
    return "（" + "；".join(items) + "）"


def _cmp(value: object, unit: str, op: str, threshold: str) -> str:
    """数值判据渲染：有值 → ``<值><单位> <比较符> <阈值>``；字段缺失 → ``未提及``。

    缺失时刻意**不附比较符**：``未提及 ≥ 15mm`` 是无意义的伪陈述。
    """
    if value is None:
        return "未提及"
    return f"{value}{unit} {op} {threshold}"


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

    return False, "P1 无急诊触发" + _checks(
        "急症标志 未置位",
        f"破裂状态 {_fmt(case.rupture_status)}",
        f"AAA 归因性症状 {_fmt(case.symptom_aaa_related)}",
        "循环不稳/活动性出血/急性肢体缺血/灌注障碍/脓毒性休克 均无",
    )


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

    return False, "P2 无特殊病变" + _checks(
        f"感染证据 {_fmt(case.infection_evidence)}",
        f"炎症证据 {_fmt(case.inflammatory_evidence)}",
        f"遗传/结缔组织病 {_fmt(case.genetic_syndrome)}",
        f"恶性肿瘤 {_fmt(case.malignancy)}",
        "特殊病变线索 未命中",
        f"病种 {_fmt(case.disease_category)}",
        "术后并发症 未含感染/瘘线索",
    )


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

    return False, "P3 解剖/手术复杂度未达阈值" + _checks(
        f"瘤颈长度 {_cmp(case.neck_length_mm, 'mm', '≥', f'{NECK_LENGTH_THRESHOLD_MM}mm')}",
        f"瘤颈成角 {_cmp(case.neck_angle_deg, '°', '≤', f'{NECK_ANGLE_THRESHOLD_DEG}°')}",
        f"入路直径 {_cmp(case.access_diameter_mm, 'mm', '≥', f'{ACCESS_DIAMETER_THRESHOLD_MM}mm')}",
        "瘤颈血栓/钙化 "
        f"{_cmp(case.neck_thrombus_calc_pct, '%', '≤', f'{NECK_THROMBUS_CALC_THRESHOLD_PCT}%')}",
        f"迂曲/极度成角 {_fmt(case.tortuosity)}",
        f"年增长率 {_cmp(case.growth_rate_mm_per_year, 'mm/年', '<', '10mm/年')}",
        f"解剖分型 {_fmt(case.anatomy_level)}",
        f"既往修复史 {_fmt(case.prior_repair)}",
        "术后并发症 未含复杂关键词",
        f"病种 {_fmt(case.disease_category)}，未合并髂动脉瘤",
    )


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
    return False, "P4 无严重合并症" + _checks(
        f"心衰 {_fmt(case.heart_failure_nyha, ' 级')}，阈值 ≥ III 级",
        f"COPD {_fmt(case.copd)}",
        f"CKD {_fmt(case.ckd_stage, ' 期')}，阈值 ≥ 3 期",
        f"冠心病 CAD {_fmt(case.cad)}",
    )


def step_p5_conflict(case: VascCase) -> tuple[bool, str]:
    """P5 证据冲突（O24）。"""
    if _is_truthy(case.evidence_conflict):
        return True, "P5·O24 指南与影像证据冲突"
    return False, "P5 无证据冲突" + _checks(f"证据冲突标志 {_fmt(case.evidence_conflict)}")


def step_p6_missing(case: VascCase, missing: list[str]) -> tuple[bool, str]:
    """P6 关键字段缺失 / 病种无法识别（O25）。"""
    from ..models.preop.case import CRITICAL_FACT_FIELDS

    if missing:
        return True, f"P6·O25 关键字段缺失：{'、'.join(missing)}"
    if not case.disease_category:
        return True, "P6·O25 病种无法识别（disease_category 为空）"
    return False, "P6 关键字段齐全" + _checks(
        f"{len(CRITICAL_FACT_FIELDS)} 项关键字段均已填：{'、'.join(CRITICAL_FACT_FIELDS)}",
        f"病种 {_fmt(case.disease_category)}",
    )


def step_p7_guideline(case: VascCase) -> tuple[bool, str]:
    """P7 低复杂度常规指南场景（O26）。"""
    cats = set(case.disease_category or [])
    if not (cats & GUIDELINE_CATEGORIES):
        return False, "P7 不属于常规指南病种" + _checks(
            f"病种 {_fmt(case.disease_category)}",
            "常规指南病种：无症状 AAA / 孤立性髂动脉瘤 / 术后随访",
        )

    # 术后病种：内漏类型决定归属（表2 T10）——**白名单正列举**，不是 `is not None` 守卫。
    #   只有「无内漏」/「稳定Ⅱ型」放行指南；其余（含未提及 / 不明 / Ⅰ型 / Ⅲ型 / Ⅳ型）
    #   一律否决 → 由 P7b 兜底为复杂 + 人工复核（不得默认「稳定」）。
    #   ⚠️ 未提及（None）≠ 无内漏（EndoleakType.NONE）：前者是数据缺口，不是「已排除内漏」。
    #      若写成 `and case.endoleak_type is not None`，None 会跌出本分支、被下方
    #      「低复杂度指南病种」出口当作稳定随访放行（实测：指南 + 免人工复核 + 0.90）。
    if DiseaseCategory.POSTOPERATIVE in cats:
        et = case.endoleak_type
        if et in (EndoleakType.NONE, EndoleakType.II):
            return True, f"P7·O26 术后随访内漏状态 = {et.value}（稳定）"
        return False, "P7·O26 术后内漏类型非稳定Ⅱ型" + _checks(
            f"内漏类型 {_fmt(et)}",
            "稳定取值：无内漏 / Ⅱ型，未提及 ≠ 无内漏",
        )

    hit = cats & GUIDELINE_CATEGORIES
    return True, f"P7·O26 低复杂度指南病种：{'、'.join(c.value for c in hit)}"


def step_p8_prerequisites(case: VascCase, missing: list[str]) -> tuple[bool, str]:
    """P8 全部适用前置条件已核实（O26, O27）。"""
    if missing:
        return False, (
            f"P8 前置未满足：仍缺 {len(missing)} 个关键字段"
            + _checks(f"缺失字段：{'、'.join(missing)}")
        )
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
        # P7 未确立指南场景（病种不属常规指南，**或**术后内漏状态不可确认稳定），
        # 且 P1~P6 均未命中 —— 兜底为复杂（不得默认「稳定」）
        note_fallback = (
            "P7 未确立指南场景（病种或术后内漏状态不满足 O26），且 P1~P6 均未触发 → 兜底复杂模式"
        )
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
