"""执行层节点 —— 5 个**确定性**工具的统一挂载点（当前全部为桩）。

定位（交接文档第二节「数据流」）：
    本层是「决策产物」的唯一产地。VascCase 是**输入**，本层产物**不回写** VascCase：

    ==========  ==================  ==========================
    工具        产物                承载模型
    ==========  ==================  ==========================
    A 指南引擎   指南推荐条目          （并入 FinalRecommendation）
    B 影像量化器 容积 / 各段直径 / 钙化  VascMeasurement
    C 解剖评分器 解剖评分分值          AnatomyScore
    D 记忆检索器 历史病例 / 既往证据     （并入 FinalRecommendation）
    E 风险计算器 风险分值              RiskAssessment
    ==========  ==================  ==========================

治理红线：
    5 个工具**全部是确定性算子**，不是「交给 LLM 自行决定是否调用的 tool」。
    它们由代码写死调用，性质等同于 ``import math``；本层不得引入任何 LLM 客户端。

当前状态：**5 个工具全部未实现**（:data:`IMPLEMENTED_TOOLS` 为空）。
    每个工具都在 :data:`TOOL_REGISTRY` 里写明了**阻塞原因**——不是「待办」，
    而是缺什么具体资源。缺少资源的工具不应仓促实现，否则产生无法验证的产物。
    因此本节点当前返回空的 ``tool_outputs``；下游据此保持谨慎（人工复核）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..state import PreopState

__all__ = [
    "IMPLEMENTED_TOOLS",
    "TOOL_REGISTRY",
    "ToolSpec",
    "execution_node",
    "run_tool",
    "unimplemented_tools",
]


# ===========================================================================
# 工具登记表
# ===========================================================================
@dataclass(frozen=True)
class ToolSpec:
    """一个确定性工具的元信息。

    ``blocked_reason`` 为 ``None`` 表示已实现；否则表示**缺什么**才能实现。
    """

    key: str
    label: str
    consumes: tuple[str, ...]
    produces: str
    blocked_reason: str | None = None

    @property
    def implemented(self) -> bool:
        """该工具是否已实现。"""
        return self.blocked_reason is None


TOOL_REGISTRY: tuple[ToolSpec, ...] = (
    ToolSpec(
        key="guideline_engine",
        label="工具A · 指南引擎",
        consumes=("case.disease_category", "case.anatomy_level", "case.max_diameter_mm"),
        produces="指南推荐条目（并入 FinalRecommendation）",
        blocked_reason=(
            "需先确定接入哪一部/哪几部指南及其版本（SVS / ESVS / NICE …），"
            "并把指南条目结构化为可检索的条目库；口径未定。"
        ),
    ),
    ToolSpec(
        key="imaging_quantifier",
        label="工具B · 影像量化器",
        consumes=("CTA 影像",),
        produces="VascMeasurement（容积 / 各节段直径 / 钙化量化）",
        blocked_reason=(
            "需 CTA 影像数据 + 血管分割与中心线提取算法；当前既无影像数据，"
            "也无算法实现，故无法产出可验证的量化结果。"
        ),
    ),
    ToolSpec(
        key="anatomy_scorer",
        label="工具C · 解剖评分器",
        consumes=("case 解剖字段", "VascMeasurement"),
        produces="AnatomyScore",
        blocked_reason=(
            "需临床评分量表（各项分值口径与权重）。设计表 6 个 Sheet 中**没有**"
            "评分量表这张表，且 Sheet「05_说明与待确认」已明确：解剖评分的完整参数"
            "不由 VascCase 承载。故量表是外部输入，当前缺失。"
        ),
    ),
    ToolSpec(
        key="memory_retriever",
        label="工具D · 记忆检索器",
        consumes=("case 摘要",),
        produces="历史相似病例 / 既往证据（并入 FinalRecommendation）",
        blocked_reason=(
            "需已脱敏的历史病例库与向量检索索引；当前无该数据集，"
            "检索质量（相似度阈值、召回率）无从评估。"
        ),
    ),
    ToolSpec(
        key="risk_calculator",
        label="工具E · 风险计算器",
        consumes=("case 合并症字段", "AnatomyScore"),
        produces="RiskAssessment",
        blocked_reason=(
            "需具体风险模型及其系数（围术期死亡率的计算口径、模型版本）。"
            "该口径同样不在设计表内，属外部临床输入，当前缺失。"
        ),
    ),
)

#: 已实现的工具键集合（当前为空——5 个工具全部未实现）。
IMPLEMENTED_TOOLS: frozenset[str] = frozenset(s.key for s in TOOL_REGISTRY if s.implemented)

_SPEC_BY_KEY: dict[str, ToolSpec] = {s.key: s for s in TOOL_REGISTRY}


def unimplemented_tools() -> tuple[ToolSpec, ...]:
    """返回尚未实现的工具（含各自阻塞原因），供测试与报告展示。"""
    return tuple(s for s in TOOL_REGISTRY if not s.implemented)


# ===========================================================================
# 节点
# ===========================================================================
def run_tool(key: str, state: PreopState) -> Any:
    """按工具键执行单个工具。

    抛出：
        KeyError: ``key`` 不在 :data:`TOOL_REGISTRY` 中。
        NotImplementedError: 该工具尚未实现（说明文字即其阻塞原因）。
    """
    spec = _SPEC_BY_KEY[key]
    if spec.blocked_reason is not None:
        raise NotImplementedError(f"{spec.label} 未实现：{spec.blocked_reason}")
    raise NotImplementedError(f"{spec.label} 标记为已实现但缺少执行分支——实现工具时请在此处分派。")


def execution_node(state: PreopState) -> dict[str, Any]:
    """执行层节点：调用全部**已实现**的确定性工具。

    当前 :data:`IMPLEMENTED_TOOLS` 为空，故返回 ``{"tool_outputs": {}}``。
    这不是占位敷衍，而是如实反映「工具产物尚不存在」——下游输出层会据此
    保留人工复核标记，绝不凭空编造评分或指南推荐。

    ``tool_outputs`` 以**工具键**为键，缺项即代表该工具未执行（与 :mod:`..state` 约定一致）。

    参数：
        state: 至少含 ``case``（已由路由层回填）。

    返回：
        含 ``tool_outputs`` 的状态增量。
    """
    outputs: dict[str, Any] = {key: run_tool(key, state) for key in sorted(IMPLEMENTED_TOOLS)}
    return {"tool_outputs": outputs}
