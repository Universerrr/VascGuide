"""路由分支定向覆盖测试 —— 补齐 ``src/rules/router.py`` 中此前无病例触发的判定分支。

与 ``tests/test_preop.py`` 的分工：
    ``test_preop.py`` 是**路由基线**（断言一经确立不得修改），只覆盖每条路径的
    代表性入口；本文件针对基线未触及的 **13 行**做定向回归保护，两者互补，
    且**不修改**基线文件任何一个字符。

覆盖对象分两类，验证手法不同：

1. **可达分支（10 处）** —— 真实存在、但此前无任何病例走到：
   ``219`` / ``221`` / ``239`` / ``242``（P2·O21 炎症证据 / 遗传结缔组织病 /
   「5其他特殊」病种 / 术后感染-瘘并发症）、``269``（P3·O18 瘤颈血栓钙化）、
   ``285`` / ``287`` / ``293``（P3·O23 复杂修复史 / 再干预史 / 术后并发症）、
   ``313``（P4·O14 冠心病）、``337``（P7·O26 非指南病种）。
   每条断言同时校验「模式 + 规则编号 + 派生标记 + 置信度」，避免只覆盖到行、
   却锁不住口径。

2. **不可达防御分支（3 处）** —— ``329``（P6 病种无法识别的二级判定）、
   ``355``（P8 前置否决）、``452``（P8 否决后的复杂兜底）。在 ``route()`` 的
   调用契约下它们**不可达**：P6 已对 ``missing`` 非空短路，而走到 P8 的前提
   是 P6 未命中（即 ``missing`` 为空），两个条件互斥。
   对这类分支用「三重钉法」，既拿到覆盖、又不掩盖「不可达」这一事实：
     · 不变量测试 —— 证明流水线内确实不可达（任一关键字段缺失都在 P6 被拦下）；
     · 函数级测试 —— 证明被绕开的那段逻辑本身行为正确；
     · 契约演练 —— 临时让 P6 放行，证明 P8 否决路径仍然可用，即这三行是
       **防御性冗余**而非错误代码（P6 契约一旦变更即可立即生效）。

运行：``uv run pytest tests/test_router_branches.py -v``
"""

from __future__ import annotations

import pytest

from src.models.enums import (
    DiseaseCategory,
    EndoleakType,
    InfectionEvidence,
    PriorRepair,
    RouteMode,
    YesNoUnknown,
)
from src.models.preop.case import CRITICAL_FACT_FIELDS, VascCase
from src.rules.router import (
    NECK_THROMBUS_CALC_THRESHOLD_PCT,
    route,
    step_p6_missing,
    step_p8_prerequisites,
)

# 复用基线工厂，保证「字段齐全的指南病例」只有一处定义，避免两份默认口径漂移。
from tests.test_preop import make_case


# ===========================================================================
# 可达分支 · P2 特殊病变（O21）
# ===========================================================================
class TestP2SpecialLesionBranches:
    """P2·O21 中四个此前无用例触发的入口。"""

    def test_inflammatory_evidence(self) -> None:
        """炎症证据 = 有 → 特殊病变（219）。"""
        result = route(make_case(inflammatory_evidence=YesNoUnknown.YES))
        assert result.route_mode is RouteMode.COMPLEX
        assert result.is_special_lesion
        assert "炎症证据" in result.reason
        assert result.confidence == 0.90  # 字段齐全，是真实命中而非缺失降级

    def test_genetic_syndrome(self) -> None:
        """遗传 / 结缔组织病 = 有 → 特殊病变（221）。"""
        result = route(make_case(genetic_syndrome=YesNoUnknown.YES))
        assert result.route_mode is RouteMode.COMPLEX
        assert result.is_special_lesion
        assert "遗传" in result.reason

    def test_other_special_category(self) -> None:
        """病种含「5其他特殊」→ 特殊病变（239）。"""
        result = route(make_case(disease_category=[DiseaseCategory.OTHER_SPECIAL]))
        assert result.route_mode is RouteMode.COMPLEX
        assert result.is_special_lesion
        assert DiseaseCategory.OTHER_SPECIAL.value in result.reason

    def test_postop_infection_complication(self) -> None:
        """术后「感染 / 瘘」并发症 → 走 P2 特殊病变（242），早于 P3 的术后分支。"""
        result = route(make_case(postop_complication="支架移植物感染"))
        assert result.route_mode is RouteMode.COMPLEX
        assert result.is_special_lesion
        assert "术后感染/瘘" in result.reason

    def test_suspected_infection_is_not_affirmative(self) -> None:
        """口径反例：「疑似感染」≠「有感染」（O21），不得误升级为特殊病变。

        ``InfectionEvidence.SUSPECTED`` 与 ``YesNoUnknown.YES`` 的 value 不同，
        ``_is_truthy`` 只认「有」—— 这是四态枚举独立成类的全部意义，必须钉住。
        """
        result = route(make_case(infection_evidence=InfectionEvidence.SUSPECTED))
        assert not result.is_special_lesion
        assert result.route_mode is RouteMode.GUIDELINE


# ===========================================================================
# 可达分支 · P3 复杂解剖 / 复杂手术（O15~O23）
# ===========================================================================
class TestP3ComplexAnatomyBranches:
    def test_neck_thrombus_calc_over_threshold(self) -> None:
        """O18 瘤颈血栓 / 钙化超阈值 → 复杂解剖（269）。"""
        result = route(make_case(neck_thrombus_calc_pct=NECK_THROMBUS_CALC_THRESHOLD_PCT + 1))
        assert result.route_mode is RouteMode.COMPLEX
        assert result.complex_anatomy
        assert "O18" in result.reason

    @pytest.mark.parametrize("pct", [0, NECK_THROMBUS_CALC_THRESHOLD_PCT])
    def test_neck_thrombus_calc_at_or_below_threshold(self, pct: int) -> None:
        """口径边界：O18 是**严格大于**阈值，等于阈值不触发。"""
        result = route(make_case(neck_thrombus_calc_pct=pct))
        assert result.route_mode is RouteMode.GUIDELINE
        assert not result.complex_anatomy

    @pytest.mark.parametrize("repair", [PriorRepair.FEVAR, PriorRepair.BEVAR, PriorRepair.OTHER])
    def test_complex_prior_repair(self, repair: PriorRepair) -> None:
        """O23 复杂修复史（FEVAR / BEVAR / 其他）→ 复杂（285）。

        EVAR / OSR 属常规修复，**不在**该集合内，故单独反例见下一用例。
        """
        result = route(make_case(prior_repair=repair))
        assert result.route_mode is RouteMode.COMPLEX
        assert result.complex_anatomy
        assert "O23" in result.reason

    def test_complex_surgery_history_without_prior_repair(self) -> None:
        """O23 无既往修复 + 复杂手术 / 多次再干预史 = 有 → 复杂（287）。"""
        result = route(make_case(complex_surgery_history=YesNoUnknown.YES))
        assert result.route_mode is RouteMode.COMPLEX
        assert result.complex_anatomy
        assert "O23" in result.reason

    def test_postop_complication_without_prior_repair(self) -> None:
        """O23 无既往修复 + 术后并发症关键词 → 复杂（293）。

        注意：该出口的 reason **不带规则编号**（仅「P3 术后并发症：…」），
        与 O15~O20 各出口的文案格式不同，故此处按文案断言。
        """
        result = route(make_case(postop_complication="Ⅱ型内漏伴瘤囊增大"))
        assert result.route_mode is RouteMode.COMPLEX
        assert result.complex_anatomy
        assert "术后并发症" in result.reason

    @pytest.mark.parametrize("repair", [PriorRepair.EVAR, PriorRepair.OSR])
    def test_postop_complication_ignored_when_prior_repair_present(
        self, repair: PriorRepair
    ) -> None:
        """口径反例：已有修复史者不因「术后并发症」判为术前复杂（288 的 ``is NONE`` 前提）。

        这类病例属术后随访路径，应走 P7 指南（此处的内漏状态为「无」，属稳定随访）。
        """
        result = route(
            make_case(
                disease_category=[DiseaseCategory.POSTOPERATIVE],
                prior_repair=repair,
                postop_complication="内漏",
                endoleak_type=EndoleakType.NONE,
            )
        )
        assert result.route_mode is RouteMode.GUIDELINE
        assert not result.complex_anatomy


# ===========================================================================
# 可达分支 · P4 严重合并症（O11~O14）
# ===========================================================================
class TestP4ComorbidityBranches:
    def test_cad(self) -> None:
        """O14 冠心病 CAD = 有 → 复杂（313）。"""
        result = route(make_case(cad=YesNoUnknown.YES))
        assert result.route_mode is RouteMode.COMPLEX
        assert result.severe_comorbidity
        assert "O14" in result.reason


# ===========================================================================
# 可达分支 · P7 指南场景（O26）
# ===========================================================================
class TestP7GuidelineBranches:
    @pytest.mark.parametrize(
        "category",
        [DiseaseCategory.SYMPTOMATIC_UNRUPTURED, DiseaseCategory.RUPTURED_OR_SUSPECTED],
    )
    def test_non_guideline_category_falls_back_to_complex(self, category: DiseaseCategory) -> None:
        """O26 非指南病种 → P7 不命中（337），由 P7b 兜底复杂 + 人工复核。

        构造说明：这里只给「病种标签」，症状 / 破裂**事实字段**保持基线（无 / 未破裂），
        因此 P1 不触发。该用例同时钉住两件事——① 病种标签本身不足以触发急诊；
        ② 非指南标签不得被默认判为「稳定」。
        """
        result = route(make_case(disease_category=[category]))
        assert result.route_mode is RouteMode.COMPLEX
        assert result.manual_review_required
        assert not result.guideline_eligible
        p7 = next(t for t in result.trace if t.order == "P7")
        assert p7.result is False
        assert any(t.order == "P7b" for t in result.trace)


# ===========================================================================
# 不可达防御分支 · 不变量（证明流水线内不可达）
# ===========================================================================
class TestUnreachableDefensiveBranches:
    """P6 二级判定（329）、P8 前置否决（355）与 P8 兜底（452）的可达性论证。

    不可达证明：走到 P8 的前提是 P6 未命中；P6 命中条件之一是 ``missing`` 非空；
    而 P8 的否决条件恰是 ``missing`` 非空 —— 两者互斥。故 P8 否决路径恒不执行，
    连带其后的复杂兜底（452）也不执行。
    """

    @pytest.mark.parametrize("field", CRITICAL_FACT_FIELDS)
    def test_any_missing_critical_field_blocks_before_p8(self, field: str) -> None:
        """任一关键字段缺失都在 P6 被拦截，且**不会**进入 P8（355 / 452 不可达的机械证明）。"""
        value: object = [] if field == "disease_category" else None
        result = route(make_case(**{field: value}))

        assert result.route_mode is RouteMode.COMPLEX
        assert result.confidence == 0.45  # 0.90 × MISSING_PENALTY
        assert result.manual_review_required
        assert field in result.missing_critical_fields
        assert not any(t.order == "P8" for t in result.trace)

    def test_empty_category_is_caught_by_missing_guard_first(self) -> None:
        """病种为空时，由 P6 的 ``missing`` 分支（326）先返回，二级判定（329）不执行。

        两条分支的文案不同，据此可判定实际走的是哪一条。
        """
        result = route(make_case(disease_category=[]))
        note = next(t.note for t in result.trace if t.order == "P6")
        assert "关键字段缺失" in note
        assert "病种无法识别" not in note


# ===========================================================================
# 不可达防御分支 · 函数级与契约演练（证明逻辑本身正确）
# ===========================================================================
class TestDefensiveBranchLogic:
    def test_p6_secondary_judgment_works_at_function_level(self) -> None:
        """函数级：显式传入空 ``missing`` 时，329 的二级判定确实生效。

        它保证「病种无法识别」不是死文案 —— 一旦上游 ``missing`` 判定口径收紧
        （例如 disease_category 不再计入关键字段），该分支会立刻接管。
        """
        hit, note = step_p6_missing(make_case(disease_category=[]), [])
        assert hit is True
        assert "病种无法识别" in note

    def test_p8_denial_works_at_function_level(self) -> None:
        """函数级：355 的前置否决在 ``missing`` 非空时正确返回，且报出缺失个数。"""
        ok, note = step_p8_prerequisites(make_case(), ["sex", "rupture_status"])
        assert ok is False
        assert "仍缺 2 个关键字段" in note

    def test_p8_denial_path_still_works_when_p6_lets_through(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """契约演练：临时让 P6 放行，验证 P8 否决路径（355）与兜底返回（452）仍然可用。

        ``sex`` 置空使 ``missing`` 非空（而 ``disease_category`` 保留指南病种，
        以便 P7 命中、真正走到 P8）。演练结果必须仍是「复杂 + 人工复核 + 置信度×0.5」，
        证明这两行是**防御性冗余**而不是错误代码。
        """
        from src.rules import router as router_module

        monkeypatch.setattr(
            router_module,
            "step_p6_missing",
            lambda case, missing: (False, "P6 演练：临时放行"),
        )

        result = route(make_case(sex=None))

        assert result.missing_critical_fields == ["sex"]
        assert result.route_mode is RouteMode.COMPLEX
        assert result.confidence == 0.45
        assert result.manual_review_required
        p8 = next(t for t in result.trace if t.order == "P8")
        assert p8.result is False
        assert "仍缺 1 个关键字段" in p8.note


# ===========================================================================
# 缺省值语义：未提及 ≠ 无（table2@v1.6 修复的 P7 术后内漏缺省值穿透）
# ===========================================================================
class TestMissingValueSemantics:
    """术后随访的内漏状态：只有「明确无内漏 / 稳定Ⅱ型」可放行指南。

    背景：原实现用 ``endoleak_type is not None`` 作守卫，``None``（未提及）会跌出
    该分支，被下游「低复杂度指南病种」出口放行为指南 + 免人工复核 + 置信度 0.90 ——
    等价于把「没查」当成「查过了且无内漏」。本类把「未提及」与「无」的区分钉死，
    防止后来者再把否定式守卫写回来。
    """

    @staticmethod
    def _postop(**overrides: object) -> VascCase:
        return make_case(
            disease_category=[DiseaseCategory.POSTOPERATIVE],
            prior_repair=PriorRepair.EVAR,
            **overrides,
        )

    @pytest.mark.parametrize(
        ("label", "endoleak", "expected"),
        [
            ("未提及 → 复杂（安全侧）", None, RouteMode.COMPLEX),
            ("不明 → 复杂", EndoleakType.UNKNOWN, RouteMode.COMPLEX),
            ("Ⅰa 型高危 → 复杂", EndoleakType.IA, RouteMode.COMPLEX),
            ("Ⅲa 型高危 → 复杂", EndoleakType.IIIA, RouteMode.COMPLEX),
            ("Ⅳ 型 → 复杂", EndoleakType.IV, RouteMode.COMPLEX),
            ("明确无内漏 → 指南", EndoleakType.NONE, RouteMode.GUIDELINE),
            ("稳定Ⅱ型 → 指南", EndoleakType.II, RouteMode.GUIDELINE),
        ],
    )
    def test_endoleak_state_decides_route(
        self, label: str, endoleak: EndoleakType | None, expected: RouteMode
    ) -> None:
        result = route(self._postop(endoleak_type=endoleak))
        assert result.route_mode is expected, label

    def test_unmentioned_is_not_treated_as_absent_endoleak(self) -> None:
        """核心回归：未提及必须走安全侧，且 note 要如实声明「未提及」。"""
        result = route(self._postop(endoleak_type=None))
        assert result.route_mode is RouteMode.COMPLEX
        assert result.guideline_eligible is False
        assert result.manual_review_required
        p7 = next(t for t in result.trace if t.order == "P7")
        assert p7.result is False
        assert "未提及" in p7.note
        assert "非稳定Ⅱ型" in p7.note

    def test_unmentioned_keeps_confidence_but_flags_review(self) -> None:
        """6 项关键字段齐全 ⇒ 置信度不下调（0.90），但人工复核标记必须置真。"""
        result = route(self._postop(endoleak_type=None))
        assert result.missing_critical_fields == []
        assert result.confidence == 0.90
        assert result.manual_review_required

    def test_p7b_fallback_note_covers_postop_entry(self) -> None:
        """P7b 兜底文案须涵盖「内漏状态不可确认稳定」，而不只说「非指南病种」。"""
        result = route(self._postop(endoleak_type=None))
        p7b = next(t for t in result.trace if t.order == "P7b")
        assert "术后内漏" in p7b.note
        assert result.reason == p7b.note

    def test_explicit_stable_values_are_unaffected(self) -> None:
        """对照组：显式填「无内漏 / Ⅱ型」的病例结论、置信度、复核标记均不变。"""
        for et in (EndoleakType.NONE, EndoleakType.II):
            result = route(self._postop(endoleak_type=et))
            assert result.route_mode is RouteMode.GUIDELINE, et
            assert result.confidence == 0.90, et
            assert result.manual_review_required is False, et
