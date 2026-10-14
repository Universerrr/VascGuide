"""输入层节点 —— 把「术前输入」变成结构化的 :class:`VascCase`。

本层是**整个术前 Agent 唯一的 LLM 入口**（治理红线）：
    自由文本病历 / CTA 报告 ──LLM 抽取──▶ ``VascCase``（事实层）
    除此之外的任何一层都**不得**接触 LLM。

当前状态（务必如实告知使用者）：
    · **确定性部分已实现**：接受已结构化的 ``VascCase``，重新过一遍全部校验器
      （枚举归一化 / 精度量化 / 证据链挂载检查），并计算**输入快照哈希**。
      重新构造还顺带保证了「输入层不会污染调用方的原件」（新对象而非就地改）。
    · **LLM 抽取器未实现**：见 :data:`EXTRACTOR_IMPLEMENTED` 与
      :func:`extract_case_from_text`。原因不是难度，而是**无法验收** ——
      没有标注病例评估集，抽取准确率（精确率 / 召回率 / 字段级 F1）无从度量，
      贸然接入 LLM 只会让「LLM 只出现在两处」这条红线失去可验证性。
"""

from __future__ import annotations

from typing import Any

from ...models.preop.case import VascCase
from ..state import PreopState, stable_hash

__all__ = [
    "EXTRACTOR_BLOCKED_REASON",
    "EXTRACTOR_IMPLEMENTED",
    "extract_case_from_text",
    "input_node",
]

#: LLM 抽取器是否已实现（当前为 ``False``）。
EXTRACTOR_IMPLEMENTED: bool = False

#: 未实现的原因（同时作为 :class:`NotImplementedError` 的说明文字）。
EXTRACTOR_BLOCKED_REASON: str = (
    "LLM 抽取器未实现：接入 LLM 前必须先有【标注病例评估集】来度量抽取准确率"
    "（字段级精确率/召回率/F1），否则「LLM 只用于输入抽取」这条治理红线"
    "无法被验证。当前尚无评估集，故本层只接受已结构化的 VascCase。"
)


def extract_case_from_text(raw_text: str) -> VascCase:
    """【未实现 · 本 Agent 唯一的 LLM 入口】把自由文本抽取为结构化 ``VascCase``。

    实现时必须遵守：
        · 抽取结果只落**事实层**字段，不得做任何推理（如「颈长偏短」不算数据）；
        · 每个写入字段都要在 ``field_evidence`` 里留下原文出处与写入者（=LLM）；
        · 不得读取判定层 / 输出层字段。

    参数：
        raw_text: 病历与 CTA 报告原文。

    抛出：
        NotImplementedError: 恒抛出，说明见 :data:`EXTRACTOR_BLOCKED_REASON`。
    """
    raise NotImplementedError(EXTRACTOR_BLOCKED_REASON)


def input_node(state: PreopState) -> dict[str, Any]:
    """输入层节点：确定性归一化 + 计算输入快照哈希。

    为什么要在这一层重算一次 ``VascCase``：
        ① **归一化**——把照抄设计表的写法（如 ``'有（活动性）'``）统一成规范取值，
           把所有精度口径（1 位 / 2 位小数）落地，保证下游读到的是同一套口径；
        ② **隔离**——``model_validate`` 产出**新对象**，``router_layer`` 后续对 case
           的就地回填不会改到调用方手里那个原始病例，同一次输入重复跑结果可复现；
        ③ **快照哈希**——此时 case 仍是「纯输入事实」（尚未写入任何派生字段），
           在这里取哈希才配叫「输入快照」。

    参数：
        state: 至少含 ``case`` 字段（``VascCase``）。

    返回：
        含 ``case`` / ``case_id`` / ``input_snapshot_hash`` 的状态增量。

    抛出：
        ValueError: 缺少 ``case``，或该层尚未实现的「原始文本输入」形态被传进来。
    """
    case = state.get("case")
    if case is None:
        raise ValueError(
            "输入层缺少 case：本层当前只接受**已结构化**的 VascCase。"
            f"若你手上是病历原文，需要 LLM 抽取器——{EXTRACTOR_BLOCKED_REASON}"
        )

    normalized = VascCase.model_validate(case.model_dump(mode="python"))

    return {
        "case": normalized,
        "case_id": normalized.case_id,
        "input_snapshot_hash": stable_hash(normalized),
    }
