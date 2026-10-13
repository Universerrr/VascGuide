"""数据模型契约测试：VascCase 与设计表（唯一权威口径）的一致性。

为什么单独成文件？
    `tests/test_preop.py` 的 41 项是**既有行为回归基线**（路由语义），本文件锁定
    **数据契约**（字段清单 / 枚举取值 / 归一化 / 精度 / 审计留痕），两者职责不同，
    分开后基线改动可被审计。

覆盖：
    1. 字段清单：与设计表 51 个临床字段一一对应，无缺失、无多余；
    2. 枚举契约：6 个枚举取值与设计表「取值/枚举」列逐字一致（含「疑似」「未核实」
       「未描述」「既往已愈」等易被吞掉的态）；
    3. 归一化：anatomy_level / lesion_morphology 自由文本 → 枚举；未识别必须报错；
    4. 精度契约：1 位小数 / 2 位小数，ROUND_HALF_UP；
    5. 审计留痕：FieldProvenance / UrgencyFlagAudit / field_evidence 键完整性；
    6. 判定回归：换枚举后 P2/P3 不得静默失效（`_is_truthy` 身份比较陷阱）。

运行：``uv run pytest tests/test_model_contract.py -v``
"""

from __future__ import annotations

import pytest

from src.models.audit import FieldProvenance, UrgencyFlagAudit
from src.models.enums import (
    AnatomyLevel,
    DiseaseCategory,
    FieldWriter,
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
)
from src.models.preop.case import (
    AUDIT_FIELDS,
    CRITICAL_FACT_FIELDS,
    ENUM_FACT_FIELDS,
    VascCase,
    derive,
)
from src.rules.router import route
from src.rules.version import RULESET_VERSION

# 设计表 Sheet `01_字段总表` 的 51 个临床字段（顺序即表格顺序）。
DESIGN_TABLE_CLINICAL_FIELDS: tuple[str, ...] = (
    "case_id",
    "source_note",
    "age",
    "sex",
    "disease_category",
    "lesion_subtype",
    "temporal_status",
    "diagnosis_certainty",
    "symptom_aaa_related",
    "symptom_type",
    "pain_cause_attributed",
    "rupture_status",
    "hemodynamic_instability",
    "active_hemorrhage",
    "acute_limb_ischemia",
    "visceral_malperfusion",
    "septic_shock",
    "max_diameter_mm",
    "iliac_diameter_mm",
    "growth_rate_mm_per_year",
    "lesion_morphology",
    "neck_length_mm",
    "neck_angle_deg",
    "access_diameter_mm",
    "anatomy_level",
    "neck_thrombus_calc_pct",
    "tortuosity",
    "prior_repair",
    "postop_complication",
    "endoleak_type",
    "infection_evidence",
    "inflammatory_evidence",
    "special_lesion_type",
    "genetic_syndrome",
    "malignancy",
    "heart_failure_nyha",
    "copd",
    "ckd_stage",
    "cad",
    "complex_surgery_history",
    "evidence_conflict",
    "urgency_flag",
    "urgency_triggered",
    "is_special_lesion",
    "complex_anatomy",
    "severe_comorbidity",
    "guideline_eligible",
    "missing_critical_fields",
    "confidence",
    "manual_review_required",
    "route_mode",
)

# 设计表 Sheet `01_字段总表` 中「类型 = 枚举」的 28 个字段（含 list 型 disease_category）。
DESIGN_TABLE_ENUM_FIELDS: tuple[str, ...] = (
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
    "lesion_morphology",
    "anatomy_level",
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


def make_case(**overrides: object) -> VascCase:
    """构造默认走指南模式、无字段缺失的基线病例（与 test_preop.py 同构）。"""
    base: dict[str, object] = {
        "case_id": "CONTRACT-000",
        "age": 72,
        "sex": Sex.MALE,
        "temporal_status": TemporalStatus.CURRENT,
        "symptom_aaa_related": SymptomAAA.ABSENT,
        "rupture_status": RuptureStatus.INTACT,
        "prior_repair": PriorRepair.NONE,
        "disease_category": [DiseaseCategory.ASYMPTOMATIC],
        "max_diameter_mm": 42.0,
        "neck_length_mm": 25.0,
        "neck_angle_deg": 20.0,
        "access_diameter_mm": 9.0,
        "anatomy_level": "肾下",
    }
    base.update(overrides)
    return VascCase(**base)  # type: ignore[arg-type]


# ===========================================================================
# 1. 字段清单契约
# ===========================================================================
class TestFieldInventory:
    def test_clinical_field_count_is_51(self) -> None:
        clinical = set(VascCase.model_fields) - set(AUDIT_FIELDS)
        assert len(clinical) == 51

    def test_clinical_field_names_match_design_table(self) -> None:
        clinical = set(VascCase.model_fields) - set(AUDIT_FIELDS)
        assert clinical == set(DESIGN_TABLE_CLINICAL_FIELDS)

    def test_audit_fields_are_the_only_extras(self) -> None:
        """除 51 临床字段外，只允许存在 2 个审计辅助字段。"""
        assert set(VascCase.model_fields) == set(DESIGN_TABLE_CLINICAL_FIELDS) | set(AUDIT_FIELDS)
        assert len(AUDIT_FIELDS) == 2

    def test_every_field_is_documented(self) -> None:
        """每个字段都必须有中文 description（对应设计表「备注」列）。"""
        undocumented = [n for n, f in VascCase.model_fields.items() if not f.description]
        assert undocumented == []

    def test_audit_fields_not_in_critical_set(self) -> None:
        assert set(AUDIT_FIELDS).isdisjoint(set(CRITICAL_FACT_FIELDS))

    def test_every_enum_field_is_normalized(self) -> None:
        """设计表标记为「枚举」的 28 个字段必须全部被归一化校验器覆盖。

        防止今后新增枚举字段时漏挂校验，导致「照抄设计表原文」被判非法。
        """
        covered = set(ENUM_FACT_FIELDS) | {"anatomy_level", "lesion_morphology"}
        assert covered == set(DESIGN_TABLE_ENUM_FIELDS)
        assert covered <= set(VascCase.model_fields)


# ===========================================================================
# 2. 枚举契约（取值必须与设计表逐字一致）
# ===========================================================================
class TestEnumContract:
    def test_infection_evidence_four_states(self) -> None:
        """感染证据为四态，「疑似」必须存在（O21：仅发热/菌血症不足以确诊）。"""
        assert tuple(m.value for m in InfectionEvidence) == ("有", "无", "疑似", "未提及")

    def test_pain_attribution_three_states(self) -> None:
        """「未核实」必须与「否」区分（否认腹痛 ≠ 无症状）。"""
        assert tuple(m.value for m in PainAttribution) == ("是", "否", "未核实")

    def test_tortuosity_uses_not_described(self) -> None:
        assert tuple(m.value for m in Tortuosity) == ("有", "无", "未描述")

    def test_lesion_morphology_values(self) -> None:
        assert tuple(m.value for m in LesionMorphology) == ("梭形", "囊状", "不规则", "未描述")

    def test_anatomy_level_values(self) -> None:
        assert tuple(m.value for m in AnatomyLevel) == (
            "肾下",
            "短颈肾下",
            "近肾",
            "旁肾",
            "近内脏",
            "IV型TAAA",
        )

    def test_malignancy_status_four_states(self) -> None:
        """「既往已愈」必须与「有（活动性）」区分。"""
        assert tuple(m.value for m in MalignancyStatus) == ("有", "无", "既往已愈", "未提及")

    def test_all_enums_are_str_for_audit_serialization(self) -> None:
        for member in (
            InfectionEvidence.SUSPECTED,
            PainAttribution.UNVERIFIED,
            Tortuosity.NOT_DESCRIBED,
            LesionMorphology.SACCULAR,
            AnatomyLevel.TYPE_IV_TAAA,
            MalignancyStatus.RESOLVED,
        ):
            assert isinstance(member, str)


# ===========================================================================
# 3. 归一化契约
# ===========================================================================
class TestNormalization:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("近肾腹主动脉瘤", AnatomyLevel.JUXTARENAL),
            ("近肾", AnatomyLevel.JUXTARENAL),
            ("肾下型腹主动脉瘤", AnatomyLevel.INFRARENAL),
            ("短颈肾下AAA", AnatomyLevel.SHORT_NECK_INFRARENAL),
            ("旁肾腹主动脉瘤", AnatomyLevel.PARARENAL),
            ("近内脏主动脉瘤", AnatomyLevel.PARAVISCERAL),
            ("IV型胸腹主动脉瘤", AnatomyLevel.TYPE_IV_TAAA),
            ("iv型taaa", AnatomyLevel.TYPE_IV_TAAA),
            ("  肾下  ", AnatomyLevel.INFRARENAL),
        ],
    )
    def test_anatomy_level_normalize(self, text: str, expected: AnatomyLevel) -> None:
        assert AnatomyLevel.normalize(text) is expected

    def test_short_neck_wins_over_infrarenal_substring(self) -> None:
        """「短颈肾下」含「肾下」子串，必须优先归为短颈肾下（具体优先）。"""
        assert AnatomyLevel.normalize("短颈肾下") is AnatomyLevel.SHORT_NECK_INFRARENAL

    def test_anatomy_level_unrecognized_raises(self) -> None:
        """未识别不得猜测，必须报错交人工复核。"""
        with pytest.raises(ValueError, match="anatomy_level 无法归一化"):
            AnatomyLevel.normalize("胸主动脉瘤")

    def test_anatomy_level_none_and_blank(self) -> None:
        assert AnatomyLevel.normalize(None) is None
        assert AnatomyLevel.normalize("   ") is None

    def test_lesion_morphology_normalize(self) -> None:
        assert LesionMorphology.normalize("囊状扩张") is LesionMorphology.SACCULAR
        assert LesionMorphology.normalize("梭形") is LesionMorphology.FUSIFORM
        assert LesionMorphology.normalize("不规则形") is LesionMorphology.IRREGULAR
        assert LesionMorphology.normalize(None) is None

    def test_lesion_morphology_unrecognized_raises(self) -> None:
        with pytest.raises(ValueError, match="lesion_morphology 无法归一化"):
            LesionMorphology.normalize("形态不详")

    def test_case_accepts_free_text_and_normalizes(self) -> None:
        """模型入口即归一化：抽出自由文本也能落库为枚举。"""
        case = make_case(anatomy_level="近肾腹主动脉瘤", lesion_morphology="囊状")
        assert case.anatomy_level is AnatomyLevel.JUXTARENAL
        assert case.lesion_morphology is LesionMorphology.SACCULAR

    def test_case_rejects_unrecognized_anatomy_level(self) -> None:
        with pytest.raises(ValueError):
            make_case(anatomy_level="肾上型")


# ===========================================================================
# 3b. 设计表原文容错（带括号注释的取值）
# ===========================================================================
class TestDesignTableLiteralTolerance:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("有（活动性）", "有"),
            ("有（休克/低血压/晕厥）", "有"),
            ("有（影像/病原支持）", "有"),
            ("是（归因AAA）", "是"),
            ("未提及", "未提及"),
            ("IV型TAAA", "IV型TAAA"),
        ],
    )
    def test_strip_enum_annotation(self, raw: str, expected: str) -> None:
        from src.models.enums import strip_enum_annotation

        assert strip_enum_annotation(raw) == expected

    def test_malignancy_accepts_design_table_literal(self) -> None:
        """照抄设计表原文「有（活动性）」必须可用（此前会被判为非法枚举值）。"""
        case = make_case(malignancy="有（活动性）")
        assert case.malignancy is MalignancyStatus.ACTIVE

    def test_pain_attribution_accepts_design_table_literal(self) -> None:
        assert make_case(pain_cause_attributed="是（归因AAA）").pain_cause_attributed is (
            PainAttribution.ATTRIBUTED_TO_AAA
        )

    def test_hemodynamic_instability_accepts_annotation(self) -> None:
        case = make_case(hemodynamic_instability="有（休克/低血压/晕厥）")
        assert case.hemodynamic_instability is YesNoUnknown.YES

    def test_infection_evidence_with_annotation(self) -> None:
        case = make_case(infection_evidence="有（影像/病原支持）")
        assert case.infection_evidence is InfectionEvidence.YES

    def test_routing_unaffected_by_annotation(self) -> None:
        """带注释写法与核心取值必须路由一致（纯格式归一化）。"""
        r1 = route(make_case(malignancy="有（活动性）"))
        r2 = route(make_case(malignancy=MalignancyStatus.ACTIVE))
        assert r1.route_mode == r2.route_mode == RouteMode.COMPLEX
        assert [t.result for t in r1.trace] == [t.result for t in r2.trace]

    def test_still_rejects_unknown_value(self) -> None:
        """容错不等于放行：真·非法取值仍须被拒。"""
        with pytest.raises(ValueError):
            make_case(malignancy="疑似肿瘤")


# ===========================================================================
# 4. 精度契约
# ===========================================================================
class TestPrecision:
    def test_one_decimal_fields_round_half_up(self) -> None:
        case = VascCase(
            case_id="X",
            max_diameter_mm=42.37123,
            iliac_diameter_mm=40.05,
            growth_rate_mm_per_year=9.95,
            neck_length_mm=14.987,
            access_diameter_mm=7.04,
        )
        assert case.max_diameter_mm == 42.4
        assert case.iliac_diameter_mm == 40.1  # HALF_UP；银行家舍入会得 40.0
        assert case.growth_rate_mm_per_year == 10.0
        assert case.neck_length_mm == 15.0
        assert case.access_diameter_mm == 7.0

    def test_confidence_two_decimals(self) -> None:
        assert VascCase(case_id="X", confidence=0.87654).confidence == 0.88
        assert VascCase(case_id="X", confidence=0.125).confidence == 0.13

    def test_string_numbers_are_accepted(self) -> None:
        """LLM 常以字符串给出数值，应可解析并归一化。"""
        assert VascCase(case_id="X", max_diameter_mm="42.37").max_diameter_mm == 42.4

    def test_missing_values_stay_missing(self) -> None:
        """归一化不得把「缺失」补成默认值。"""
        case = VascCase(case_id="X")
        assert case.max_diameter_mm is None
        assert case.confidence is None

    def test_unspecified_decimal_fields_not_quantized(self) -> None:
        """设计表未标注小数位的字段（neck_angle_deg）不得被静默改写。"""
        assert VascCase(case_id="X", neck_angle_deg=20.1234).neck_angle_deg == 20.1234

    def test_unparsable_number_still_rejected(self) -> None:
        with pytest.raises(ValueError):
            VascCase(case_id="X", max_diameter_mm="abc")


# ===========================================================================
# 5. 审计留痕契约
# ===========================================================================
class TestAuditProvenance:
    def test_field_provenance_records_writer(self) -> None:
        prov = FieldProvenance(
            source_quote="CTA：肾下型AAA，最大径约42mm",
            writer=FieldWriter.IMAGING,
            confidence=0.88,
        )
        assert prov.writer is FieldWriter.IMAGING
        assert prov.overwritten_by_human is False

    def test_field_provenance_writer_required(self) -> None:
        """写入者是归责必需项，不得省略。"""
        with pytest.raises(ValueError):
            FieldProvenance(source_quote="…")  # type: ignore[call-arg]

    def test_field_provenance_extra_forbidden(self) -> None:
        with pytest.raises(ValueError):
            FieldProvenance(writer=FieldWriter.LLM, ghost=1)  # type: ignore[call-arg]

    def test_field_evidence_attaches_to_declared_field(self) -> None:
        case = make_case(
            field_evidence={
                "max_diameter_mm": FieldProvenance(
                    source_quote="最大径约42mm", writer=FieldWriter.LLM, confidence=0.9
                )
            }
        )
        assert "max_diameter_mm" in case.field_evidence

    def test_field_evidence_rejects_ghost_field(self) -> None:
        """证据链不得挂在未声明字段上（审计完整性）。"""
        with pytest.raises(ValueError, match="未声明字段"):
            make_case(field_evidence={"ghost": FieldProvenance(writer=FieldWriter.LLM)})

    def test_field_evidence_defaults_empty(self) -> None:
        assert make_case().field_evidence == {}

    def test_urgency_flag_audit(self) -> None:
        audit = UrgencyFlagAudit(
            set_by=FieldWriter.HUMAN,
            set_at="2026-10-12T14:20:00+08:00",
            reason="急诊申请：腹痛进行性加重，怀疑先兆破裂",
        )
        case = make_case(urgency_flag=True, urgency_flag_audit=audit)
        assert case.urgency_flag is True
        assert case.urgency_flag_audit is not None
        assert case.urgency_flag_audit.set_by is FieldWriter.HUMAN

    def test_urgency_flag_without_audit_still_allowed(self) -> None:
        """留痕目前不强制（避免破坏既有调用）；审计完整性强化列为待办。"""
        assert make_case(urgency_flag=True).urgency_flag_audit is None


# ===========================================================================
# 6. 判定回归（换枚举不得静默失效）
# ===========================================================================
class TestRoutingRegression:
    def test_infection_suspected_is_accepted(self) -> None:
        """M1 回归：四态枚举可承载「疑似」，此前会被 pydantic 直接拒绝。"""
        case = make_case(infection_evidence=InfectionEvidence.SUSPECTED)
        assert case.infection_evidence is InfectionEvidence.SUSPECTED

    def test_infection_suspected_does_not_trigger_p2(self) -> None:
        """当前口径：仅「有」触发 P2。是否让「疑似」也触发，属临床口径，待确认。"""
        result = route(make_case(infection_evidence=InfectionEvidence.SUSPECTED))
        assert result.route_mode is not RouteMode.COMPLEX
        assert result.is_special_lesion is False

    def test_infection_yes_still_triggers_p2(self) -> None:
        """`_is_truthy` 改为按值比较后，P2 感染判定必须仍然命中。"""
        result = route(make_case(infection_evidence=InfectionEvidence.YES))
        assert result.route_mode is RouteMode.COMPLEX
        assert result.is_special_lesion is True

    def test_legacy_yes_no_unknown_still_accepted(self) -> None:
        """向后兼容：抽取器传 YesNoUnknown.YES 仍应被接受（值相同）。"""
        result = route(make_case(infection_evidence=YesNoUnknown.YES))
        assert result.route_mode is RouteMode.COMPLEX

    def test_tortuosity_present_still_triggers_p3(self) -> None:
        """`_is_truthy` 身份比较陷阱回归：换 Tortuosity 枚举后 P3 不得失效。"""
        result = route(make_case(tortuosity=Tortuosity.PRESENT))
        assert result.route_mode is RouteMode.COMPLEX
        assert result.complex_anatomy is True

    def test_tortuosity_not_described_is_not_complex(self) -> None:
        result = route(make_case(tortuosity=Tortuosity.NOT_DESCRIBED))
        assert result.route_mode is not RouteMode.COMPLEX

    def test_active_malignancy_triggers_p2(self) -> None:
        """O21 漏实现修复：活动性恶性肿瘤此前被误判为指南模式。"""
        result = route(make_case(malignancy=MalignancyStatus.ACTIVE))
        assert result.route_mode is RouteMode.COMPLEX
        assert result.is_special_lesion is True
        assert "恶性肿瘤" in result.reason

    def test_resolved_malignancy_does_not_trigger_p2(self) -> None:
        """「既往已愈」不参与特殊病变判定。"""
        result = route(make_case(malignancy=MalignancyStatus.RESOLVED))
        assert result.is_special_lesion is False

    def test_free_text_anatomy_level_becomes_complex(self) -> None:
        result = route(make_case(anatomy_level="近肾腹主动脉瘤"))
        assert result.route_mode is RouteMode.COMPLEX
        assert result.complex_anatomy is True

    def test_design_table_decimal_does_not_flip_guideline(self) -> None:
        """精度归一化后，常规病例仍应走指南（42.37123 → 42.4，未达 55/50 阈值）。"""
        result = route(make_case(max_diameter_mm=42.37123))
        assert result.route_mode is RouteMode.GUIDELINE

    def test_ruleset_version_bumped_for_o21_fix(self) -> None:
        assert RULESET_VERSION == "table1@v1.0+table2@v1.4"
        assert route(make_case()).ruleset_version == RULESET_VERSION

    def test_derive_still_backfills_with_new_enums(self) -> None:
        case = make_case(
            infection_evidence=InfectionEvidence.YES,
            malignancy=MalignancyStatus.ACTIVE,
        )
        derive(case)
        assert case.route_mode is RouteMode.COMPLEX
        assert case.is_special_lesion is True
        assert case.confidence == 0.90
