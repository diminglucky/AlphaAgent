from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class RiskRuleResponse(BaseModel):
    rule_id: str
    rule_type: str
    scope: str
    threshold: float
    action_on_breach: str
    enabled: bool
    description: str
    updated_at: datetime


class CreateRiskRuleRequest(BaseModel):
    rule_type: str
    scope: str = Field(..., examples=["symbol", "portfolio", "order"])
    threshold: float = Field(..., gt=0)
    action_on_breach: str = Field(..., examples=["BLOCK", "WARN"])
    description: str = ""


class UpdateRiskRuleRequest(BaseModel):
    threshold: Optional[float] = Field(default=None, gt=0)
    enabled: Optional[bool] = None
    description: Optional[str] = None


class RiskEventResponse(BaseModel):
    event_id: str
    rule_id: str
    symbol: Optional[str]
    severity: str
    message: str
    decision: str
    details: dict
    created_at: datetime
