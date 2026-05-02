"""Schemas for the multi-agent analysis endpoint."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class AgentBreakdown(BaseModel):
    view: str
    confidence: float
    reasoning: str
    key_points: list[str] = []
    risk_flags: list[str] = []


class AnalysisReportResponse(BaseModel):
    symbol: str
    action: str
    confidence: float
    summary: str
    reasoning: str
    risk_flags: list[str]
    components: dict[str, Any]
    approved: bool
    generated_at: datetime
    llm_powered: bool


class AnalyzeRequest(BaseModel):
    portfolio_context: Optional[str] = None
