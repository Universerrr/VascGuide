"""编排层图装配 —— LangGraph ``StateGraph`` + SQLite Checkpoint。

本模块把四个节点串成线性流水线，并接上「可落盘、可回放」的检查点存储：

    START ─▶ input_layer ─▶ router_layer ─▶ execution_layer ─▶ output_layer ─▶ END

「全程可审计」这条红线在这里落地：
    · 每个节点都经 :func:`..state.audited` 包装，自动产出节点级审计记录
      （节点名 / 起止时间 / 输入哈希 / 输出哈希）；
    · 每次执行后，**完整 state**（含 ``route_result.trace`` 与 ``audit_trail``）
      被写入 SQLite；换一个独立连接即可读回同一份 state —— 这正是
      ``tests/test_preop_graph.py`` 的往返测试要验证的能力。

## 一个必须显式处理的坑：类型注册

LangGraph 的 ``JsonPlusSerializer`` 用 msgpack 序列化 state。对于**本项目自定义类型**
（pydantic 模型、dataclass、枚举），它当前会「放行但告警」：

    Deserializing unregistered type src.models.preop.case.VascCase from checkpoint.
    This will be blocked in a future version.

也就是说：**不注册也能跑，但未来某个 LangGraph 版本会直接把反序列化阻断**，
届时历史 checkpoint 全部读不回来，审计链在「升级」这个动作上断掉。
故本模块通过 :func:`build_checkpoint_serde` 显式声明全部允许类型——
这不是可选优化，而是审计红线要求的防御。

治理红线：本模块是确定性基础设施，不得引入任何 LLM 客户端。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, get_args, get_type_hints

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from ..models.preop.case import VascCase
from ..rules.router import RouteResult, StepTrace
from .execution_layer.node import execution_node
from .input_layer.node import input_node
from .output_layer.node import output_node
from .router_layer.node import router_node
from .state import PreopState, audited

__all__ = [
    "DEFAULT_CHECKPOINT_DB",
    "build_checkpoint_serde",
    "build_preop_graph",
    "run_preop",
    "sqlite_checkpointer",
    "thread_config",
]

#: 默认的检查点数据库路径。
#: 放在 ``.workbuddy/`` 下是刻意的 —— 该目录已被 ``.gitignore`` 忽略，
#: 运行期产生的二进制审计库不会被误提交进仓库。
DEFAULT_CHECKPOINT_DB: Path = Path(".workbuddy/state/preop_checkpoints.sqlite")


# ===========================================================================
# 序列化白名单
# ===========================================================================
def _unwrap_annotation(annotation: Any) -> Iterator[Any]:
    """展开一个类型注解，产出它自身及所有类型参数。

    处理 ``X | None``（``get_args`` → ``(X, NoneType)``）、``list[X]``、
    ``dict[str, X]`` 等容器写法，使嵌套引用能被递归发现。
    """
    yield annotation
    for argument in get_args(annotation):
        yield from _unwrap_annotation(argument)


def _declared_types(roots: Iterable[Any]) -> list[type]:
    """把 ``roots`` 及其**嵌套引用**的项目自定义类型全部展开。

    为什么不写死一份清单：白名单最容易漏的从来不是顶层模型，而是
    **嵌在模型内部的类型** —— 例如 ``FinalRecommendation`` 里的
    ``DecisionStep`` / ``EvidenceItem``、``VascCase`` 里的
    ``FieldProvenance`` / ``UrgencyFlagAudit``。写死清单意味着每次新增模型
    都要记得回来补一行，迟早会漏（本轮就实测漏了前两个）。

    递归展开后，「凡是 state 里可达的自定义类型都被登记」成为**构造性事实**，
    而非依赖开发者自觉。
    """
    found: dict[str, type] = {}
    queue: list[Any] = list(roots)

    while queue:
        candidate = queue.pop()
        if not isinstance(candidate, type):
            continue

        key = f"{getattr(candidate, '__module__', '')}.{getattr(candidate, '__qualname__', '')}"
        if key in found:
            continue

        if issubclass(candidate, Enum):
            found[key] = candidate
        elif issubclass(candidate, BaseModel):
            found[key] = candidate
            for field in candidate.model_fields.values():
                queue.extend(_unwrap_annotation(field.annotation))
        elif is_dataclass(candidate):
            found[key] = candidate
            try:
                hints = get_type_hints(candidate)
            except (NameError, TypeError):
                # 注解无法解析时退化为字符串注解，不影响该类型本身已被登记。
                hints = dict(candidate.__annotations__)
            for hint in hints.values():
                queue.extend(_unwrap_annotation(hint))

    return [found[key] for key in sorted(found)]


def allowed_msgpack_types() -> list[type]:
    """列出允许被 checkpoint 反序列化的全部项目自定义类型。

    根集合覆盖三类，再由 :func:`_declared_types` 递归补全其嵌套引用：
        · pydantic 模型（``VascCase`` / 产物模型 / 审计留痕模型）；
        · dataclass（``RouteResult`` / ``StepTrace`` / ``NodeAudit``）；
        · 全部枚举（含 ``FieldWriter``，它嵌在 ``FieldProvenance`` 里）。
    """
    from ..models import enums as enums_module
    from ..models.audit import FieldProvenance, UrgencyFlagAudit
    from ..models.preop.assessment import AnatomyScore, RiskAssessment
    from ..models.preop.measurement import VascMeasurement
    from ..models.preop.recommendation import FinalRecommendation
    from .state import NodeAudit

    roots: list[Any] = [
        VascCase,
        VascMeasurement,
        AnatomyScore,
        RiskAssessment,
        FinalRecommendation,
        FieldProvenance,
        UrgencyFlagAudit,
        RouteResult,
        StepTrace,
        NodeAudit,
    ]
    roots.extend(
        obj
        for obj in vars(enums_module).values()
        if isinstance(obj, type) and getattr(obj, "__module__", "") == enums_module.__name__
    )

    return _declared_types(roots)


def build_checkpoint_serde() -> JsonPlusSerializer:
    """构造显式声明了白名单的序列化器。

    为什么不能省：见模块文档「一个必须显式处理的坑」。
    """
    return JsonPlusSerializer(allowed_msgpack_modules=allowed_msgpack_types())


# ===========================================================================
# 图装配
# ===========================================================================
def build_preop_graph(checkpointer: SqliteSaver | None = None) -> Any:
    """装配并编译术前 Agent 图。

    参数：
        checkpointer: 检查点存储；``None`` 表示不落盘（仅用于轻量测试）。

    返回：
        编译后的 LangGraph 应用（可 ``invoke``）。
    """
    graph: StateGraph = StateGraph(PreopState)

    # 节点名与四层目录名一致，便于把审计记录直接映射回归属层。
    graph.add_node("input_layer", audited("input_layer", input_node))
    graph.add_node("router_layer", audited("router_layer", router_node))
    graph.add_node("execution_layer", audited("execution_layer", execution_node))
    graph.add_node("output_layer", audited("output_layer", output_node))

    graph.add_edge(START, "input_layer")
    graph.add_edge("input_layer", "router_layer")
    graph.add_edge("router_layer", "execution_layer")
    graph.add_edge("execution_layer", "output_layer")
    graph.add_edge("output_layer", END)

    return graph.compile(checkpointer=checkpointer)


def thread_config(thread_id: str) -> dict[str, Any]:
    """构造 LangGraph 调用配置（一次执行 = 一个 thread）。"""
    return {"configurable": {"thread_id": thread_id}}


def run_preop(
    case: VascCase,
    *,
    checkpointer: SqliteSaver | None = None,
    thread_id: str = "preop-default",
) -> PreopState:
    """执行一次完整术前流水线，返回最终 state。

    参数：
        case: 已结构化的术前输入病例。
        checkpointer: 检查点存储；给了就会落盘，可事后读回。
        thread_id: 本次执行的线程标识（同一 thread 可续跑/回放）。

    返回：
        最终状态，含 ``case`` / ``route_result`` / ``tool_outputs`` /
        ``final_recommendation`` / ``audit_trail``。
    """
    app = build_preop_graph(checkpointer=checkpointer)
    return app.invoke({"case": case}, thread_config(thread_id))


# ===========================================================================
# 检查点存储
# ===========================================================================
@contextmanager
def sqlite_checkpointer(db_path: str | Path = DEFAULT_CHECKPOINT_DB) -> Iterator[SqliteSaver]:
    """打开一个 SQLite 检查点存储（上下文管理器，退出时关闭连接）。

    ``check_same_thread=False``：LangGraph 可能在非创建线程上读写连接。
    ``setup()``：建表；重复调用是幂等的，故已存在的库可安全复用。
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path), check_same_thread=False)
    try:
        saver = SqliteSaver(conn, serde=build_checkpoint_serde())
        saver.setup()
        yield saver
    finally:
        conn.close()
