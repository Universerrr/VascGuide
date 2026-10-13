"""解剖评分与风险评估 —— 工具 C（解剖评分器）与工具 E（风险评估器）的产物。

定位：
    两个评分器的产物都是**计算**得出（非 LLM 抽取），故独立成模型，不回写 VascCase。

⚠️ 评分规则本身应尽量确定性、可复现；如引入模型/量表，须在审计中记录量表版本。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AnatomyScore(BaseModel):
    """解剖评分器（工具 C）产物：量化 EVAR 解剖可行性。

    注：具体量表与阈值以工程实现为准，本模型只做数据承载。
    """

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(..., description="关联病例标识。")

    # ---- 各项评分 ----
    proximal_neck_score: float | None = Field(
        default=None, description="近端锚定区评分（越低越不利）。"
    )
    access_score: float | None = Field(default=None, description="入路评分。")
    angulation_score: float | None = Field(default=None, description="成角评分。")
    calcification_score: float | None = Field(default=None, description="钙化/血栓评分。")
    total_score: float | None = Field(default=None, description="总分（各项加权汇总）。")

    # ---- 结论 ----
    evar_feasibility: str | None = Field(
        default=None,
        description="EVAR 解剖可行性结论（如：标准 / 挑战 / 不宜）。",
    )
    adverse_features: list[str] = Field(
        default_factory=list,
        description="不利解剖特征清单。",
    )

    # ---- 审计 ----
    scoring_system: str | None = Field(
        default=None, description="所用评分体系/量表名称与版本（审计必需）。"
    )


class RiskAssessment(BaseModel):
    """风险评估器（工具 E）产物：围术期与远期风险分层。"""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(..., description="关联病例标识。")

    # ---- 风险分层 ----
    perioperative_risk: str | None = Field(
        default=None,
        description="围术期风险等级（如：低 / 中 / 高）。",
    )
    perioperative_mortality_pct: float | None = Field(
        default=None, ge=0, le=100, description="围术期预期死亡率（%）。"
    )
    longterm_survival_years: float | None = Field(
        default=None,
        ge=0,
        description="预期生存年限（年）。",
    )
    risk_score: float | None = Field(default=None, description="综合风险分值。")

    # ---- 结论 ----
    decision_support: str | None = Field(
        default=None,
        description="风险对治疗决策的支持意见（如：可耐受开放手术 / 建议微创）。",
    )
    risk_factors: list[str] = Field(
        default_factory=list,
        description="主要风险因素清单。",
    )

    # ---- 审计 ----
    model_name: str | None = Field(default=None, description="所用风险模型名称与版本（审计必需）。")


__all__ = ["AnatomyScore", "RiskAssessment"]
