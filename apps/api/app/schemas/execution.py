from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class OrderSimulationRequest(BaseModel):
    symbol: str
    side: str = Field(..., examples=["BUY"])
    quantity: int = Field(..., gt=0)
    price: float = Field(..., gt=0)


class OrderSimulationResponse(BaseModel):
    accepted: bool
    reasons: list[str]
    estimated_notional: float
    required_cash: float
    remaining_cash_after_order: float
    risk_checks: list[str]


class PlaceOrderRequest(BaseModel):
    symbol: str
    side: str = Field(..., examples=["BUY"])
    order_type: str = Field(default="LIMIT", examples=["LIMIT", "MARKET"])
    quantity: int = Field(..., gt=0)
    price: float = Field(..., gt=0)
    source: str = Field(default="MANUAL", examples=["MANUAL", "SIGNAL"])
    confirmation_token: Optional[str] = Field(
        default=None,
        description=(
            "Manual confirmation token (§5.5.4). Required when "
            "QUANT_REQUIRE_ORDER_CONFIRMATION is enabled. Obtain via POST "
            "/orders/live/confirm-token with payload digest."
        ),
    )


class OrderResponse(BaseModel):
    order_id: str
    account_id: str
    symbol: str
    side: str
    order_type: str
    price: float
    quantity: int
    filled_quantity: int
    status: str
    broker_order_id: Optional[str]
    source: str
    reject_reason: Optional[str]
    created_at: datetime
    updated_at: datetime


class TradeFillResponse(BaseModel):
    fill_id: str
    order_id: str
    symbol: str
    fill_price: float
    fill_quantity: int
    fill_time: datetime
    commission: float


class SimulateFillRequest(BaseModel):
    fill_price: float = Field(..., gt=0)
    fill_quantity: int = Field(..., gt=0)

