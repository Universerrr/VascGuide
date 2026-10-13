"""术前模块测试：VascCase 数据模型 + P0a~P8 路由流水线。

覆盖：
    1. 模型层：字段校验、枚举、缺失关键字段收集；
    2. 路由层：急诊 / 复杂（P2/P3/P4/P5/P6）/ 指南（P7/P8）全分支；
    3. 审计层：判定轨迹完整、规则版本号落盘、置信度惩罚。

运行：``uv run pytest tests/test_preop.py -v``
"""

from __future__ import annotations

import pytest

from src.models.enums import (
    CKDStage,
    DiseaseCategory,
    EndoleakType,
    HeartFailureNYHA,
    PriorRepair,
    RouteMode,
    RuptureStatus,
    Sex,
    SymptomAAA,
    TemporalStatus,
    YesNoUnknown,
)
from src.models.preop.case import CRITICAL_FACT_FIELDS, VascCase, derive
from src.rules.router import collect_missing_critical_fields, route
from src.rules.version import RULESET_VERSION


# ===========================================================================
# 工厂：构造「正常基线病例」（无症状、未破裂、资料齐全 → 指南模式）
# ===========================================================================
def make_case(**overrides: object) -> VascCase:
    """构造一个默认走指南模式、无字段缺失的基线病例。"""
    base: dict[str, object] = {
        "case_id": "TEST-000",
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
# 模型层
# ===========================================================================
class TestModel:
    def test_enum_is_str(self) -> None:
        """枚举应可直接 JSON 序列化为中文。"""
        assert Sex.MALE == "男"
        assert RouteMode.EMERGENCY == "急诊模式"

    def test_extra_field_forbidden(self) -> None:
        with pytest.raises(ValueError):
            VascCase(case_id="X", unknown_field=1)  # type: ignore[call-arg]

    def test_age_plausibility_guard(self) -> None:
        with pytest.raises(ValueError):
            VascCase(case_id="X", age=15)

    def test_critical_fact_fields_are_fact_layer(self) -> None:
        """CRITICAL_FACT_FIELDS 必须全部是事实层字段（判定层不可能缺失）。"""
        derived = {
            "urgency_triggered",
            "is_special_lesion",
            "complex_anatomy",
            "severe_comorbidity",
            "guideline_eligible",
            "missing_critical_fields",
            "confidence",
            "manual_review_required",
            "route_mode",
        }
        assert derived.isdisjoint(set(CRITICAL_FACT_FIELDS))
        assert len(CRITICAL_FACT_FIELDS) == 6


# ===========================================================================
# 缺失收集（O25）
# ===========================================================================
class TestMissing:
    def test_collect_all_missing(self) -> None:
        case = VascCase(case_id="X", disease_category=[DiseaseCategory.ASYMPTOMATIC])
        missing = collect_missing_critical_fields(case)
        assert set(missing) == {
            "sex",
            "temporal_status",
            "symptom_aaa_related",
            "rupture_status",
            "prior_repair",
        }

    def test_collect_none_missing(self) -> None:
        assert collect_missing_critical_fields(make_case()) == []

    def test_empty_disease_category_counts_as_missing(self) -> None:
        case = make_case(disease_category=[])
        assert "disease_category" in collect_missing_critical_fields(case)


# ===========================================================================
# 路由层 · 急诊（P1）
# ===========================================================================
class TestEmergency:
    def test_p1_urgency_flag(self) -> None:
        result = route(make_case(urgency_flag=True))
        assert result.route_mode is RouteMode.EMERGENCY
        assert "O01" in result.reason

    def test_p1_confirmed_rupture(self) -> None:
        result = route(make_case(rupture_status=RuptureStatus.CONFIRMED))
        assert result.route_mode is RouteMode.EMERGENCY

    def test_p1_suspected_rupture(self) -> None:
        """疑似破裂也走急诊（不得因未确诊延误）。"""
        result = route(make_case(rupture_status=RuptureStatus.SUSPECTED))
        assert result.route_mode is RouteMode.EMERGENCY

    def test_p1_symptomatic(self) -> None:
        result = route(make_case(symptom_aaa_related=SymptomAAA.PRESENT))
        assert result.route_mode is RouteMode.EMERGENCY

    def test_p1_hemodynamic_instability(self) -> None:
        result = route(make_case(hemodynamic_instability=YesNoUnknown.YES))
        assert result.route_mode is RouteMode.EMERGENCY

    def test_intact_rupture_not_emergency(self) -> None:
        """「未破裂」不触发急诊（T26/T33）。"""
        result = route(make_case(rupture_status=RuptureStatus.INTACT))
        assert result.route_mode is not RouteMode.EMERGENCY


# ===========================================================================
# 路由层 · 复杂（P2~P6）
# ===========================================================================
class TestComplex:
    def test_p2_infection(self) -> None:
        result = route(make_case(infection_evidence=YesNoUnknown.YES))
        assert result.route_mode is RouteMode.COMPLEX
        assert result.is_special_lesion

    def test_p2_special_lesion_type(self) -> None:
        result = route(make_case(special_lesion_type="穿透性主动脉溃疡 PAU"))
        assert result.route_mode is RouteMode.COMPLEX

    def test_p2_infectious_category(self) -> None:
        result = route(make_case(disease_category=[DiseaseCategory.INFECTIOUS]))
        assert result.route_mode is RouteMode.COMPLEX

    def test_p3_short_neck(self) -> None:
        result = route(make_case(neck_length_mm=12.0))
        assert result.route_mode is RouteMode.COMPLEX
        assert result.complex_anatomy

    def test_p3_neck_angle(self) -> None:
        result = route(make_case(neck_angle_deg=60.0))
        assert result.route_mode is RouteMode.COMPLEX
        assert result.complex_anatomy

    def test_p3_access_diameter(self) -> None:
        result = route(make_case(access_diameter_mm=5.0))
        assert result.route_mode is RouteMode.COMPLEX

    def test_p3_growth_rate(self) -> None:
        result = route(make_case(growth_rate_mm_per_year=12.0))
        assert result.route_mode is RouteMode.COMPLEX

    def test_p3_juxtarenal(self) -> None:
        result = route(make_case(anatomy_level="近肾腹主动脉瘤"))
        assert result.route_mode is RouteMode.COMPLEX

    def test_p3_aaa_with_iliac(self) -> None:
        """AAA 合并髂动脉瘤（表1 L02）→ 复杂。"""
        result = route(
            make_case(
                disease_category=[
                    DiseaseCategory.ASYMPTOMATIC,
                    DiseaseCategory.ILIAC_ANEURYSM,
                ]
            )
        )
        assert result.route_mode is RouteMode.COMPLEX

    def test_p4_nyha3(self) -> None:
        result = route(make_case(heart_failure_nyha=HeartFailureNYHA.III))
        assert result.route_mode is RouteMode.COMPLEX
        assert result.severe_comorbidity

    def test_p4_copd(self) -> None:
        result = route(make_case(copd=YesNoUnknown.YES))
        assert result.route_mode is RouteMode.COMPLEX

    def test_p4_ckd3(self) -> None:
        result = route(make_case(ckd_stage=CKDStage.S3))
        assert result.route_mode is RouteMode.COMPLEX

    def test_p5_evidence_conflict(self) -> None:
        result = route(make_case(evidence_conflict=YesNoUnknown.YES))
        assert result.route_mode is RouteMode.COMPLEX
        assert result.manual_review_required

    def test_p6_missing_fields(self) -> None:
        case = VascCase(case_id="X", disease_category=[DiseaseCategory.ASYMPTOMATIC])
        result = route(case)
        assert result.route_mode is RouteMode.COMPLEX
        assert result.confidence == 0.45  # 0.90 × 0.5
        assert result.manual_review_required

    def test_p6_fallback_unclassified(self) -> None:
        """病种为空列表 → 兜底复杂，不得默认「稳定」。"""
        case = make_case(disease_category=[])
        result = route(case)
        assert result.route_mode is RouteMode.COMPLEX


# ===========================================================================
# 路由层 · 指南（P7/P8）
# ===========================================================================
class TestGuideline:
    def test_p7_asyptomatic_small(self) -> None:
        result = route(make_case())
        assert result.route_mode is RouteMode.GUIDELINE
        assert result.guideline_eligible
        assert result.confidence == 0.90

    def test_p7_isolated_iliac(self) -> None:
        result = route(make_case(disease_category=[DiseaseCategory.ILIAC_ANEURYSM]))
        assert result.route_mode is RouteMode.GUIDELINE

    def test_p7_postop_routine(self) -> None:
        result = route(
            make_case(
                disease_category=[DiseaseCategory.POSTOPERATIVE],
                prior_repair=PriorRepair.EVAR,
                endoleak_type=EndoleakType.NONE,
            )
        )
        assert result.route_mode is RouteMode.GUIDELINE

    def test_p7_stable_type2_endoleak(self) -> None:
        """稳定Ⅱ型内漏仍可走指南（T10）。"""
        result = route(
            make_case(
                disease_category=[DiseaseCategory.POSTOPERATIVE],
                prior_repair=PriorRepair.EVAR,
                endoleak_type=EndoleakType.II,
            )
        )
        assert result.route_mode is RouteMode.GUIDELINE

    def test_p7_type1_endoleak_is_complex(self) -> None:
        """Ⅰ型内漏为高危 → 复杂。"""
        result = route(
            make_case(
                disease_category=[DiseaseCategory.POSTOPERATIVE],
                prior_repair=PriorRepair.EVAR,
                endoleak_type=EndoleakType.IA,
            )
        )
        assert result.route_mode is RouteMode.COMPLEX


# ===========================================================================
# 审计层
# ===========================================================================
class TestAudit:
    def test_trace_records_all_steps_up_to_hit(self) -> None:
        """命中即短路 —— 急诊流程只应记录 P0a/P0b/P1，不含 P2~P8。"""
        result = route(make_case(rupture_status=RuptureStatus.CONFIRMED))
        orders = [t.order for t in result.trace]
        assert orders == ["P0a", "P0b", "P1"]

    def test_trace_contains_full_path_for_guideline(self) -> None:
        """指南流程应记录全部 P0a~P8。"""
        result = route(make_case())
        orders = [t.order for t in result.trace]
        assert orders == ["P0a", "P0b", "P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8"]

    def test_every_step_has_rule_ref(self) -> None:
        result = route(make_case())
        assert all(t.rule_ref for t in result.trace)

    def test_ruleset_version_recorded(self) -> None:
        result = route(make_case())
        assert result.ruleset_version == RULESET_VERSION
        assert result.ruleset_version.startswith("table1@")

    def test_route_is_deterministic(self) -> None:
        """相同输入 → 相同输出（可复现红线）。"""
        case = make_case()
        r1, r2 = route(case), route(case)
        assert r1.route_mode == r2.route_mode
        assert r1.confidence == r2.confidence
        assert [t.result for t in r1.trace] == [t.result for t in r2.trace]


# ===========================================================================
# derive() 回填
# ===========================================================================
class TestDerive:
    def test_derive_fills_all_derived_fields(self) -> None:
        case = make_case()
        assert case.route_mode is None  # 派生前为空
        derive(case)
        assert case.route_mode is RouteMode.GUIDELINE
        assert case.urgency_triggered is False
        assert case.guideline_eligible is True
        assert case.missing_critical_fields == []
        assert case.confidence == 0.90
        assert case.manual_review_required is False

    def test_derive_returns_same_instance(self) -> None:
        case = make_case()
        assert derive(case) is case

    def test_derive_emergency_path(self) -> None:
        case = make_case(rupture_status=RuptureStatus.SUSPECTED)
        derive(case)
        assert case.route_mode is RouteMode.EMERGENCY
        assert case.urgency_triggered is True
