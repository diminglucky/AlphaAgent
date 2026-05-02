from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


class InstrumentResponse(BaseModel):
    symbol: str
    exchange: str
    name: str
    industry: str
    list_date: Optional[date] = None
    delist_date: Optional[date] = None
    status: str
    is_st: bool


class MarketBarResponse(BaseModel):
    symbol: str
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    amount: float
    turnover_rate: float
    adj_type: str
    data_source: str


class RealtimeQuoteResponse(BaseModel):
    symbol: str
    quote_time: datetime
    last_price: float
    bid1: float
    ask1: float
    volume: int
    turnover: float
    pct_change: float
    limit_up: float
    limit_down: float
