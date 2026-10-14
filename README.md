# VascGuide AI Agent

> 面向 **主动脉瘤（Aortic Aneurysm）** 的临床决策支持智能体 —— **术前—术中—术后三 Agent 闭环架构**。
> 设计原则：**「规则主导，LLM 为辅」** —— 决策树是司令员，LLM 是发言人。

---

## 一、项目背景

VascGuide 面向主动脉瘤（AAA / TAA）全周期管理，覆盖 **术前决策 → 术中导航 → 术后随访** 三个环节，
形成可追踪、可审计的闭环：

- **术前决策 Agent**：输入术前病例文本 + 影像，输出 **个体化循证诊疗方案 + 证据链**。
  采用四层流水线：`Input → Router → Execution → Aggregator & Output`。
- **术中导航 Agent**：输入 DSA 影像 + 生命体征 + 手术阶段信号，实时输出 **确定性指令 + 证据链**。
- **术后随访 Agent**：输入术后病例文本 + 影像，输出 **随访规划 + 异常预警**，纵向追踪全周期结局。

三个 Agent 共享一条完整数据链（术前 → 术中 → 术后全程可追踪），随访结果写回记忆库，
成为术前 / 术后相似病例检索的决策参考基准；术后检出异常时触发 **二次干预评估**，
复用术前决策树重算治疗方案，形成闭环。

### 核心治理红线

> **LLM 仅出现于「输入抽取」与「输出转译」两处。**
> 路由、解剖评分、风险分层、随访规划、异常检测、决策树仲裁 **全部为确定性代码**（无 LLM 参与），
> 且全程由 LangGraph Checkpoint 保证可审计、所有建议均附证据链。

---

## 二、当前阶段

> **确定性内核（数据模型 + 规则层 + 编排层）已落地并通过验证；LLM 接入与确定性工具均未开始。**

### ✅ 已完成

| 模块 | 内容 |
|---|---|
| **术前数据模型（5 个）** | `VascCase`（51 字段）、`VascMeasurement`、`AnatomyScore`、`RiskAssessment`、`FinalRecommendation` |
| **共享枚举（19 个）** | `StrEnum` + 中文值，覆盖性别、病种、破裂状态、解剖分型、恶性肿瘤等 |
| **审计留痕结构** | `FieldProvenance`（字段原文出处 / 写入者 / 置信度）、`UrgencyFlagAudit` |
| **确定性规则层** | `router.py`（P0a~P8 路由流水线）+ `version.py`（规则版本注册表），详见「四」 |
| **编排层（LangGraph）** | 四层节点 `input → router → execution → output` 串成 `StateGraph` 并接 SQLite Checkpoint；每节点自动留痕（节点名 / 起止时间 / 输入输出哈希），审计链可**逐环校验**，详见「五」 |
| **测试与工具链** | 158 项测试全绿（41 路由基线 + 67 数据契约 + 50 编排层）、`ruff` 无告警、覆盖率 97% |

### ⏳ 尚未开始

缺口分四类，**性质不同，都不应仓促补齐**——每一类都已在代码里写成显式的「不可用 + 原因」，
而不是留一个看起来能跑的空壳。

**① 等外部资源（技术缺口）**

- **5 个确定性工具全部未实现**（`execution_layer/`）。每个工具都在
  `TOOL_REGISTRY` 里写明了**具体缺什么**：指南引擎缺「接入哪部指南 + 条目结构化方式」、
  影像量化器缺「CTA 数据 + 分割与中心线算法」、解剖评分器与风险计算器缺「临床量表与模型系数」、
  记忆检索器缺「历史病例库与检索索引」。
  因此 `tool_outputs` 当前恒为空 —— **宁可空着，也不凭空造评分**。

**② 等临床口径（内容缺口）**

- **诊断与治疗方式建议**：`FinalRecommendation.primary_recommendation` 当前是**显式占位文本**，
  `treatment_options` 为空列表。设计表只定义「路由」，不定义「治疗建议措辞」；
  三种路由模式各自的标准处置路径属临床口径，须由临床侧确认后填入。

**③ 等评估集（能力缺口）**

- **输入层 LLM 抽取器**与**输出层 LLM 转译** —— 全项目**仅有的两个**允许出现 LLM 的节点。
  二者均已留出接口并主动抛出 `NotImplementedError`，异常信息里写明「为什么现在不能做」：
  抽取器必须先有**标注病例评估集**才能度量字段级准确率，否则「LLM 只用于两处」这条红线
  虽在形式上成立、却无法被验证；转译只做措辞润色，得先有 ② 定稿的结论文本才有内容可转译。

**④ 其他**

- **术中 / 术后 Agent** —— `intraop_agent/`、`postop_agent/` 目前仅为目录骨架，无实现。
- **`main.py`** —— 仍为占位入口。

推进顺序遵循「**确定性内核优先**」：先落地数据模型、规则层与编排骨架，
**LLM 只在最后接入两端的抽取与转译节点**，中间管道保持零 LLM 参与。

---

## 三、目录结构

```
zs-Midea VascGuide/
├── docs/                        # 架构文档、临床指南（如 ESVS 2024）
├── src/
│   ├── core/                    # 核心引擎预留位〔骨架，当前未使用；见下方「说明」第 4 条〕
│   ├── models/                  # Pydantic 数据模型
│   │   ├── __init__.py          # ✅ 统一导出（模型 + 枚举 + 审计结构）
│   │   ├── enums.py             # ✅ 19 个共享枚举（StrEnum，中文值）
│   │   ├── audit.py             # ✅ 审计留痕结构（FieldProvenance / UrgencyFlagAudit）
│   │   ├── preop/               # ✅ 术前模型包（含 __init__.py 聚合导出）
│   │   │   ├── case.py          # ✅ VascCase（51 字段）+ derive() + apply_route_result()
│   │   │   ├── measurement.py   # ✅ VascMeasurement + CenterlinePoint（仅模型，无计算）
│   │   │   ├── assessment.py    # ✅ AnatomyScore + RiskAssessment（仅模型，无计算）
│   │   │   └── recommendation.py# ✅ FinalRecommendation + EvidenceItem + DecisionStep
│   │   ├── intraop.py           # IntraOpIntent（预留，空占位）
│   │   └── postop.py            # PostOpCase / FollowUpPlan / FollowUpStatus（预留，空占位）
│   ├── rules/                   # ✅ 确定性规则层（详见「四」；无 __init__.py）
│   │   ├── router.py            # ✅ P0a~P8 路由判定流水线（纯函数）
│   │   └── version.py           # ✅ 规则版本号注册表（审计必需）
│   ├── tools/                   # 确定性工具集〔骨架〕—— 挂载点实际在 preop_agent/execution_layer/
│   ├── utils/                   # 工具函数（LLM 调用封装、Checkpoint 管理）〔骨架〕
│   ├── preop_agent/             # ✅ 术前决策 Agent（四层 + 编排，详见「五」）
│   │   ├── state.py             # ✅ PreopState + NodeAudit + stable_hash() + audited()
│   │   ├── graph.py             # ✅ StateGraph 装配 + SQLite Checkpoint + 序列化白名单
│   │   ├── input_layer/node.py  # ✅ 归一化 + 输入快照哈希（LLM 抽取器留空并显式抛错）
│   │   ├── router_layer/node.py # ✅ 对 src/rules/router.py 的薄封装（临床规则 0 行）
│   │   ├── execution_layer/node.py # ✅ 5 个工具挂载点（全部未实现，各自写明阻塞原因）
│   │   └── output_layer/node.py # ✅ 聚合为 FinalRecommendation（诊疗建议为显式占位）
│   ├── intraop_agent/           # 术中导航 Agent〔骨架〕
│   │   ├── localization/        # 术中定位
│   │   ├── assessment/          # 术中评估
│   │   ├── monitoring/          # 生命体征监测
│   │   └── decision_tree/       # 确定性决策树
│   └── postop_agent/            # 术后随访 Agent〔骨架〕
│       ├── case_update/         # ① 病例更新
│       ├── risk_stratify/       # ② 风险分层
│       ├── followup_plan/       # ③ 随访规划
│       ├── anomaly_monitor/     # ④ 异常监控
│       ├── status_manager/      # ⑤ 状态管理
│       └── output_translate/    # ⑥ 输出转译
├── tests/                       # 测试（无 __init__.py，见「八、开发约定」）
│   ├── test_preop.py            # ✅ 41 项路由行为基线（本轮断言零改动）
│   ├── test_model_contract.py   # ✅ 67 项数据契约
│   └── test_preop_graph.py      # ✅ 50 项编排层 + Checkpoint 往返 + 白名单守卫 + 两条架构守卫
├── pyproject.toml               # 依赖与项目元数据（唯一"真源"）
├── uv.lock                      # 全量精确锁定（含传递依赖，由 uv 生成）
├── main.py                      # 系统入口（占位）
├── LICENSE                      # MIT
├── .gitignore                   # Python 模板
├── .python-version              # 解释器版本锁定（3.13.14）
└── README.md                    # 本文档 —— 全项目唯一说明入口
```

**图例**：✅ = 已实现并通过测试；〔骨架〕= 只有目录结构，无业务逻辑；其余为预留文件。

> **说明**
> 1. 本仓库根目录即为项目根目录，**必须从仓库根运行**（`pyproject.toml` 中 `[tool.uv] package = false`，不是可安装包）。
> 2. **目录职责说明统一由本文档承载**，不再在子目录下另建 `README.md`（单一真源，避免多处维护漂移）。
> 3. **`__init__.py` 不是必需品**（PEP 420 命名空间包无它也能导入）。当前实际分布：
>    `src/models/` 与 `src/models/preop/` 保留（承载聚合 re-export）；
>    `src/rules/` 已移除（无 re-export 消费者）；`tests/` 已移除（非运行时包）。
>    是否省略的判据见「八、开发约定」。
> 4. **`src/core/` 目前是空预留位**。编排层（`state.py` / `graph.py`）落在了
>    `src/preop_agent/` 内，理由是现阶段只有术前 Agent 有编排需求，`PreopState` 也是
>    术前专属；放到 `src/core/` 反而会把「谁是术前专属、谁是三 Agent 共用」搅混。
>    若将来术中 / 术后也需要编排（届时 `NodeAudit` / `stable_hash` / `audited` 确实是
>    三 Agent 共用的），再把这三样上移到 `src/core/`，`PreopState` 留在原处。

---

## 四、核心模块：规则层（`src/rules/`）

> **治理红线：本层是判定层，禁止 `import` 任何 LLM 客户端。**
> LLM 仅允许出现在 `preop_agent/input_layer/`（输入抽取）与 `preop_agent/output_layer/`（输出转译）两处。
> 路由、解剖评分、风险分层、随访规划、异常检测、决策树仲裁 **全部为确定性代码**。

本目录承载 VascGuide 的**全部确定性规则**，是「规则主导，LLM 为辅」这条红线的物理落点。
它是一段**纯粹的确定性函数库**（性质等同 `import math`），**不是**交给 LLM 自主选择调用的工具（tool）。

### 1. 文件

| 文件 | 职责 |
|---|---|
| `router.py` | P0a~P8 路由判定流水线（纯函数，无副作用、无 IO、无全局状态） |
| `version.py` | 规则版本号注册表（复合版本串，审计必需） |

### 2. 路由做什么（以及不做什么）

`route(VascCase) → RouteResult`。它只回答**一个问题**：「这个病例该走哪条路？」

```
事实层输入  ──▶  P0a~P8 判定链（命中即短路）  ──▶  三选一结论 + 判定轨迹 + 规则版本
                 急诊 > 复杂 > 指南
```

- **短路即优先级**：判定链自上而下，一旦命中立即返回，后续步骤不再求值。
  「急诊 > 复杂 > 指南」不是配置项，而是**代码的物理结构**。
- **两个兜底方向都是保守的**：全部不命中 → 回落为**复杂模式 + 需人工复核**（不默认「稳定」）；
  指南模式下若仍有字段缺失 → 同样降级。关键字段缺失时置信度 `0.90 → 0.45`（×0.5）。
- **每一步都留痕**：逐条写入 `StepTrace`（步骤号 / 判定条件 / 结果 / 规则编号 / 说明），
  **含被否决的步骤**，最终结论附带 `RULESET_VERSION`。这是「历史结论可追溯复现」的落地方式。

### 3. 设计原则

1. **纯函数、无全局状态、无 IO** —— 相同输入必然得到相同输出（可复现）。
2. **输出结构化中间结果**（含逐条判定轨迹），供审计落盘。
3. **阈值 / 编号一律与 `.workbuddy/spec/VascCase字段设计表.xlsx` 对齐。**

### 4. 变更纪律（审计红线）

> 改动任何**阈值 / 病种归属 / 覆盖规则**后，**必须**在 `src/rules/version.py` 手动 bump 对应版本号，
> 并在 `RULESET_CHANGELOG` 记录原因。否则历史结论无法追溯复现。

当前版本串：**`table1@v1.0+table2@v1.4`**。

由于本层是一个**独立、可被工具扫描的目录**，这条纪律可以自动化检查，例如：

```
改动了 src/rules/** 但未改动 src/rules/version.py  →  构建失败
```

### 5. 与 `preop_agent/router_layer/` 的关系

`preop_agent/router_layer/` 必须是本目录的**薄封装** —— 只负责「图编排的胶水」
（State ↔ `VascCase` 翻译、调用 `route()`、写 Checkpoint），**严禁重复实现任何规则逻辑**。

| | `src/rules/`（本目录） | `preop_agent/router_layer/` |
|---|---|---|
| 关注 | 临床判定逻辑 | 图编排的胶水 |
| 输入 / 输出 | `VascCase` → `RouteResult` | LangGraph `State` → State + Checkpoint |
| 依赖 | 仅 `models`（零 IO / 零 LLM） | LangGraph、Checkpoint、日志 |
| 临床规则行数 | 本目录 | **0 行** |

`route()` 存在**两个调用者**：`VascCase.derive()`（服务无编排场景，如 CLI / 单测）与
`router_layer` 节点（服务 LangGraph 编排）。**两处都必须是薄封装。**

> **为什么规则不直接写在 `router_layer/` 里？** 因为三期 Agent 共享同一套临床口径，
> 且规则必须能独立测试 —— 41 项路由测试 0.2 秒跑完，不需要 LangGraph、不需要数据库、
> 不需要任何 API Key（相比之下编排层测试要 7 秒）。
> 绑定到 `preop_agent/` 下会导致跨层循环依赖、版本号漂移，并使「规则变更纪律」无法被机器检查。

---

## 五、核心模块：编排层（`src/preop_agent/`）

编排层做三件事：**把四层节点串成图**、**为每一步留痕**、**把整份状态落盘到 SQLite**。

### 1. 文件

| 文件 | 职责 |
|---|---|
| `state.py` | `PreopState`（状态契约）、`NodeAudit`（节点留痕）、`stable_hash()`、`audited()` 包装器 |
| `graph.py` | `build_preop_graph()` 装配、`sqlite_checkpointer()` 落盘、`run_preop()` 入口、序列化白名单 |
| `input_layer/node.py` | 确定性归一化 + 输入快照哈希；LLM 抽取器留空 |
| `router_layer/node.py` | 对 `src/rules/router.py` 的薄封装（**临床规则 0 行**） |
| `execution_layer/node.py` | 5 个确定性工具的挂载点（当前全部未实现） |
| `output_layer/node.py` | 聚合 `FinalRecommendation` |

### 2. 图与状态

```
START ─▶ input_layer ─▶ router_layer ─▶ execution_layer ─▶ output_layer ─▶ END
```

状态字段按推进顺序增长：`case` →（归一化）→ `case_id` / `input_snapshot_hash`
→ `route_result` → `tool_outputs` → `final_recommendation`，而 `audit_trail` 全程追加。

两个刻意的设计：

- **`audit_trail` 用 `operator.add` reducer** —— 每个节点只负责「追加自己那一条」，
  合并交给框架，节点之间不必读彼此的轨迹，天然无读写竞争。
- **`input_snapshot_hash` 在输入层计算** —— 那时 `case` 还是纯输入事实；
  路由回填之后 `case` 已被写入派生字段，再取哈希就不叫「输入快照」了。

### 3. 审计链：可逐环校验

`audited()` 包装器让**每个节点自动生成**一条记录（节点名 / 起止时间 / 输入哈希 / 输出哈希），
节点作者**无从遗漏** —— 留痕是框架行为，不是人工纪律。

输入哈希与输出哈希取**同一口径**（都是「状态投影」的哈希，且剔除时间戳），
因此成立一条可验证的不变量：

```
audit_trail[i].output_hash == audit_trail[i+1].input_hash
```

即「上一节点的输出状态」就是「下一节点的输入状态」。测试逐环断言这条等式
（`test_audit_chain_closes_ring_by_ring`），任何一环被篡改都会立刻暴露。

哈希**排除** `audit_trail` 本身（它含时间戳），因此「同输入 + 同规则版本 → 同哈希」，
重复执行结果可复现（`test_hashes_are_reproducible_across_runs`）。

### 4. 三条被机器守住的架构红线

规则不靠自觉，靠测试。以下三条由 `tests/test_preop_graph.py` 机械执行：

| 守卫 | 做法 |
|---|---|
| **薄封装不藏规则** | AST 扫描 `router_layer/node.py`：代码里不得出现任何**数值常量**（阈值）、病种 / 解剖 / 处置**关键词**、以及**规则编号** |
| **判定层零 LLM** | AST 扫描 `src/rules/` 与 `router_layer/` `execution_layer/` `output_layer/` 的全部 `import`，出现任何 LLM 客户端 SDK 即失败 |
| **序列化白名单完整** | 从真实 state 反推全部自定义类型，与 `build_checkpoint_serde()` 的白名单比对；漏注册即失败（详见本节目第 5 小节） |

`input_layer/` 是唯一豁免的层（它是被允许的 LLM 入口），且其抽取函数当前主动抛错。

### 5. 一个必须显式处理的序列化坑

LangGraph 用 msgpack 序列化状态。对本项目自定义类型（pydantic 模型、dataclass、枚举），
它当前的行为是「**放行但告警**」，并提示：

> Deserializing unregistered type … This will be blocked in a future version.

也就是说：**不注册也能跑，但未来某个版本会直接阻断反序列化**，届时历史 Checkpoint
全部读不回来 —— 审计链会在「升级」这个动作上悄悄断掉。故 `graph.py` 通过
`build_checkpoint_serde()` 显式声明全部允许类型（`allowed_msgpack_modules`）。
这不是可选优化，而是审计红线要求的防御。

**白名单是递归展开的，不是手写清单。** `allowed_msgpack_types()` 从一组根模型出发，
递归收集其**嵌套引用**的全部自定义类型（含 `list[X]` / `X | None` 等容器写法）。
原因是一个实测教训：手写清单时最常漏的恰恰是**嵌在模型内部的类型** ——
初版就漏掉了 `FinalRecommendation` 里的 `DecisionStep` / `EvidenceItem` 与
`VascMeasurement` 里的 `CenterlinePoint`。递归展开后，「凡是 state 里可达的自定义类型
都被登记」成为**构造性事实**，不再依赖开发者每次新增模型时记得回来补一行。

**这一条由测试守住**（`test_allowlist_covers_every_type_in_state`）：测试从一次真实运行
的 state 里**反推**出全部自定义类型，再与白名单比对，因此新增模型若漏注册会立即失败。
另有一个阳性对照（`test_canary_unregistered_types_are_observably_flagged`）绕开白名单
构造 saver，证明「零告警」这个断言不是空的。

> ⚠️ **一个反直觉的实测结论**：`LANGGRAPH_STRICT_MSGPACK=true` **不是**更可靠的守卫。
> 实测在该模式下，未注册类型的 state 依然能正确往返，而且**不再产生任何告警** ——
> 既不报错也不提示，风险反而更隐蔽。所以真正的防线只有「白名单完整 + 测试比对」，
> 不要指望这个环境变量替你发现问题。

### 6. 编排层当前的三处留白

| 留白 | 位置 | 当前状态 |
|---|---|---|
| 诊疗方式建议 | `output_layer` 的 `primary_recommendation` / `treatment_options` | 显式占位文本，**不含任何临床主张** |
| LLM 输出转译 | `FinalRecommendation.translated_text` | 保持 `None` |
| 5 个确定性工具 | `execution_layer` 的 `TOOL_REGISTRY` | `tool_outputs` 恒为空，每个工具写明阻塞原因 |

**为什么宁可留白**：这三处一旦填上，就等于往代码里引入了一批**新的「规则内容」**
（评分口径、建议文案）。按本项目的变更纪律，那必须新增一张版本表并注册进
`src/rules/version.py`，否则审计链恰在这一点断开。所以正确顺序是**先定口径、再写代码**。

---

## 六、快速开始

> **环境要求：Python 3.13.x**（本项目锁定 `3.13.14`，见 `.python-version` 与「七、依赖版本策略」）。
> 依赖与环境由 **uv** 管理（`pyproject.toml` + `uv.lock`），一条命令即可同步。

```bash
# 0) 如未安装 uv：
#    Windows(PowerShell): irm https://astral.sh/uv/install.ps1 | iex
#    macOS / Linux:       curl -LsSf https://astral.sh/uv/install.sh | sh

# 1) 建环境 + 安装全部依赖（≈ npm install）
uv sync

# 2) 运行占位入口（≈ npm run）
uv run main.py
```

> - uv 会自动创建 `.venv/` 并按 `uv.lock` **精确安装**，**无需手动 `activate`**；
> - 首次克隆若尚无 `uv.lock`，执行 `uv sync` 会自动生成。

预期输出：打印项目名称与当前阶段（`skeleton`）。

### 跑一次术前流水线（编排层）

`main.py` 仍是占位入口。要实际跑通「病例 → 最终建议 + 可审计落盘」，直接用编排层入口：

```python
from src.models.enums import (
    DiseaseCategory,
    PriorRepair,
    RuptureStatus,
    Sex,
    SymptomAAA,
    TemporalStatus,
)
from src.models.preop.case import VascCase
from src.preop_agent.graph import build_preop_graph, run_preop, sqlite_checkpointer, thread_config

case = VascCase(
    case_id="DEMO-001",
    age=72,
    sex=Sex.MALE,
    temporal_status=TemporalStatus.CURRENT,
    symptom_aaa_related=SymptomAAA.ABSENT,
    rupture_status=RuptureStatus.INTACT,
    prior_repair=PriorRepair.NONE,
    disease_category=[DiseaseCategory.ASYMPTOMATIC],
    max_diameter_mm=42.0,
    neck_length_mm=25.0,
    neck_angle_deg=20.0,
    access_diameter_mm=9.0,
    anatomy_level="肾下",
)

# 默认落在 .workbuddy/state/preop_checkpoints.sqlite（该目录已被 .gitignore 忽略）
with sqlite_checkpointer() as saver:
    state = run_preop(case, checkpointer=saver, thread_id="DEMO-001")

print(state["final_recommendation"].route_mode)  # 指南模式
print(len(state["final_recommendation"].decision_path))  # 10（含被否决项）
print([record.node for record in state["audit_trail"]])  # 四个节点

# 换一个**独立连接**读回同一份 state —— 这就是「全程可审计」的兑现
with sqlite_checkpointer() as reopened:
    app = build_preop_graph(checkpointer=reopened)
    print(app.get_state(thread_config("DEMO-001")).values["case"].case_id)  # DEMO-001
```

> 脚本须**从仓库根**运行（`uv run python xxx.py` 或 `python -m`），否则 `import src` 会失败。

### 常用命令（测试 / 检查）

```bash
# 跑全部测试（应为 158 passed）
uv run pytest tests/ -q

# 静态检查（应为 All checks passed）
uv run ruff check src/ tests/

# 格式检查（不改文件；加 --diff 可预览改动）
uv run ruff format --check src/ tests/
uv run ruff format src/ tests/          # 真正改写文件

# 覆盖率（按需，比朴素跑慢约 7 倍，会在仓库根生成 .coverage）
uv run pytest tests/ --cov --cov-report=term-missing
```

> 也可以用解释器直接调用（等价）：`.venv/Scripts/python.exe -m pytest tests/ -q`。
> **`pytest` 必须能从仓库根导入 `src`**，因此 `pyproject.toml` 保留了
> `[tool.pytest.ini_options] pythonpath = ["."]` —— 移除它会让裸命令 `pytest` 报
> `ModuleNotFoundError: No module named 'src'`（详见「八、开发约定」）。

### 查看测试结果

- **逐条通过/失败**：`pytest tests/ -v`，或 `--junit-xml=report.xml` 导出后转 HTML；
- **覆盖了哪些代码**：`--cov-report=html` 生成 `htmlcov/index.html`，红色行即未被测试执行到的分支。

> ⚠️ **覆盖率 ≠ 测试结果**：前者衡量「代码有多少行被执行到」，后者衡量「每个用例过没过」。
> 两者互补 —— 一个看「测了没有」，一个看「测的对不对」。当前 158 项全绿、覆盖率 97%。

---

## 七、依赖版本策略（已锁定）

> 锁定日期：**2026-10-09**。锁定后如无必要请勿升级，避免版本漂移导致安装/运行不一致。

### 1. 解释器版本

| 项目 | 版本 | 说明 |
|---|---|---|
| 目标 | **Python 3.13.x** | 锁定 `3.13.14`（实测通过），见 `.python-version` |
| 下限 | ≥ 3.12 | 由 `numpy 2.5.x` 决定（其要求 `>=3.12`） |
| 上限 | < 3.14 | `langgraph 1.2.x` 官方分类器目前止于 3.13，故 3.14 暂不采用 |

### 2. 运行时依赖（精确锁定）

| 包 | 锁定版本 | 作用 | 对 Python 要求 |
|---|---|---|---|
| langgraph | `1.2.14` | 编排 / 状态机 / Checkpoint | ≥ 3.10 |
| langchain | `1.4.4` | Agent 框架（1.x） | ≥ 3.10, < 4 |
| langchain-core | `1.6.9` | 生态基座（兼容性锚点） | ≥ 3.10, < 4 |
| langchain-openai | `1.7.0` | OpenAI / DeepSeek 兼容接入 | ≥ 3.10 |
| langgraph-checkpoint-sqlite | `3.1.1` | Checkpoint 落 SQLite（全程可审计） | ≥ 3.10 |
| python-dotenv | `1.2.4` | 读取 `.env` 配置 | ≥ 3.10 |
| pydantic | `2.14.0` | 数据模型 / 校验 | ≥ 3.10 |
| numpy | `2.5.3` | 数值计算 | ≥ 3.12 |
| scikit-learn | `1.9.1` | 风险计算（logistic）等 | ≥ 3.11 |

### 3. 兼容性要点（必须同时满足）

- **Python 下限由 numpy 决定**：`numpy 2.5.3` 要求 `>=3.12`，`scikit-learn 1.9.1` 要求 `>=3.11`，其余库仅要求 `>=3.10`。取交集 → **Python 3.12 ~ 3.13**，本项目锁定 **3.13.14**。
- **LangChain 家族必须「同代」**：`langchain` / `langchain-core` / `langchain-openai` 互为依赖，必须同时处于 **1.x** 世代。一旦混入旧版 `langchain-core`（0.x），安装即报依赖冲突 —— 这是最常见的坑。
- **langgraph 与 langchain 同代**：LangChain 1.x 的 agent 运行在 LangGraph 之上，本组合取 `langgraph 1.2.x` + `langchain 1.x`。
- **pydantic 必须 v2**：`langchain-core 1.x` 依赖 pydantic v2，本组合用 `2.14.0`；切勿混入 pydantic v1（且 pydantic v1 不兼容 Python ≥3.14）。
- **numpy 2.x 与 scikit-learn 1.9.x 兼容**：sklearn 要求 `numpy>=1.24.1`、`scipy>=1.10.0`，`numpy 2.5.3` 满足。
- **依赖真源与锁定**：直接依赖写在 `pyproject.toml`；`uv.lock` 锁定**全部（含传递）**依赖，二者均入库，保证任何人 `uv sync` 得到一致结果。
- **传递依赖**：`scipy`、`openai`、`pydantic-core`、`joblib` 等**无需手写**，由 `uv.lock` 统一精确锁定。

### 4. 安装与「完全复现」

```bash
uv sync              # 按 pyproject.toml + uv.lock 建环境并精确安装（≈ npm install / npm ci）
uv lock              # 依赖变更后刷新 uv.lock（≈ 更新 package-lock.json）
uv add <pkg>         # 新增依赖（自动写入 pyproject.toml 并刷新锁 ≈ npm install <pkg>）
uv add --dev <pkg>   # 新增开发依赖
uv run <cmd>         # 在项目环境中执行命令（≈ npm run）
```

### 5. 复核与注意

```bash
uv run python -V     # 应输出 Python 3.13.x
uv tree              # 查看依赖树
uv pip check         # 检查是否存在依赖冲突
```

- 上述版本为 **2026-10-09** 各库当前最新稳定版。
- ✅ **已用 `uv lock` 实际解析验证**（2026-10-09）：共 **65 个包**全部解析成功、无依赖冲突，上表 9 个直接依赖版本与 `uv.lock` **完全一致**。
- 传递依赖由 `uv.lock` 精确锁定，例如 `scipy 1.18.1`、`openai 3.26.1`、`pydantic-core 2.50.0`、`langgraph-checkpoint 4.2.0`；开发依赖 `pytest 9.1.1`、`pytest-cov 7.1.0`、`ruff 0.16.10`。

---

## 八、开发约定

- **规则优先**：凡属确定性判定（路由 / 评分 / 分层 / 规划 / 预警 / 仲裁）一律以确定性代码实现，不交由 LLM。
- **LLM 边界**：LLM 仅承担输入抽取与输出转译，且不得改写数值与结论。
- **判定层禁 LLM**：`src/rules/**` 及全部判定层函数**禁止 import 任何 LLM 客户端** —— 硬性约束（见「四」）。
- **规则变更纪律**：改动任何阈值 / 病种归属 / 覆盖规则后，**必须** bump `src/rules/version.py` 的版本号
  并在 `RULESET_CHANGELOG` 记录原因；否则历史结论无法追溯复现。
- **可审计**：全链路使用 LangGraph Checkpoint 留存状态，所有建议附证据链，可追溯至原始字段出处。
- **模型与规则分离**：`models/` 只管结构，`rules/` 只管判定；依赖方向单向 `models → rules`，
  跨层引用用**延迟导入**破循环（见 `case.py::derive()` 内部导入）。
- **`VascCase` 管输入不管产物**：工具产物各自独立成模型，**不回写 `VascCase`**。
- **文档单一真源**：目录职责统一在本文档「三、目录结构」维护，**不在子目录下另建 `README.md`**，
  避免多处维护导致漂移。
- **增量填充**：按「确定性内核优先」顺序推进，每阶段须保证测试全绿 + `ruff` 无告警。
- **`__init__.py` 非必需**：Python 3 命名空间包（PEP 420）无它也能导入。是否保留按实际需要判断 ——
  需要 **re-export / 显式包边界** 时保留；纯标记用途可省略。
  省略前须确认两点：①本包无 `from .pkg import X` 形式的 re-export 消费者（否则直接 ImportError）；
  ②目录内还有其他文件（**git 不跟踪空目录**，否则目录会从版本库消失）。
  若省略的是 pytest 直接运行的目录，须保留 `pyproject.toml` 的 `pythonpath = ["."]`。

---

## 九、许可证

本项目基于 [MIT License](./LICENSE) 开源。
