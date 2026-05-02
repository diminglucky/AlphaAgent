from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RecommendationItemResponse(BaseModel):
    recommendation_id: str
    symbol: str
    action: str
    target_weight: float
    confidence: float
    time_horizon: str
    reason_summary: str
    risk_flags: list[str]
    status: str
    created_at: datetime


class RecommendationListResponse(BaseModel):
    as_of: datetime = Field(..., alias="asOf")
    items: list[RecommendationItemResponse]

    model_config = ConfigDict(populate_by_name=True)


class RecommendationExplainRequest(BaseModel):
    symbol: str


class RecommendationExplainResponse(BaseModel):
    symbol: str
    summary: str
    drivers: list[str]
    risk_notes: list[str]
    sources: list[str]
