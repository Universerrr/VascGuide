"""编排层共享状态（``PreopState``）与节点审计轨迹（``NodeAudit`` / ``stable_hash``）。

定位：
    LangGraph 的 ``StateGraph`` 以一份「状态」贯穿全部节点。本模块只做三件事：
      1. 定义这份状态的**字段契约**（:class:`PreopState`）—— 全链路唯一的真相载体；
      2. 定义每个节点的**审计轨迹结构**（:class:`NodeAudit`）；
      3. 提供**稳定哈希**（:func:`stable_hash`）与**节点包装器**（:func:`audited`），
         使「每个节点都自动留痕」成为框架行为而非人工纪律。

契约（交接文档第六节「审计留痕设计」）要求每个节点记录：
    节点名 / 时间戳 / 输入输出哈希。
    → 由 :func:`audited` 统一生成，节点作者只需专注业务逻辑，无从遗漏。

治理红线：
    本模块是**确定性基础设施**，不得引入任何 LLM 客户端。
    哈希必须可复现：**同输入 + 同规则版本 → 同哈希**。
    故 :func:`stable_hash` 刻意**排除**时间戳等非确定性字段（见 :data:`HASHED_KEYS`）。
"""

from __future__ import annotations

import hashlib
import json
import operator
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Annotated, Any, TypedDict

from pydantic import BaseModel

from ..models.preop.case import VascCase
from ..models.preop.recommendation import FinalRecommendation
from ..rules.router import RouteResult

__all__ = [
    "HASHED_KEYS",
    "NodeAudit",
    "PreopState",
    "audited",
    "stable_hash",
    "utc_now_iso",
]


# ===========================================================================
# 状态字段契约
# ===========================================================================
class PreopState(TypedDict, total=False):
    """术前 Agent 全链路共享状态。

    字段推进顺序（与四层节点一一对应）::

        case ──input_layer──▶ case(已归一化) ──router_layer──▶ route_result
             ──execution_layer──▶ tool_outputs ──output_layer──▶ final_recommendation

    设计要点：
        · ``audit_trail`` 使用 ``operator.add`` reducer —— 每个节点**追加**自己的
          审计记录，LangGraph 负责合并；节点无需读取既有轨迹，天然避免读写竞争。
        · ``tool_outputs`` 以工具名为键，缺项即代表该工具未执行（见 execution_layer）。
        · ``input_snapshot_hash`` 由 input_layer 在**路由回填之前**计算 —— 那时
          ``case`` 还是纯粹的输入事实，哈希才有「输入快照」的意义（回填后 case 会被
          写入派生字段，再哈希就不是输入了）。
    """

    case: VascCase
    case_id: str
    input_snapshot_hash: str
    route_result: RouteResult
    tool_outputs: dict[str, Any]
    final_recommendation: FinalRecommendation
    audit_trail: Annotated[list[NodeAudit], operator.add]


# 参与哈希的字段：**排除 audit_trail**。
# 原因：audit_trail 内含时间戳，属非确定性内容；若纳入哈希，则「同输入同规则」
# 也会得到不同哈希，直接违反「可复现」红线。
HASHED_KEYS: tuple[str, ...] = (
    "case",
    "case_id",
    "route_result",
    "tool_outputs",
    "final_recommendation",
)


# ===========================================================================
# 审计轨迹
# ===========================================================================
@dataclass(frozen=True)
class NodeAudit:
    """单个节点的执行审计记录。

    字段与交接文档第六节逐条对应：节点名 / 开始时间 / 结束时间 / 输入哈希 / 输出哈希。
    ``frozen=True`` 保证已落盘的审计记录不可被后续节点篡改。
    """

    node: str
    started_at: str
    finished_at: str
    input_hash: str
    output_hash: str

    def to_dict(self) -> dict[str, str]:
        """转为纯字典（便于落库 / 断言 / 展示）。"""
        return {
            "node": self.node,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "input_hash": self.input_hash,
            "output_hash": self.output_hash,
        }


def utc_now_iso() -> str:
    """当前 UTC 时间的 ISO 8601 字符串（审计时间戳统一口径）。"""
    return datetime.now(UTC).isoformat()


# ===========================================================================
# 稳定哈希
# ===========================================================================
def _normalize(value: Any) -> Any:
    """把任意对象递归归一化为「JSON 可序列化且结构确定」的形式。

    处理顺序即优先级：pydantic 模型 → dataclass → 枚举 → 映射 → 序列 → 标量。
    键一律转字符串并排序，集合类先排序，确保**同内容必得同字符串**。
    """
    if isinstance(value, BaseModel):
        return _normalize(value.model_dump(mode="python"))
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _normalize(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Enum):
        return _normalize(value.value)
    if isinstance(value, Mapping):
        return {str(k): _normalize(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (set, frozenset)):
        items = [_normalize(v) for v in value]
        return sorted(items, key=lambda x: json.dumps(x, sort_keys=True, ensure_ascii=False))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_normalize(v) for v in value]
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    # 兜底：不可识别类型退化为 repr，保证哈希始终可计算且对同一对象稳定。
    return repr(value)


def _project(state: Mapping[str, Any]) -> dict[str, Any]:
    """从状态中挑出参与哈希的字段（丢弃 audit_trail 等非确定性内容）。"""
    return {k: state[k] for k in HASHED_KEYS if k in state}


def stable_hash(value: Any) -> str:
    """计算稳定哈希（SHA-256 十六进制）。

    **同内容 → 同哈希**，与字典插入顺序、集合迭代顺序无关，与时间戳无关。
    用于输入快照哈希（``FinalRecommendation.input_snapshot_hash``）与节点级留痕。
    """
    payload = json.dumps(
        _normalize(value), sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ===========================================================================
# 节点包装器
# ===========================================================================
def audited(
    node_name: str,
    fn: Callable[[PreopState], dict[str, Any]],
) -> Callable[[PreopState], dict[str, Any]]:
    """把一个节点函数包装成「自带审计留痕」的节点。

    包装后行为：
        1. 记录开始时间与**输入哈希**（对状态投影取哈希，排除时间戳）；
        2. 执行原节点函数，拿到状态增量；
        3. 按 LangGraph 的合并语义合成「本节点执行后的状态」，对其投影取
           **输出哈希**；
        4. 返回值 = 原增量 + ``{"audit_trail": [新纪录]}``（由 reducer 追加合并）。

    ⚠️ 关键设计：输入哈希与输出哈希**必须取同一口径**（都是「状态投影」的哈希），
    否则两个哈希不可对账。统一口径后可验证如下不变量：

        ``audit_trail[i].output_hash == audit_trail[i+1].input_hash``

    也就是「上一节点的输出状态」就是「下一节点的输入状态」——审计链因此可以
    **逐环校验**，任何一环被篡改都会立刻暴露。

    这样「每个节点都留痕」不再依赖开发者自觉，而是框架强制。
    """

    def wrapper(state: PreopState) -> dict[str, Any]:
        started_at = utc_now_iso()
        input_hash = stable_hash(_project(state))

        update = fn(state)

        # 按合并语义还原「本节点执行后的状态」——与下一节点即将看到的输入一致。
        # （本图唯一带 reducer 的通道是 audit_trail，而它已被 _project 排除。）
        resulting = {**state, **update}
        output_hash = stable_hash(_project(resulting))
        finished_at = utc_now_iso()

        record = NodeAudit(
            node=node_name,
            started_at=started_at,
            finished_at=finished_at,
            input_hash=input_hash,
            output_hash=output_hash,
        )
        return {**update, "audit_trail": [record]}

    wrapper.__name__ = f"audited__{node_name}"
    wrapper.__doc__ = fn.__doc__
    return wrapper
