"""数据库模型 — AlphaAgent 核心表 + 推荐进化闭环"""
from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Float, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.db.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class WatchlistORM(Base):
    """自选股"""
    __tablename__ = "watchlist"
    __table_args__ = (UniqueConstraint("symbol", name="uq_watchlist_symbol"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)


class AlertORM(Base):
    """价格提醒 & Agent 提醒"""
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    alert_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # alert_type: price_above / price_below / agent_buy / agent_sell / stop_loss
    target_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    triggered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    feishu_sent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    triggered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class PositionORM(Base):
    """持仓（手动录入）"""
    __tablename__ = "positions"
    __table_args__ = (UniqueConstraint("symbol", name="uq_position_symbol"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    avg_cost: Mapped[float] = mapped_column(Float, nullable=False)
    stop_loss_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.08)
    take_profit_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.20)
    last_alert_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_alert_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)


class TradingAccountORM(Base):
    """交易账户快照（模拟盘或外部券商账户）"""
    __tablename__ = "trading_accounts"
    __table_args__ = (UniqueConstraint("account_id", name="uq_trading_account_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, default="PAPER")
    broker: Mapped[str] = mapped_column(String(32), nullable=False, default="paper")
    cash: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    available_cash: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    market_value: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_asset: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    raw: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)


class TradingPositionORM(Base):
    """交易账户持仓快照（与手动持仓 positions 隔离）"""
    __tablename__ = "trading_positions"
    __table_args__ = (UniqueConstraint("account_id", "symbol", name="uq_trading_position_account_symbol"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, default="PAPER", index=True)
    broker: Mapped[str] = mapped_column(String(32), nullable=False, default="paper")
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    market_value: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    raw: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)


class TradeOrderORM(Base):
    """订单记录：本地模拟盘和 QMT Gateway 统一落库"""
    __tablename__ = "trade_orders"
    __table_args__ = (UniqueConstraint("client_order_id", name="uq_trade_client_order_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_order_id: Mapped[str] = mapped_column(String(64), nullable=False)
    broker_order_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, default="PAPER")
    broker: Mapped[str] = mapped_column(String(32), nullable=False, default="paper")
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    order_type: Mapped[str] = mapped_column(String(16), nullable=False, default="LIMIT")
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING", index=True)
    filled_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_fill_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="manual")
    strategy: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    raw: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)


class TradeFillORM(Base):
    """订单成交记录"""
    __tablename__ = "trade_fills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    broker_order_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    fee: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    filled_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now, index=True)
    evolution_recorded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    raw: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class AnalysisCacheORM(Base):
    """Agent 分析结果缓存"""
    __tablename__ = "analysis_cache"
    __table_args__ = (UniqueConstraint("symbol", name="uq_analysis_symbol"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    result: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)


class ModelVersionORM(Base):
    """推荐模型版本。

    这里的“模型”先从可解释规则权重开始，后续可替换为真实 ML 模型。
    """
    __tablename__ = "model_versions"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_model_name_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, default="scanner-evolution")
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="rule-v1")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    parent_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ScanRunORM(Base):
    """一次全市场扫描批次"""
    __tablename__ = "scan_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="scanner")
    params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    market_status: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    hot_industries: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    scanned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    candidates: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    analyzed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tier1_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tier2_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tier3_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    llm_status: Mapped[str] = mapped_column(String(24), nullable=False, default="disabled")
    elapsed_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now, index=True)


class StockPredictionORM(Base):
    """扫描器输出的可验证预测样本"""
    __tablename__ = "stock_predictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    model_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    action: Mapped[str] = mapped_column(String(24), nullable=False, default="BUY")
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False, default=5, index=True)
    target_return_pct: Mapped[float] = mapped_column(Float, nullable=False, default=3.0)
    stop_loss_pct: Mapped[float] = mapped_column(Float, nullable=False, default=8.0)
    probability: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    expected_return_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    confidence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    price_at_prediction: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    features: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    trade_plan: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    raw_result: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", index=True)
    predicted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now, index=True)
    due_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now, index=True)
    validated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class PredictionOutcomeORM(Base):
    """预测到期后的真实表现"""
    __tablename__ = "prediction_outcomes"
    __table_args__ = (UniqueConstraint("prediction_id", name="uq_prediction_outcome"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prediction_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    model_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    start_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    end_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    max_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    min_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    close_return_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    max_return_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    max_drawdown_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    hit_target: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    hit_stop: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    bars_checked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    validated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now, index=True)


class EvolutionRunORM(Base):
    """一次模型进化/校准运行"""
    __tablename__ = "evolution_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    candidate_model_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="completed")
    evaluated_predictions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    avg_return_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    brier_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    calibration_error: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    promoted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now, index=True)


class ModelMetricORM(Base):
    """模型按周期聚合后的指标"""
    __tablename__ = "model_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    avg_return_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    avg_max_return_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    brier_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    calibration_error: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    computed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now, index=True)


class LLMUsageORM(Base):
    """LLM token 用量与成本估算记录"""
    __tablename__ = "llm_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    model: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    endpoint: Mapped[str] = mapped_column(String(64), nullable=False, default="chat")
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    raw_usage: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now, index=True)
