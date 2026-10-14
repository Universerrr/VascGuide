"""输出层节点 —— 把判定结果聚合为 :class:`FinalRecommendation`（决策产物）。

本层做四件事（全部**机械可验证**，无一处自由裁量）：
    ① ``trace → decision_path``：``StepTrace`` 与 ``DecisionStep`` 字段 1:1 对应，
       逐条直转，**含被否决项**（审计要求：不得只留命中项）；
    ② ``ruleset_version``：直接取自 :class:`RouteResult` 的复合版本串；
    ③ ``input_snapshot_hash``：取自输入层算好的输入快照哈希；
    ④ ``evidence_chain``：路由结论的依据 + ``VascCase.field_evidence`` 里每个
       带出处的字段（原告原文），使每条建议可回指到具体规则与原文。

## 明确的两个留白（等外部输入，非本层能自行决定）

**留白一：诊断与治疗方式建议。**
    ``primary_recommendation`` / ``treatment_options`` 目前是显式占位
    （见 :data:`PRIMARY_RECOMMENDATION_PLACEHOLDER`），**不含任何临床主张**。
    原因：设计表只管「路由」，管不到「治疗建议措辞」；三模式各自的标准处置路径
    属临床口径，必须由临床侧确认。**在口径确认前，宁可为空，不可编造。**

**留白二：LLM 输出转译。**
    ``translated_text`` 保持 ``None``（见 :data:`TRANSLATION_BLOCKED_REASON`）。
    该字段属于「LLM 只出现在两处」红线中的第二处（输出转译），但它的价值是
    **措辞润色**，前提是先有确定的结论文本可润色；留白一的文案未定，转译也就无处落脚。

治理红线：
    本层是**聚合与转写**，不是判定。不得在此引入任何新的判定分支或阈值——
    任何「如果 A 则 B」的临床逻辑一旦出现在这里，就等于绕过 ``src/rules`` 另立了一处规则。
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import Enum
from typing import Any

from ...models.preop.case import VascCase
from ...models.preop.recommendation import DecisionStep, EvidenceItem, FinalRecommendation
from ...rules.router import RouteResult, StepTrace
from ..state import PreopState

__all__ = [
    "PRIMARY_RECOMMENDATION_PLACEHOLDER",
    "TRANSLATION_BLOCKED_REASON",
    "TRANSLATION_IMPLEMENTED",
    "output_node",
]

#: 主建议占位（**不含任何临床主张**，等临床口径确认后替换）。
PRIMARY_RECOMMENDATION_PLACEHOLDER: str = (
    "〔待补临床口径〕诊断与治疗方式的主建议尚未定义：需先确认三种路由模式各自的"
    "标准处置路径，确认后替换本占位文本。在此之前本字段不作为临床依据。"
)

#: LLM 输出转译是否已实现（当前为 ``False``）。
TRANSLATION_IMPLEMENTED: bool = False

#: 输出转译未实现的原因。
TRANSLATION_BLOCKED_REASON: str = (
    "LLM 输出转译未实现：转译只做措辞润色、不改结论，其输入应是**已确定的结论文本**。"
    "当前 primary_recommendation / treatment_options 尚未定稿（见留白一），"
    "无内容可转译，贸然接入只会产生无依据的表述。"
)


def _render(value: Any) -> str:
    """把字段值渲染为人类可读字符串（枚举取中文值，列表串接）。"""
    if value is None:
        return "（未提及）"
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, (list, tuple)):
        return "、".join(_render(v) for v in value)
    return str(value)


def _to_decision_steps(trace: Sequence[StepTrace]) -> list[DecisionStep]:
    """``StepTrace`` → ``DecisionStep``：逐条直转，**保留全部被否决步骤**。

    两个字段的对应关系是 1:1（order / condition / result / rule_ref / note），
    无需任何映射表。``note`` 为空串时转 ``None``，避免出现「有 note 字段但内容为空」。
    """
    return [
        DecisionStep(
            order=step.order,
            condition=step.condition,
            result=step.result,
            rule_ref=step.rule_ref,
            note=step.note or None,
        )
        for step in trace
    ]


def _decisive_step(trace: Sequence[StepTrace]) -> StepTrace | None:
    """取**最终命中**的那一步。

    流水线是「自上而下、命中即短路」，故最后一个 ``result=True`` 的步骤就是
    决定最终模式的步骤（P0a/P0b 是预处理登记步，若后续全不命中才会成为末项）。
    """
    for step in reversed(trace):
        if step.result:
            return step
    return None


def _build_evidence(case: VascCase, result: RouteResult) -> list[EvidenceItem]:
    """构造证据链：路由结论的依据 + 各带出处字段的原文。

    证据链的用途是「可追溯」——每条建议都要能回指到规则编号与原文片段。
    """
    items: list[EvidenceItem] = []

    decisive = _decisive_step(result.trace)
    items.append(
        EvidenceItem(
            statement=f"路由结论：{result.route_mode.value}；依据：{result.reason}",
            rule_ref=decisive.rule_ref if decisive else None,
        )
    )

    for field_name in sorted(case.field_evidence):
        provenance = case.field_evidence[field_name]
        items.append(
            EvidenceItem(
                statement=(
                    f"字段 {field_name} = {_render(getattr(case, field_name, None))}"
                    f"（写入者：{provenance.writer.value}）"
                ),
                source=provenance.source_quote,
            )
        )

    return items


def output_node(state: PreopState) -> dict[str, Any]:
    """输出层节点：聚合出 :class:`FinalRecommendation`。

    参数：
        state: 至少含 ``case``（已回填）、``route_result``、``input_snapshot_hash``。

    返回：
        含 ``final_recommendation`` 的状态增量。
    """
    case = state["case"]
    result = state["route_result"]

    recommendation = FinalRecommendation(
        case_id=case.case_id,
        route_mode=result.route_mode,
        # 留白一：等临床口径（见模块文档）。
        primary_recommendation=PRIMARY_RECOMMENDATION_PLACEHOLDER,
        treatment_options=[],
        confidence=result.confidence,
        manual_review_required=result.manual_review_required,
        evidence_chain=_build_evidence(case, result),
        decision_path=_to_decision_steps(result.trace),
        ruleset_version=result.ruleset_version,
        input_snapshot_hash=state.get("input_snapshot_hash"),
        # 留白二：等留白一定稿后再接 LLM 转译。
        translated_text=None,
    )

    return {"final_recommendation": recommendation}
