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

> ⚠️ **本阶段仅完成项目骨架（skeleton），不包含任何业务逻辑。**

- 三 Agent 的完整目录骨架已搭好，每个目录含占位 `__init__.py`；
- `src/models/` 下的 `preop.py` / `intraop.py` / `postop.py` 为**占位文件**（仅 docstring 声明规划中的模型，无实现）；
- `main.py` 为占位入口，仅打印项目名称与当前阶段；
- 暂无任何函数实现、类定义或业务逻辑代码；
- 尚未接入 LangGraph 编排、LLM 调用与确定性工具。

后续开发将按「确定性内核优先」的顺序逐步填充：先落地数据模型与确定性工具，再串接各层流水线。

---

## 三、目录结构

```
zs-Midea VascGuide/
├── docs/                       # 架构文档、临床指南（如 ESVS 2024）
├── src/
│   ├── core/                   # 核心引擎（LangGraph 编排、状态管理、Checkpoint）
│   ├── models/                 # Pydantic 数据模型
│   │   ├── preop.py            # VascCase, ToolManifest, VascMeasurement, FinalRecommendation
│   │   ├── intraop.py          # IntraOpIntent（预留）
│   │   └── postop.py           # PostOpCase, FollowUpPlan, FollowUpStatus（预留）
│   ├── tools/                  # 确定性工具集（指南引擎、影像量化器、解剖评分器等）
│   ├── utils/                  # 工具函数（LLM 调用封装、Checkpoint 管理）
│   ├── preop_agent/            # 术前决策 Agent
│   │   ├── input_layer/        # 输入层（LLM 抽取、急诊初筛）
│   │   ├── router_layer/       # 路由层（四模式调度）
│   │   ├── execution_layer/    # 执行层（5 个确定性工具）
│   │   └── output_layer/       # 聚合输出层（聚合、仲裁、转译）
│   ├── intraop_agent/          # 术中导航 Agent（预留）
│   │   ├── localization/       # 术中定位
│   │   ├── assessment/         # 术中评估
│   │   ├── monitoring/         # 生命体征监测
│   │   └── decision_tree/      # 确定性决策树
│   └── postop_agent/           # 术后随访 Agent（预留）
│       ├── case_update/        # ① 病例更新
│       ├── risk_stratify/      # ② 风险分层
│       ├── followup_plan/      # ③ 随访规划
│       ├── anomaly_monitor/    # ④ 异常监控
│       ├── status_manager/     # ⑤ 状态管理
│       └── output_translate/   # ⑥ 输出转译
├── tests/                      # 测试
├── requirements.txt            # 依赖清单（核心依赖，已锁定精确版本）
├── main.py                     # 系统入口（占位）
├── LICENSE                     # MIT
├── .gitignore                  # Python 模板
├── .python-version             # 解释器版本锁定（3.13.14）
└── README.md
```

> 说明：本仓库根目录即为项目根目录。上述每个目录均包含一个占位的 `__init__.py`。

---

## 四、快速开始

> **环境要求：Python 3.13.x**（本项目锁定 `3.13.14`，见 `.python-version` 与「五、依赖版本策略」）。

```bash
# 1) 创建虚拟环境（推荐）
python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

# 2) 安装核心依赖
pip install -r requirements.txt

# 3) 运行占位入口
python main.py
```

预期输出：打印项目名称与当前阶段（`skeleton`）。

---

## 五、依赖版本策略（已锁定）

> 锁定日期：**2026-10-09**。锁定后如无必要请勿升级，避免版本漂移导致安装/运行不一致。

### 1. 解释器版本

| 项目 | 版本 | 说明 |
|---|---|---|
| 目标 | **Python 3.13.x** | 锁定 `3.13.14`（实测通过），见 `.python-version` |
| 下限 | ≥ 3.12 | 由 `numpy 2.5.x` 决定（其要求 `>=3.12`） |
| 上限 | < 3.14 | `langgraph 1.2.x` 官方分类器目前止于 3.13，故 3.14 暂不采用 |

### 2. 核心依赖（精确锁定）

| 包 | 锁定版本 | 作用 | 对 Python 要求 |
|---|---|---|---|
| langgraph | `1.2.14` | 编排 / 状态机 / Checkpoint | ≥ 3.10 |
| langchain | `1.4.4` | Agent 框架（1.x） | ≥ 3.10, < 4 |
| langchain-core | `1.6.9` | 生态基座（兼容性锚点） | ≥ 3.10, < 4 |
| langchain-openai | `1.7.0` | OpenAI 模型接入 | ≥ 3.10 |
| pydantic | `2.14.0` | 数据模型 / 校验 | ≥ 3.10 |
| numpy | `2.5.3` | 数值计算 | ≥ 3.12 |
| scikit-learn | `1.9.1` | 风险计算（logistic）等 | ≥ 3.11 |

### 3. 兼容性要点（必须同时满足）

- **Python 下限由 numpy 决定**：`numpy 2.5.3` 要求 `>=3.12`，`scikit-learn 1.9.1` 要求 `>=3.11`，其余库仅要求 `>=3.10`。取交集 → **Python 3.12 ~ 3.13**，本项目锁定 **3.13.14**。
- **LangChain 家族必须「同代」**：`langchain` / `langchain-core` / `langchain-openai` 互为依赖，必须同时处于 **1.x** 世代。一旦混入旧版 `langchain-core`（0.x），安装即报依赖冲突 —— 这是最常见的坑。
- **langgraph 与 langchain 同代**：LangChain 1.x 的 agent 运行在 LangGraph 之上，本组合取 `langgraph 1.2.x` + `langchain 1.x`。
- **pydantic 必须 v2**：`langchain-core 1.x` 依赖 pydantic v2，本组合用 `2.14.0`；切勿混入 pydantic v1（且 pydantic v1 不兼容 Python ≥3.14）。
- **numpy 2.x 与 scikit-learn 1.9.x 兼容**：sklearn 要求 `numpy>=1.24.1`、`scipy>=1.10.0`，`numpy 2.5.3` 满足。
- **传递依赖**：`scipy`、`openai`、`pydantic-core`、`joblib` 等由 pip 自动解析，除非做 lock，否则不要手动钉死。

### 4. 安装与「完全复现」

```bash
# 安装锁定的直接依赖
pip install -r requirements.txt

# 如需锁定全部传递依赖（推荐用于生产 / CI）
pip install pip-tools
pip-compile requirements.txt -o requirements.lock.txt   # 生成完整锁文件
pip install -r requirements.lock.txt                    # 按锁文件精确安装
```

### 5. 复核与注意

```bash
python -V     # 应输出 Python 3.13.x
pip check     # 检查已装依赖是否存在冲突
pip freeze    # 查看实际解析出的全部版本
```

- 上述版本为 **2026-10-09** 各库当前最新稳定版。
- ⚠️ 本次锁定依据各库官方元数据（`Requires` / classifiers）推导，**尚未在联网环境实际安装验证**（当前沙箱无法直连 PyPI）。首次联网安装后，请执行上面的 `pip check` 并生成 `requirements.lock.txt` 复核。

---

## 六、开发约定（规划）

- **规则优先**：凡属确定性判定（路由 / 评分 / 分层 / 规划 / 预警 / 仲裁）一律以确定性代码实现，不交由 LLM。
- **LLM 边界**：LLM 仅承担输入抽取与输出转译，且不得改写数值与结论。
- **可审计**：全链路使用 LangGraph Checkpoint 留存状态，所有建议附证据链。
- **占位优先**：骨架阶段只建目录与占位文件，业务逻辑分阶段填充。

---

## 七、许可证

本项目基于 [MIT License](./LICENSE) 开源。
