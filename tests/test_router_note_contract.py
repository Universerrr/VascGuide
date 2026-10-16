"""路由 ``note`` 文本契约测试（审计证据粒度；契约见 ``src/rules/router.py`` 模块文档）。

为什么需要本文件：
    未命中步骤的 ``note`` 若不写检查项，医生就无法独立复核「该步为何未命中」——
    而「指南模式」这类结论恰恰**完全由否决链支撑**，复核主体正是这些否决项。
    契约已写进 ``router.py`` 模块文档，但此前**没有任何断言守着**；本文件把它
    变成机械检查：以后往未命中分支补代码却漏写检查项，测试立刻红。

判据（与渲染层自检同源）：
    ① 未命中步骤的 ``note`` 必须带**非空**的「（…）」检查项后缀，只有结论句即失败；
    ② 检查项含比较符（``≥``/``≤``/``<``/``>``）时必须写出实际值；两类**豁免**：
       · 项内已显式写「未提及」——那是对缺失的诚实声明（属抽取层数据缺口，
         不是 note 粒度问题）；
       · 比较符用于枚举/序数比较（如「阈值 ≥ III 级」）——本就无数字；
    ③ 分隔符必须全角（项间 ``；``、包裹全角括号），半角写法同样判失败；
    ④ **一个检查项 = 一个字段**：项内不得出现聚合词（``均无``/``均未``/``全部无``…）。
       聚合句把「未提及」与「明确为否」抹平成一个「无」，正好藏掉复核者最想看的信息
       （这条依据到底查了没有）——P1 的 5 个急性征象曾这样写过（table2@v1.7 已修）。

分工声明：本文件只校验 ``note`` **文案**，不校验任何判定结果 ——
    判定行为由 ``test_preop.py``（41 项基线）与 ``test_router_branches.py`` 守着。

运行：``uv run pytest tests/test_router_note_contract.py -v``
"""

from __future__ import annotations

import re

import pytest

from src.models.enums import (
    DiseaseCategory,
    EndoleakType,
    HeartFailureNYHA,
    PriorRepair,
    Sex,
    YesNoUnknown,
)
from src.rules.router import _checks, _cmp, _fmt, route, step_p8_prerequisites
from tests.test_preop import make_case

CHECK_SUFFIX = re.compile(r"（(.+?)）")
COMPARATOR = re.compile(r"[≥≤<>]")
DIGIT = re.compile(r"\d")
HALFWIDTH = re.compile(r"[();,]")
# 聚合词：一个检查项里出现它，意味着多个字段被压成了一句结论（判据 ④）
AGGREGATE = re.compile(r"均[无未]|全部[无未]|皆[无未]")


def _violations(note: str, order: str) -> list[str]:
    """返回 ``note`` 违反契约的条目（空列表 = 合规）。"""
    match = CHECK_SUFFIX.search(note)
    if not match or not match.group(1).strip():
        return [f"{order}: 未命中但未附非空检查项 → {note!r}"]
    bad: list[str] = []
    for item in match.group(1).split("；"):
        if not item.strip():
            bad.append(f"{order}: 存在空检查项 → {note!r}")
        elif HALFWIDTH.search(item):
            bad.append(f"{order}: 检查项含半角分隔符（须用全角）→ {item!r}")
        elif AGGREGATE.search(item):
            bad.append(f"{order}: 检查项聚合了多个字段（应逐字段列出取值）→ {item!r}")
        elif "未提及" in item or not COMPARATOR.search(item):
            continue
        elif not DIGIT.search(item):
            bad.append(f"{order}: 数值判据缺实际值 → {item!r}")
    return bad


# 覆盖各类会走到「未命中分支」的真实病例
CASES: dict[str, object] = {
    "基线（P1~P6 全否决 → 指南）": make_case(),
    "非指南病种（P7 亦否决 → 兜底）": make_case(
        disease_category=[DiseaseCategory.SYMPTOMATIC_UNRUPTURED]
    ),
    "缺病种（P1~P5 否决后 P6 命中）": make_case(disease_category=[]),
    "短颈（P1/P2 否决后 P3 命中）": make_case(neck_length_mm=12.0),
    "合并髂动脉瘤（P3 否决至表1 L02）": make_case(
        disease_category=[DiseaseCategory.ASYMPTOMATIC, DiseaseCategory.ILIAC_ANEURYSM]
    ),
    "NYHA III（P1~P3 否决后 P4 命中）": make_case(heart_failure_nyha=HeartFailureNYHA.III),
    "术后内漏未提及（P1~P6 否决后 P7 亦否决 → 兜底）": make_case(
        disease_category=[DiseaseCategory.POSTOPERATIVE],
        prior_repair=PriorRepair.EVAR,
        endoleak_type=None,
    ),
    "术后稳定随访（内漏明确为「无」→ 指南）": make_case(
        disease_category=[DiseaseCategory.POSTOPERATIVE],
        prior_repair=PriorRepair.EVAR,
        endoleak_type=EndoleakType.NONE,
    ),
}


class TestUnhitNoteContract:
    """流水线跑出来的每条未命中 note 都必须自证依据。"""

    @pytest.mark.parametrize("label", list(CASES))
    def test_unhit_notes_carry_checks(self, label: str) -> None:
        result = route(CASES[label])  # type: ignore[arg-type]
        bad: list[str] = []
        for step in result.trace:
            if step.result or not step.note:
                continue
            bad += _violations(step.note, step.order)
        assert not bad, f"[{label}] note 契约违规：\n" + "\n".join(bad)

    def test_p8_unreachable_branch_is_compliant(self) -> None:
        """``355`` 在流水线内不可达（P6 已拦下），直接调用其函数校验 note 合规。"""
        hit, note = step_p8_prerequisites(make_case(), ["sex", "temporal_status"])
        assert hit is False
        assert _violations(note, "P8") == []
        assert "仍缺 2 个关键字段" in note


class TestNoteFormatHelpers:
    """``_fmt`` / ``_cmp`` / ``_checks`` 的渲染边界（契约的唯一定义处）。"""

    def test_fmt_renders_enum_by_chinese_value(self) -> None:
        assert _fmt(Sex.MALE) == "男"

    def test_fmt_renders_none_as_unmentioned(self) -> None:
        assert _fmt(None) == "未提及"
        assert _fmt(None, "mm") == "未提及"  # 缺失时不追加单位

    def test_fmt_joins_list_and_marks_empty(self) -> None:
        assert _fmt([DiseaseCategory.ASYMPTOMATIC]) == "1无症状AAA"
        assert _fmt([]) == "空"

    def test_cmp_keeps_comparator_only_when_value_present(self) -> None:
        assert _cmp(25.0, "mm", "≥", "15.0mm") == "25.0mm ≥ 15.0mm"
        assert _cmp(None, "mm", "≥", "15.0mm") == "未提及"  # 不产生「未提及 ≥ 15mm」

    def test_checks_wraps_with_fullwidth_delimiters(self) -> None:
        assert _checks("甲 1", "乙 2") == "（甲 1；乙 2）"


# ===========================================================================
# P1 未命中 note：逐字段列出急性征象（D-04 回归）
# ===========================================================================
# 这里刻意**重复**字段名与标签，而不复用 router 内部的 acute_signs 元组：
# 本文件断言的是「对外契约」，复用实现内部结构会让测试跟着实现一起漂移。
ACUTE_SIGNS: tuple[tuple[str, str], ...] = (
    ("hemodynamic_instability", "循环不稳"),
    ("active_hemorrhage", "活动性出血"),
    ("acute_limb_ischemia", "急性肢体缺血"),
    ("visceral_malperfusion", "重要器官灌注障碍"),
    ("septic_shock", "脓毒性休克"),
)


def _p1_note(case: object) -> str:
    """取出 P1 步骤的 note（并断言 P1 确为未命中）。"""
    result = route(case)  # type: ignore[arg-type]
    step = next(t for t in result.trace if t.order == "P1")
    assert step.result is False
    return step.note


class TestP1RejectedNoteIsPerField:
    """P1 未命中 note 不许把 5 个急性征象压成一句「均无」。

    改前该句恒为 ``…均无`` —— 即使这 5 个字段全是 ``None``（未采集）。
    把「没查」写成「已排除」，方向恰好错在复核「本例为何不是急诊模式」的关键处。
    """

    def test_uncaptured_signs_are_reported_as_unmentioned(self) -> None:
        """字段未采集 → 逐项写「未提及」，且不得出现聚合句。"""
        note = _p1_note(make_case())  # 5 个三态字段默认均为 None
        for _, label in ACUTE_SIGNS:
            assert f"{label} 未提及" in note
        assert "均无" not in note
        assert _violations(note, "P1") == []

    def test_explicitly_negative_signs_are_reported_as_negative(self) -> None:
        """明确为否 → 逐项写「无」，与「未提及」严格区分。"""
        case = make_case(**{name: YesNoUnknown.NO for name, _ in ACUTE_SIGNS})
        note = _p1_note(case)
        for _, label in ACUTE_SIGNS:
            assert f"{label} 无" in note
        assert "未提及" not in note

    def test_mixed_states_are_not_flattened(self) -> None:
        """混合状态（一项「无」、一项「未提及」）不得被抹平成同一个值。"""
        note = _p1_note(make_case(hemodynamic_instability=YesNoUnknown.NO, septic_shock=None))
        assert "循环不稳 无" in note
        assert "脓毒性休克 未提及" in note
