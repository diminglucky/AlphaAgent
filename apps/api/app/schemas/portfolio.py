from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class PortfolioSummaryResponse(BaseModel):
    account_id: str
    portfolio_name: str
    base_currency: str
    total_asset: float
    cash: float
    market_value: float
    daily_pnl: float
    total_pnl: float
    updated_at: datetime


class PositionResponse(BaseModel):
    position_id: str
    account_id: str
    symbol: str
    quantity: int
    available_quantity: int
    avg_cost: float
    market_value: float
    unrealized_pnl: float
    realized_pnl: float
    updated_at: datetime


class RebalanceRequest(BaseModel):
    signals: dict[str, float] = Field(
        description="Signal scores per symbol (-1 to 1). Positive = bullish candidate."
    )
    prices: dict[str, float] = Field(
        description="Current price per symbol (used to convert value-change to shares)."
    )
    scheme: str = Field(
        default="signal_proportional",
        description=(
            "Allocation scheme: signal_proportional | equal_weight | "
            "inverse_volatility | risk_adjusted"
        ),
    )
    volatilities: Optional[dict[str, float]] = Field(
        default=None,
        description="20-day daily volatility per symbol (required for inverse_volatility / risk_adjusted).",
    )


class RebalanceActionResponse(BaseModel):
    symbol: str
    current_weight: float
    target_weight: float
    action: str
    quantity_change: int
    estimated_value_change: float
    reason: str


class RebalanceResponse(BaseModel):
    actions: list[RebalanceActionResponse]
    expected_turnover: float
    expected_cash_ratio: float
    risk_metrics: dict[str, float]
    warnings: list[str]

