"""VascCase —— 术前输入层数据模型。

定位（核心）：
    VascCase = LLM 从病历与 CTA 报告**一次抽取**出的「术前输入事实全集」。
    - 路由读取其中一部分（判定层字段）；
    - 后续影像量化 / 解剖评分 / 风险评估 / 指南引擎也各读取其中一部分；
    - **工具算出的产物不回写本模型**（分别归 VascMeasurement / AnatomyScore /
      RiskAssessment / FinalRecommendation）。

两层设计（必须遵守）：
    事实层（fact）  ：LLM 抽取，可缺失，**不得推理**，须带原文出处。
    判定层（det）   ：确定性代码计算，布尔/列表，**可复现**。
    → 路由只读判定层，不读原文。

来源：`.workbuddy/spec/VascCase字段设计表.xlsx` · Sheet `01_字段总表`（51 个临床字段）。
      另有 2 个审计留痕辅助字段（``field_evidence`` / ``urgency_flag_audit``），
      见 :data:`AUDIT_FIELDS`，不计入 51 个临床字段。
治理红线：本模型只做数据承载与校验，**不得引入任何 LLM 客户端**。
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..audit import FieldProvenance, UrgencyFlagAudit
from ..enums import (
    AnatomyLevel,
    CKDStage,
    DiagnosisCertainty,
    DiseaseCategory,
    EndoleakType,
    HeartFailureNYHA,
    InfectionEvidence,
    LesionMorphology,
    MalignancyStatus,
    PainAttribution,
    PriorRepair,
    RouteMode,
    RuptureStatus,
    Sex,
    SymptomAAA,
    TemporalStatus,
    Tortuosity,
    YesNoUnknown,
    strip_enum_annotation,
)

# 关键字段集：其缺失将触发「复杂模式 + 置信度×0.5」（依据表2 O25）。
# 注意：只包含**事实层**字段——判定层由代码派生，必然存在，不可能缺失。
CRITICAL_FACT_FIELDS: tuple[str, ...] = (
    "sex",
    "temporal_status",
    "symptom_aaa_related",
    "rupture_status",
    "prior_repair",
    "disease_category",
)

# 审计留痕辅助字段（跨层结构，**不计入**设计表的 51 个临床字段）。
AUDIT_FIELDS: tuple[str, ...] = ("field_evidence", "urgency_flag_audit")

# 设计表标注「数字（1位小数）」的字段 —— 落库前统一归一化。
ONE_DECIMAL_FIELDS: tuple[str, ...] = (
    "max_diameter_mm",
    "iliac_diameter_mm",
    "growth_rate_mm_per_year",
    "neck_length_mm",
    "access_diameter_mm",
)

# 枚举型字段（含 list 型 disease_category）—— 落库前去掉设计表的括号注释。
# 说明：anatomy_level / lesion_morphology 由各自的归一化校验器处理，故不在此列。
ENUM_FACT_FIELDS: tuple[str, ...] = (
    "sex",
    "disease_category",
    "temporal_status",
    "diagnosis_certainty",
    "symptom_aaa_related",
    "pain_cause_attributed",
    "rupture_status",
    "hemodynamic_instability",
    "active_hemorrhage",
    "acute_limb_ischemia",
    "visceral_malperfusion",
    "septic_shock",
    "tortuosity",
    "prior_repair",
    "endoleak_type",
    "infection_evidence",
    "inflammatory_evidence",
    "genetic_syndrome",
    "malignancy",
    "heart_failure_nyha",
    "copd",
    "ckd_stage",
    "cad",
    "complex_surgery_history",
    "evidence_conflict",
    "route_mode",
)


def _quantize(value: object, places: int) -> object:
    """按指定小数位归一化数值（ROUND_HALF_UP，非银行家舍入）。

    - ``None`` 原样返回（保留「缺失」语义，不得填充默认值）；
    - 不可解析值原样返回，交给 ``Field`` 约束报错，不在此处吞掉异常。
    """
    if value is None:
        return None
    try:
        quantum = Decimal(1).scaleb(-places)
        return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))
    except (InvalidOperation, ArithmeticError, ValueError):
        return value


class VascCase(BaseModel):
    """术前输入层：LLM 抽取的病例事实 + 确定性派生的判定标记。"""

    model_config = ConfigDict(
        extra="forbid",  # 拒绝未声明字段，防止抽取器写入脏数据
        validate_assignment=True,  # 赋值时重跑校验，保证派生逻辑可挂载
        use_enum_values=False,  # 保留枚举对象，便于类型安全
    )

    # ==================================================================
    # 元数据
    # ==================================================================
    case_id: str = Field(
        ...,
        description="病例唯一标识（系统生成，不可变）；用于全链路 Checkpoint 审计追溯。",
    )
    source_note: str | None = Field(
        default=None,
        description="原文摘要（证据层）。保留证据出处；**不得作为路由判断依据**。",
    )

    # ==================================================================
    # 事实层 · 人口学（来源：LLM 抽取）
    # ==================================================================
    age: int | None = Field(
        default=None,
        ge=0,
        le=120,
        description="年龄（岁）。影响修复评估分层。",
    )
    sex: Sex | None = Field(
        default=None,
        description="性别。阈值区分关键（男 55mm / 女 50mm）；未知不得默认男。",
    )

    # ==================================================================
    # 事实层 · 疾病与时态
    # ==================================================================
    disease_category: list[DiseaseCategory] | None = Field(
        default=None,
        description="一级病种（**list**）。O29 要求保留全部标签，不得只留一个。",
    )
    lesion_subtype: str | None = Field(
        default=None,
        description="二级病种（如：小型肾下AAA / 炎症性AAA / Ia型内漏）。",
    )
    temporal_status: TemporalStatus | None = Field(
        default=None,
        description="时态。关键：既往破裂 ≠ 当前破裂（表2 T27）。",
    )
    diagnosis_certainty: DiagnosisCertainty | None = Field(
        default=None,
        description="诊断确定性。疑似高危不得因未确诊而延误。",
    )

    # ==================================================================
    # 事实层 · 症状
    # ==================================================================
    symptom_aaa_related: SymptomAAA | None = Field(
        default=None,
        description="AAA 归因性症状。需与否定/他因区分。",
    )
    symptom_type: str | None = Field(
        default=None,
        description="症状类型（腹痛 / 腰背痛 / 压痛 / 远端栓塞 / 压迫症状…）。",
    )
    pain_cause_attributed: PainAttribution | None = Field(
        default=None,
        description="疼痛归因是否已核实（是（归因AAA）/ 否 / 未核实）。"
        "「否认腹痛」不足以证明无症状（O03）。",
    )

    # ==================================================================
    # 事实层 · 急症客观征象
    # ==================================================================
    rupture_status: RuptureStatus | None = Field(
        default=None,
        description="破裂状态。「排除破裂」→未破裂，不触发急诊（表2 T26/T33）。",
    )
    hemodynamic_instability: YesNoUnknown | None = Field(
        default=None,
        description="循环不稳（休克/低血压/晕厥）。需排除非主动脉原因。",
    )
    active_hemorrhage: YesNoUnknown | None = Field(
        default=None,
        description="活动性出血（造影剂外渗/大出血）。须确认来源为主动脉。",
    )
    acute_limb_ischemia: YesNoUnknown | None = Field(
        default=None,
        description="急性肢体缺血。仅急性；慢性跛行不触发。",
    )
    visceral_malperfusion: YesNoUnknown | None = Field(
        default=None,
        description="重要器官灌注障碍（肠系膜/肾/脊髓缺血）。",
    )
    septic_shock: YesNoUnknown | None = Field(
        default=None,
        description="脓毒性休克。感染性病种伴急性失代偿。",
    )

    # ==================================================================
    # 事实层 · 测量（门控用浅层数值；精密测量由 B 影像量化器产出）
    # ==================================================================
    max_diameter_mm: float | None = Field(
        default=None,
        ge=0,
        description="主动脉瘤体最大直径（mm，1位小数）。AAA 阈值 55/50mm。",
    )
    iliac_diameter_mm: float | None = Field(
        default=None,
        ge=0,
        description="髂动脉瘤体最大直径（mm，1位小数）。阈值 40mm，与 AAA 不同。",
    )
    growth_rate_mm_per_year: float | None = Field(
        default=None,
        description="年增长率（mm/年）。≥10 触发复杂（R004）。须同方法测量或复核。",
    )
    lesion_morphology: LesionMorphology | None = Field(
        default=None,
        description="瘤体形态（梭形 / 囊状 / 不规则 / 未描述）。形态异常独立于直径阈值。",
    )

    # ==================================================================
    # 事实层 · 解剖（工程阈值门控；精密测量由 B 产出）
    # ==================================================================
    neck_length_mm: float | None = Field(
        default=None,
        ge=0,
        description="近端瘤颈长度（mm）。<15 触发复杂（O15）。",
    )
    neck_angle_deg: float | None = Field(
        default=None,
        ge=0,
        le=180,
        description="瘤颈成角（度）。>45 触发复杂（O16）。",
    )
    access_diameter_mm: float | None = Field(
        default=None,
        ge=0,
        description="入路最小直径（mm）。<7 触发复杂（O17）。",
    )
    anatomy_level: AnatomyLevel | None = Field(
        default=None,
        description="解剖分型（肾下 / 短颈肾下 / 近肾 / 旁肾 / 近内脏 / IV型TAAA）。"
        "自由文本由校验器归一化；未识别直接报错。",
    )
    neck_thrombus_calc_pct: int | None = Field(
        default=None,
        ge=0,
        le=100,
        description="瘤颈血栓/钙化占比（%）。>50 触发复杂（O18）。",
    )
    tortuosity: Tortuosity | None = Field(
        default=None,
        description="迂曲 / 极度成角（>90°）（有 / 无 / 未描述）。O19。",
    )

    # ==================================================================
    # 事实层 · 治疗史与术后
    # ==================================================================
    prior_repair: PriorRepair | None = Field(
        default=None,
        description="既往主动脉修复史。术后与术前走不同路径，不可混淆。",
    )
    postop_complication: str | None = Field(
        default=None,
        description="术后并发症（内漏类型 / 瘤囊增大 / 支架移位 / 闭塞 / 吻合口瘤 / 感染 / 瘘…）。",
    )
    endoleak_type: EndoleakType | None = Field(
        default=None,
        description="内漏类型。Ⅰ/Ⅲ型高危；稳定Ⅱ型可走指南（表2 T10）。",
    )

    # ==================================================================
    # 事实层 · 病因与特殊病变
    # ==================================================================
    infection_evidence: InfectionEvidence | None = Field(
        default=None,
        description="感染证据（有 / 无 / 疑似 / 未提及）。仅发热/菌血症不足以确诊；"
        "「疑似」不得当作「有」。O21。",
    )
    inflammatory_evidence: YesNoUnknown | None = Field(
        default=None,
        description="炎症证据。感染性与非感染性炎症不可混。",
    )
    special_lesion_type: str | None = Field(
        default=None,
        description="特殊病变类型（PAU / IMH / IAAD / 假性动脉瘤 / 主动脉肠瘘 / 主动脉腔静脉瘘…）。",
    )
    genetic_syndrome: YesNoUnknown | None = Field(
        default=None,
        description="遗传/结缔组织病（Marfan/LDS/vEDS 等）。不套用一般 AAA 择期阈值。",
    )
    malignancy: MalignancyStatus | None = Field(
        default=None,
        description="合并恶性肿瘤（有（活动性）/ 无 / 既往已愈 / 未提及）。影响治疗优先级；"
        "仅「有（活动性）」触发 O21 特殊病变。",
    )

    # ==================================================================
    # 事实层 · 合并症
    # ==================================================================
    heart_failure_nyha: HeartFailureNYHA | None = Field(
        default=None,
        description="心衰分级。NYHA≥III 触发复杂（O11）。",
    )
    copd: YesNoUnknown | None = Field(
        default=None,
        description="COPD。明确合并即触发复杂（O12）。",
    )
    ckd_stage: CKDStage | None = Field(
        default=None,
        description="CKD 分期。≥3 触发复杂（O13）；孤立一次肌酐异常不能确诊。",
    )
    cad: YesNoUnknown | None = Field(
        default=None,
        description="冠心病 CAD。已确诊并存即触发复杂（O14）。",
    )
    complex_surgery_history: YesNoUnknown | None = Field(
        default=None,
        description="复杂手术/多次再干预史（FEVAR/BEVAR/redo）。O23。",
    )

    # ==================================================================
    # 事实层 · 一致性
    # ==================================================================
    evidence_conflict: YesNoUnknown | None = Field(
        default=None,
        description="证据冲突标记（指南与影像等关键证据结论矛盾）。O24。人工可覆写。",
    )

    # ==================================================================
    # 判定层（确定性代码派生 —— 详见 derive() ；当前为占位）
    # 说明：这些字段由事实层计算得出，**禁止 LLM 直接写入**。
    # ==================================================================
    urgency_flag: bool = Field(
        default=False,
        description="临床指定急症标志（人工/系统显式置位）。独立于自动判定；置位即最高优先。O01。",
    )
    # --- 以下字段待 derive() 实现后由 validator 自动填充 ---
    urgency_triggered: bool | None = Field(
        default=None,
        description="[派生] 急诊触发 = urgency_flag ∨ 破裂 ∨ 症状性 ∨ 休克 ∨ 出血 ∨ 急性缺血 ∨ 灌注障碍 ∨ 脓毒症。",
    )
    is_special_lesion: bool | None = Field(
        default=None,
        description="[派生] 特殊病变标记（感染/炎症/PAU/IMH/IAAD/假性/囊状/遗传/恶性）。O21。",
    )
    complex_anatomy: bool | None = Field(
        default=None,
        description="[派生] 复杂解剖标记（颈长<15 ∨ 成角>45 ∨ 入路<7 ∨ 近肾/旁肾 ∨ 血栓钙化>50 ∨ 迂曲）。",
    )
    severe_comorbidity: bool | None = Field(
        default=None,
        description="[派生] 严重合并症标记（NYHA≥III ∨ COPD ∨ CKD≥3 ∨ CAD）。",
    )
    guideline_eligible: bool | None = Field(
        default=None,
        description="[派生] 指南模式适用（急诊/复杂均已排除 ∧ 资料齐全 ∧ 低复杂度）。O26, O27。",
    )
    missing_critical_fields: list[str] = Field(
        default_factory=list,
        description="[派生] 关键字段缺失清单（见 CRITICAL_FACT_FIELDS）。非空即触发复杂 + 置信度×0.5。O25。",
    )

    # ==================================================================
    # 输出层（确定性代码派生）
    # ==================================================================
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="[派生] 置信度（0.00~1.00）。关键字段缺失时 ×0.5。医学判断仍需人工审核。",
    )
    manual_review_required: bool | None = Field(
        default=None,
        description="[派生] 需人工复核（缺失/冲突/无法识别 时置真）。O24, O25。",
    )
    route_mode: RouteMode | None = Field(
        default=None,
        description="[派生] 最终路由模式。优先级：急诊 > 复杂 > 指南。",
    )

    # ==================================================================
    # 审计留痕（跨层辅助结构；**不计入**设计表的 51 个临床字段）
    # 依据：设计表「审计留痕」列 + 交接文档第六节。
    # ==================================================================
    field_evidence: dict[str, FieldProvenance] = Field(
        default_factory=dict,
        description="事实层逐字段证据链：字段名 → 原文出处 / 写入者 / 置信度 / 覆写痕迹。"
        "判定层与输出层的留痕分别由 RouteResult.trace 与 FinalRecommendation 承载。",
    )
    urgency_flag_audit: UrgencyFlagAudit | None = Field(
        default=None,
        description="urgency_flag 的置位留痕（置位者 + 时间戳 + 理由）。O01 审计要求。",
    )

    # ==================================================================
    # 校验
    # ==================================================================
    @field_validator("age")
    @classmethod
    def _check_age_plausible(cls, v: int | None) -> int | None:
        """年龄合理性（额外护栏；Field 已限制 0~120）。"""
        if v is not None and v < 18:
            raise ValueError("age 小于 18：本系统面向成人主动脉瘤，请核实抽取结果。")
        return v

    @field_validator(*ENUM_FACT_FIELDS, mode="before")
    @classmethod
    def _strip_enum_annotation(cls, v: object) -> object:
        """容忍「设计表原文」写法：``有（活动性）`` → 枚举核心取值 ``有``。

        抽取层可能直接照抄设计表 / 表2 的带注释写法；若不归一化，合法取值会被
        pydantic 判为非法（可用性缺陷）。本步是**纯格式归一化**，不做临床推断。
        """
        if isinstance(v, list):
            return [strip_enum_annotation(x) if isinstance(x, str) else x for x in v]
        if isinstance(v, str):
            return strip_enum_annotation(v)
        return v

    @field_validator("anatomy_level", mode="before")
    @classmethod
    def _normalize_anatomy_level(cls, v: object) -> object:
        """自由文本 → :class:`AnatomyLevel`（表1 取值）。未识别直接报错，不得猜测。"""
        if v is None or isinstance(v, AnatomyLevel):
            return v
        return AnatomyLevel.normalize(str(v))

    @field_validator("lesion_morphology", mode="before")
    @classmethod
    def _normalize_lesion_morphology(cls, v: object) -> object:
        """自由文本 → :class:`LesionMorphology`。未识别直接报错，不得猜测。"""
        if v is None or isinstance(v, LesionMorphology):
            return v
        return LesionMorphology.normalize(str(v))

    @field_validator(*ONE_DECIMAL_FIELDS, mode="before")
    @classmethod
    def _quantize_one_decimal(cls, v: object) -> object:
        """设计表「数字（1位小数）」：落库前归一化（ROUND_HALF_UP）。"""
        return _quantize(v, 1)

    @field_validator("confidence", mode="before")
    @classmethod
    def _quantize_confidence(cls, v: object) -> object:
        """设计表「数字（2位小数）」：置信度归一化。"""
        return _quantize(v, 2)

    @field_validator("field_evidence")
    @classmethod
    def _check_field_evidence_keys(
        cls, v: dict[str, FieldProvenance]
    ) -> dict[str, FieldProvenance]:
        """证据链只允许挂在已声明字段上，防止写入幽灵字段（审计完整性）。"""
        unknown = sorted(set(v) - set(cls.model_fields))
        if unknown:
            raise ValueError(f"field_evidence 含未声明字段 {unknown}；证据链不得挂幽灵字段。")
        return v


def derive(case: VascCase) -> VascCase:
    """确定性派生入口：执行 P0a~P8 流水线，回填判定层与输出层字段。

    ⚠️ 本函数为**纯确定性代码**，禁止引入任何 LLM 客户端（审计红线）。
    ⚠️ 真正的判定逻辑位于 ``src/rules/router.py``，此处只做「执行 + 回填」，
       保证数据模型与规则层解耦（模型管结构，规则管判定）。

    已确认口径：
        · missing 判定集 = :data:`CRITICAL_FACT_FIELDS`（6 个事实层字段）；
        · 规则版本号 = 复合版本串（表1 + 表2），见 ``src/rules/version.py``。

    返回：
        同一个 ``case`` 对象（已就地回填），便于链式调用。
    """
    # 延迟导入：避免 models ← rules ← models 的循环引用（rules 也 TYPE_CHECKING models）
    from ...rules.router import route

    result = route(case)

    # ---- 回填判定层 ----
    case.urgency_triggered = result.urgency_triggered
    case.is_special_lesion = result.is_special_lesion
    case.complex_anatomy = result.complex_anatomy
    case.severe_comorbidity = result.severe_comorbidity
    case.guideline_eligible = result.guideline_eligible
    case.missing_critical_fields = list(result.missing_critical_fields)

    # ---- 回填输出层 ----
    case.confidence = result.confidence
    case.manual_review_required = result.manual_review_required
    case.route_mode = result.route_mode

    return case


__all__ = [
    "AUDIT_FIELDS",
    "CRITICAL_FACT_FIELDS",
    "ENUM_FACT_FIELDS",
    "ONE_DECIMAL_FIELDS",
    "VascCase",
    "derive",
]
