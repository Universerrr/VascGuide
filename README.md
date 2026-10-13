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

> **确定性内核（数据模型 + 规则层）已落地并通过验证；编排层与 LLM 接入尚未开始。**

### ✅ 已完成

| 模块 | 内容 |
|---|---|
| **术前数据模型（5 个）** | `VascCase`（51 字段）、`VascMeasurement`、`AnatomyScore`、`RiskAssessment`、`FinalRecommendation` |
| **共享枚举（19 个）** | `StrEnum` + 中文值，覆盖性别、病种、破裂状态、解剖分型、恶性肿瘤等 |
| **审计留痕结构** | `FieldProvenance`（字段原文出处 / 写入者 / 置信度）、`UrgencyFlagAudit` |
| **确定性规则层** | `router.py`（P0a~P8 路由流水线）+ `version.py`（规则版本注册表），详见「四」 |
| **测试与工具链** | 108 项测试全绿（41 行为基线 + 67 数据契约）、`ruff` 无告警、覆盖率 97% |

### ⏳ 尚未开始

- **输入层 LLM 抽取器**（`preop_agent/input_layer/`）与**输出层转译**（`preop_agent/output_layer/`）——
  这是全项目**仅有的两个**允许出现 LLM 的节点。
- **`preop_agent/` 四层骨架** —— `router_layer/`（对规则层的薄封装）、`execution_layer/`（5 个确定性工具）。
- **LangGraph `StateGraph` 编排 + SQLite Checkpoint 落盘** —— 实现全程可审计。
- **术中 / 术后 Agent** —— `intraop_agent/`、`postop_agent/` 目前仅为目录骨架，无实现。
- **`main.py`** —— 仍为占位入口。

推进顺序遵循「**确定性内核优先**」：先落地数据模型与确定性工具，
**LLM 只在最后接入两端的抽取与转译节点**，中间管道保持零 LLM 参与。

---

## 三、目录结构

```
zs-Midea VascGuide/
├── docs/                        # 架构文档、临床指南（如 ESVS 2024）
├── src/
│   ├── core/                    # 核心引擎（LangGraph 编排、状态管理、Checkpoint）〔骨架〕
│   ├── models/                  # Pydantic 数据模型
│   │   ├── __init__.py          # ✅ 统一导出（模型 + 枚举 + 审计结构）
│   │   ├── enums.py             # ✅ 19 个共享枚举（StrEnum，中文值）
│   │   ├── audit.py             # ✅ 审计留痕结构（FieldProvenance / UrgencyFlagAudit）
│   │   ├── preop/               # ✅ 术前模型包（含 __init__.py 聚合导出）
│   │   │   ├── case.py          # ✅ VascCase（51 字段）+ derive()
│   │   │   ├── measurement.py   # ✅ VascMeasurement + CenterlinePoint
│   │   │   ├── assessment.py    # ✅ AnatomyScore + RiskAssessment
│   │   │   └── recommendation.py# ✅ FinalRecommendation + EvidenceItem + DecisionStep
│   │   ├── intraop.py           # IntraOpIntent（预留，空占位）
│   │   └── postop.py            # PostOpCase / FollowUpPlan / FollowUpStatus（预留，空占位）
│   ├── rules/                   # ✅ 确定性规则层（详见「四」；无 __init__.py）
│   │   ├── router.py            # ✅ P0a~P8 路由判定流水线（纯函数）
│   │   └── version.py           # ✅ 规则版本号注册表（审计必需）
│   ├── tools/                   # 确定性工具集（指南引擎、影像量化器、解剖评分器等）〔骨架〕
│   ├── utils/                   # 工具函数（LLM 调用封装、Checkpoint 管理）〔骨架〕
│   ├── preop_agent/             # 术前决策 Agent〔骨架，四层均为空目录〕
│   │   ├── input_layer/         # 输入层（LLM 抽取、急诊初筛）← 唯一 LLM 入口之一
│   │   ├── router_layer/        # 路由层（对 src/rules/ 的薄封装，临床规则 0 行）
│   │   ├── execution_layer/     # 执行层（5 个确定性工具）
│   │   └── output_layer/        # 聚合输出层（聚合、仲裁、转译）← 唯一 LLM 入口之一
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
├── tests/                       # 测试（无 __init__.py，见「七、开发约定」）
│   ├── test_preop.py            # ✅ 41 项路由行为基线
│   └── test_model_contract.py   # ✅ 67 项数据契约
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
> - 本仓库根目录即为项目根目录，**必须从仓库根运行**（`pyproject.toml` 中 `[tool.uv] package = false`，不是可安装包）。
> - **目录职责说明统一由本文档承载**，不再在子目录下另建 `README.md`（单一真源，避免多处维护漂移）。
> - **`__init__.py` 不是必需品**（PEP 420 命名空间包无它也能导入）。当前实际分布：
>   `src/models/` 与 `src/models/preop/` 保留（承载聚合 re-export）；
>   `src/rules/` 已移除（无 re-export 消费者）；`tests/` 已移除（非运行时包）。
>   是否省略的判据见「七、开发约定」。

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
> 且规则必须能独立测试（现在 53 项路由测试不需要 LangGraph、不需要数据库、0.1 秒跑完）。
> 绑定到 `preop_agent/` 下会导致跨层循环依赖、版本号漂移，并使「规则变更纪律」无法被机器检查。

---

## 五、快速开始

> **环境要求：Python 3.13.x**（本项目锁定 `3.13.14`，见 `.python-version` 与「六、依赖版本策略」）。
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

### 常用命令（测试 / 检查）

```bash
# 跑全部测试（应为 108 passed）
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
> `ModuleNotFoundError: No module named 'src'`（详见「七、开发约定」）。

### 查看测试结果

- **逐条通过/失败**：`pytest tests/ -v`，或 `--junit-xml=report.xml` 导出后转 HTML；
- **覆盖了哪些代码**：`--cov-report=html` 生成 `htmlcov/index.html`，红色行即未被测试执行到的分支。

> ⚠️ **覆盖率 ≠ 测试结果**：前者衡量「代码有多少行被执行到」，后者衡量「每个用例过没过」。
> 两者互补 —— 一个看「测全了没有」，一个看「测的对不对」。当前 108 项全绿、覆盖率 97%。

---

## 六、依赖版本策略（已锁定）

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

## 七、开发约定

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

## 八、许可证

本项目基于 [MIT License](./LICENSE) 开源。
