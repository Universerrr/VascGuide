"""路由层节点 —— ``src/rules/router.py`` 的**薄封装**（零临床规则行）。

架构铁律（违反即破坏审计可追溯性）：
    路由规则**只存在于** ``src/rules/router.py`` 这一处。本层不得复制任何阈值常量、
    病种关键词、覆盖规则编号或判定分支——它只做三件事：**取值、调用、回填**。

为什么规则不写在这里：
    · 三个 Agent（术前 / 术中 / 术后）共享同一套路由规则。一旦在本层复制，
      就会出现「同一个规则两份实现」，版本漂移后审计链断裂，且无法机器检查；
    · 规则层必须能被**独立测试**——现有路由测试不需要 LangGraph、不需要数据库、
      不需要任何 API Key，秒级跑完。把规则搬进本层会把这份能力毁掉；
    · 保持本层足够薄，才能用一条 AST 守卫测试（见 ``tests/test_preop_graph.py``）
      机械地证明「本层没有偷藏规则」。

治理红线：本模块调用的是**确定性判定函数**，不得引入任何 LLM 客户端。
"""

from __future__ import annotations

from typing import Any

from ...models.preop.case import apply_route_result
from ...rules.router import route
from ..state import PreopState

__all__ = ["router_node"]


def router_node(state: PreopState) -> dict[str, Any]:
    """读取 case → 调用规则层 → 回填判定层与输出层字段。

    注意：``route()`` 只被调用**一次**，其返回值 ``RouteResult`` 同时供
    ① 回填 ``case``、② 供输出层生成完整决策路径使用。这保证了「判定只发生一处」。

    参数：
        state: 至少含 ``case`` 字段。

    返回：
        含 ``case``（已回填）/ ``case_id`` / ``route_result`` 的状态增量。
    """
    case = state["case"]

    result = route(case)
    apply_route_result(case, result)

    return {"case": case, "case_id": case.case_id, "route_result": result}
