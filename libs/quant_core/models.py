from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional


@dataclass(frozen=True)
class Instrument:
    symbol: str
    exchange: str
    name: str
    industry: str
    list_date: Optional[date]
    delist_date: Optional[date]
    status: str
    is_st: bool


@dataclass(frozen=True)
class MarketBar:
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


@dataclass(frozen=True)
class RealtimeQuote:
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


@dataclass(frozen=True)
class PortfolioSummary:
    account_id: str
    portfolio_name: str
    base_currency: str
    total_asset: float
    cash: float
    market_value: float
    daily_pnl: float
    total_pnl: float
    updated_at: datetime


@dataclass(frozen=True)
class Position:
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


@dataclass(frozen=True)
class Recommendation:
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


@dataclass(frozen=True)
class TradingCalendar:
    trade_date: date
    market: str
    is_open: bool
    session_type: str = "regular"


@dataclass(frozen=True)
class Order:
    order_id: str
    account_id: str
    symbol: str
    side: str
    order_type: str
    price: float
    quantity: int
    filled_quantity: int
    status: str
    source: str
    created_at: datetime
    updated_at: datetime
    broker_order_id: Optional[str] = None
    reject_reason: Optional[str] = None


@dataclass(frozen=True)
class TradeFill:
    fill_id: str
    order_id: str
    symbol: str
    fill_price: float
    fill_quantity: int
    fill_time: datetime
    commission: float = 0.0


@dataclass(frozen=True)
class RiskRuleConfig:
    rule_id: str
    rule_type: str
    scope: str
    threshold: float
    action_on_breach: str
    enabled: bool
    description: str
    updated_at: datetime


@dataclass(frozen=True)
class RiskEvent:
    event_id: str
    rule_id: str
    severity: str
    message: str
    decision: str
    created_at: datetime
    symbol: Optional[str] = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SignalSnapshot:
    signal_id: str
    symbol: str
    as_of_time: datetime
    signal_type: str
    raw_score: float
    confidence: float
    components: dict[str, Any]
    expected_horizon: str
    model_version: str


@dataclass(frozen=True)
class NewsArticleRecord:
    article_id: str
    source: str
    title: str
    published_at: datetime
    content_hash: str
    raw_text: str
    symbols: list[str]
    created_at: datetime
    url: Optional[str] = None


@dataclass(frozen=True)
class NewsEventRecord:
    event_id: str
    article_id: str
    event_type: str
    sentiment_score: float
    urgency_score: float
    relevance_score: float
    summary: str
    created_at: datetime
    llm_reasoning_version: str = "keyword_v1"


@dataclass(frozen=True)
class AuditLog:
    log_id: str
    action: str
    actor: str
    resource_type: str
    created_at: datetime
    resource_id: Optional[str] = None
    details: dict[str, Any] = field(default_factory=dict)
