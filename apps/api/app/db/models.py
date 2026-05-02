from datetime import datetime, timezone as _tz
from datetime import date as _date
from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.db.base import Base


class InstrumentORM(Base):
    __tablename__ = "instruments"

    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    exchange: Mapped[str] = mapped_column(String(8), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    industry: Mapped[str] = mapped_column(String(128), nullable=False, default="unknown")
    list_date: Mapped[str | None] = mapped_column(String(16), nullable=True)
    delist_date: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="listed")
    is_st: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class TradingCalendarORM(Base):
    __tablename__ = "trading_calendar"
    __table_args__ = (UniqueConstraint("trade_date", "market", name="uq_calendar_date_market"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    market: Mapped[str] = mapped_column(String(8), nullable=False)
    is_open: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    session_type: Mapped[str] = mapped_column(String(32), nullable=False, default="regular")


class MarketBarDailyORM(Base):
    __tablename__ = "market_bar_daily"
    __table_args__ = (UniqueConstraint("symbol", "trade_date", "adj_type", name="uq_bar_symbol_date_adj"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    trade_date: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    turnover_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    adj_type: Mapped[str] = mapped_column(String(8), nullable=False, default="qfq")
    data_source: Mapped[str] = mapped_column(String(32), nullable=False)


class NewsArticleORM(Base):
    __tablename__ = "news_articles"

    article_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    symbols: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)


class NewsEventORM(Base):
    __tablename__ = "news_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    article_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sentiment_score: Mapped[float] = mapped_column(Float, nullable=False)
    urgency_score: Mapped[float] = mapped_column(Float, nullable=False)
    relevance_score: Mapped[float] = mapped_column(Float, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    llm_reasoning_version: Mapped[str] = mapped_column(String(64), nullable=False, default="keyword_v1")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)


class OrderORM(Base):
    __tablename__ = "orders"

    order_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    order_type: Mapped[str] = mapped_column(String(16), nullable=False, default="LIMIT")
    price: Mapped[float] = mapped_column(Float, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    filled_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    broker_order_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="MANUAL")
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class TradeFillORM(Base):
    __tablename__ = "trade_fills"

    fill_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    fill_price: Mapped[float] = mapped_column(Float, nullable=False)
    fill_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    fill_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    commission: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)


class RiskRuleORM(Base):
    __tablename__ = "risk_rules"

    rule_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    rule_type: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    action_on_breach: Mapped[str] = mapped_column(String(32), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class RiskEventORM(Base):
    __tablename__ = "risk_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    rule_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    symbol: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)


class SignalSnapshotORM(Base):
    __tablename__ = "signal_snapshots"

    signal_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    as_of_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    signal_type: Mapped[str] = mapped_column(String(32), nullable=False)
    raw_score: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    components: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    expected_horizon: Mapped[str] = mapped_column(String(64), nullable=False, default="swing_5d")
    model_version: Mapped[str] = mapped_column(String(64), nullable=False, default="v1")


class AuditLogORM(Base):
    __tablename__ = "audit_logs"

    log_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)


class PortfolioSnapshotORM(Base):
    __tablename__ = "portfolio_snapshots"

    account_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    portfolio_name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_currency: Mapped[str] = mapped_column(String(16), nullable=False)
    total_asset: Mapped[float] = mapped_column(Float, nullable=False)
    cash: Mapped[float] = mapped_column(Float, nullable=False)
    market_value: Mapped[float] = mapped_column(Float, nullable=False)
    daily_pnl: Mapped[float] = mapped_column(Float, nullable=False)
    total_pnl: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class PositionORM(Base):
    __tablename__ = "positions"

    position_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    available_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    avg_cost: Mapped[float] = mapped_column(Float, nullable=False)
    market_value: Mapped[float] = mapped_column(Float, nullable=False)
    unrealized_pnl: Mapped[float] = mapped_column(Float, nullable=False)
    realized_pnl: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class RecommendationORM(Base):
    __tablename__ = "recommendations"

    recommendation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    target_weight: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    time_horizon: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_summary: Mapped[str] = mapped_column(Text, nullable=False)
    risk_flags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)


class RecommendationExplanationORM(Base):
    __tablename__ = "recommendation_explanations"

    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    drivers: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    risk_notes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    sources: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class WatchlistORM(Base):
    """User-managed list of symbols to scan for buy/sell opportunities."""
    __tablename__ = "watchlist"
    __table_args__ = (UniqueConstraint("account_id", "symbol", name="uq_watchlist_acct_sym"),)

    item_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class FactorSnapshotORM(Base):
    """Versioned feature values for trace-back (Design Doc §5.3.8)."""
    __tablename__ = "factor_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "symbol", "as_of_time", "factor_name", "feature_set_version",
            name="uq_factor_snapshot",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    as_of_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    factor_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    factor_value: Mapped[float] = mapped_column(Float, nullable=False)
    feature_set_version: Mapped[str] = mapped_column(String(32), nullable=False)
    data_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        default=lambda: datetime.now(_tz.utc).replace(tzinfo=None),
    )


class ModelRunORM(Base):
    """Record every train / inference / backtest run (Design Doc §5.3.9)."""
    __tablename__ = "model_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    model_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    model_version: Mapped[str] = mapped_column(String(32), nullable=False)
    run_type: Mapped[str] = mapped_column(String(16), nullable=False)
    train_window_start: Mapped[_date | None] = mapped_column(Date, nullable=True)
    train_window_end: Mapped[_date | None] = mapped_column(Date, nullable=True)
    score_metrics: Mapped[str | None] = mapped_column(Text, nullable=True)
    params: Mapped[str | None] = mapped_column(Text, nullable=True)
    artifact_uri: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="success")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class MarketBar1mORM(Base):
    """1-minute K-line (Design Doc §5.3.4). Schema present; ingest opt-in."""
    __tablename__ = "market_bar_1m"
    __table_args__ = (
        UniqueConstraint("symbol", "bar_time", "data_source", name="uq_bar1m_symbol_time"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    bar_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    data_source: Mapped[str] = mapped_column(String(32), nullable=False)

