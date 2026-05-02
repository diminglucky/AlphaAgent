from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def _utc_now() -> datetime:
    """Drop-in replacement for datetime.utcnow() (deprecated in 3.12)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from apps.api.app.db.models import (
    AuditLogORM,
    FactorSnapshotORM,
    InstrumentORM,
    MarketBarDailyORM,
    MarketBar1mORM,
    ModelRunORM,
    NewsArticleORM,
    NewsEventORM,
    OrderORM,
    PortfolioSnapshotORM,
    PositionORM,
    RecommendationExplanationORM,
    RecommendationORM,
    RiskEventORM,
    RiskRuleORM,
    SignalSnapshotORM,
    TradeFillORM,
)
from libs.quant_core.models import (
    AuditLog,
    MarketBar,
    NewsArticleRecord,
    NewsEventRecord,
    Order,
    PortfolioSummary,
    Position,
    Recommendation,
    RiskEvent,
    RiskRuleConfig,
    SignalSnapshot,
    TradeFill,
)


class PortfolioRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_summary(self) -> Optional[PortfolioSummary]:
        row = self.session.execute(select(PortfolioSnapshotORM)).scalar_one_or_none()
        if row is None:
            return None
        return PortfolioSummary(
            account_id=row.account_id,
            portfolio_name=row.portfolio_name,
            base_currency=row.base_currency,
            total_asset=row.total_asset,
            cash=row.cash,
            market_value=row.market_value,
            daily_pnl=row.daily_pnl,
            total_pnl=row.total_pnl,
            updated_at=row.updated_at,
        )

    def list_positions(self) -> list[Position]:
        rows = self.session.execute(
            select(PositionORM).order_by(PositionORM.symbol.asc())
        ).scalars()
        return [
            Position(
                position_id=row.position_id,
                account_id=row.account_id,
                symbol=row.symbol,
                quantity=row.quantity,
                available_quantity=row.available_quantity,
                avg_cost=row.avg_cost,
                market_value=row.market_value,
                unrealized_pnl=row.unrealized_pnl,
                realized_pnl=row.realized_pnl,
                updated_at=row.updated_at,
            )
            for row in rows
        ]

    def get_position(self, account_id: str, symbol: str) -> Optional[PositionORM]:
        return self.session.execute(
            select(PositionORM).where(
                PositionORM.account_id == account_id,
                PositionORM.symbol == symbol,
            )
        ).scalar_one_or_none()

    def upsert_position(self, position: Position) -> None:
        existing = self.get_position(position.account_id, position.symbol)
        if existing is None:
            self.session.add(PositionORM(
                position_id=position.position_id,
                account_id=position.account_id,
                symbol=position.symbol,
                quantity=position.quantity,
                available_quantity=position.available_quantity,
                avg_cost=position.avg_cost,
                market_value=position.market_value,
                unrealized_pnl=position.unrealized_pnl,
                realized_pnl=position.realized_pnl,
                updated_at=position.updated_at,
            ))
        else:
            existing.quantity = position.quantity
            existing.available_quantity = position.available_quantity
            existing.avg_cost = position.avg_cost
            existing.market_value = position.market_value
            existing.unrealized_pnl = position.unrealized_pnl
            existing.realized_pnl = position.realized_pnl
            existing.updated_at = position.updated_at
        self.session.flush()

    def remove_position(self, account_id: str, symbol: str) -> None:
        existing = self.get_position(account_id, symbol)
        if existing is not None:
            self.session.delete(existing)
            self.session.flush()

    def save_summary(self, summary: PortfolioSummary) -> None:
        existing = self.session.execute(
            select(PortfolioSnapshotORM).where(
                PortfolioSnapshotORM.account_id == summary.account_id
            )
        ).scalar_one_or_none()
        if existing is None:
            self.session.add(PortfolioSnapshotORM(
                account_id=summary.account_id,
                portfolio_name=summary.portfolio_name,
                base_currency=summary.base_currency,
                total_asset=summary.total_asset,
                cash=summary.cash,
                market_value=summary.market_value,
                daily_pnl=summary.daily_pnl,
                total_pnl=summary.total_pnl,
                updated_at=summary.updated_at,
            ))
        else:
            existing.total_asset = summary.total_asset
            existing.cash = summary.cash
            existing.market_value = summary.market_value
            existing.daily_pnl = summary.daily_pnl
            existing.total_pnl = summary.total_pnl
            existing.updated_at = summary.updated_at
        self.session.flush()


class RecommendationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_latest(self) -> tuple[Optional[datetime], list[Recommendation]]:
        rows = self.session.execute(
            select(RecommendationORM).order_by(
                desc(RecommendationORM.created_at), RecommendationORM.symbol.asc()
            )
        ).scalars().all()

        if not rows:
            return None, []

        as_of = max(row.created_at for row in rows)
        return as_of, [
            Recommendation(
                recommendation_id=row.recommendation_id,
                symbol=row.symbol,
                action=row.action,
                target_weight=row.target_weight,
                confidence=row.confidence,
                time_horizon=row.time_horizon,
                reason_summary=row.reason_summary,
                risk_flags=list(row.risk_flags or []),
                status=row.status,
                created_at=row.created_at,
            )
            for row in rows
        ]

    def get_by_symbol(self, symbol: str) -> Optional[Recommendation]:
        row = self.session.execute(
            select(RecommendationORM).where(RecommendationORM.symbol == symbol)
        ).scalar_one_or_none()
        if row is None:
            return None
        return Recommendation(
            recommendation_id=row.recommendation_id,
            symbol=row.symbol,
            action=row.action,
            target_weight=row.target_weight,
            confidence=row.confidence,
            time_horizon=row.time_horizon,
            reason_summary=row.reason_summary,
            risk_flags=list(row.risk_flags or []),
            status=row.status,
            created_at=row.created_at,
        )

    def get_explanation(self, symbol: str) -> Optional[dict[str, object]]:
        row = self.session.execute(
            select(RecommendationExplanationORM).where(
                RecommendationExplanationORM.symbol == symbol
            )
        ).scalar_one_or_none()
        if row is None:
            return None

        return {
            "symbol": row.symbol,
            "summary": row.summary,
            "drivers": list(row.drivers or []),
            "risk_notes": list(row.risk_notes or []),
            "sources": list(row.sources or []),
        }

    def save(self, rec: Recommendation) -> None:
        self.session.merge(
            RecommendationORM(
                recommendation_id=rec.recommendation_id,
                symbol=rec.symbol,
                action=rec.action,
                target_weight=rec.target_weight,
                confidence=rec.confidence,
                time_horizon=rec.time_horizon,
                reason_summary=rec.reason_summary,
                risk_flags=rec.risk_flags,
                status=rec.status,
                created_at=rec.created_at,
            )
        )


class InstrumentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert(self, symbol: str, exchange: str, name: str, industry: str,
               list_date: Optional[str], delist_date: Optional[str],
               status: str, is_st: bool, updated_at: datetime) -> None:
        self.session.merge(InstrumentORM(
            symbol=symbol, exchange=exchange, name=name, industry=industry,
            list_date=list_date, delist_date=delist_date,
            status=status, is_st=is_st, updated_at=updated_at,
        ))

    def list_all(self) -> list[dict]:
        rows = self.session.execute(select(InstrumentORM)).scalars().all()
        return [
            {"symbol": r.symbol, "exchange": r.exchange, "name": r.name,
             "industry": r.industry, "list_date": r.list_date,
             "delist_date": r.delist_date, "status": r.status, "is_st": r.is_st}
            for r in rows
        ]

    def get(self, symbol: str) -> Optional[dict]:
        row = self.session.execute(
            select(InstrumentORM).where(InstrumentORM.symbol == symbol)
        ).scalar_one_or_none()
        if row is None:
            return None
        return {"symbol": row.symbol, "exchange": row.exchange, "name": row.name,
                "industry": row.industry, "list_date": row.list_date,
                "delist_date": row.delist_date, "status": row.status, "is_st": row.is_st}


class MarketBarRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_bars(self, bars: list[MarketBar]) -> int:
        count = 0
        for bar in bars:
            self.session.merge(MarketBarDailyORM(
                symbol=bar.symbol,
                trade_date=bar.trade_date.isoformat(),
                open=bar.open, high=bar.high, low=bar.low, close=bar.close,
                volume=bar.volume, amount=bar.amount,
                turnover_rate=bar.turnover_rate,
                adj_type=bar.adj_type, data_source=bar.data_source,
            ))
            count += 1
        return count

    def list_bars(self, symbol: str, start: Optional[str] = None,
                  end: Optional[str] = None) -> list[MarketBar]:
        from datetime import date
        q = select(MarketBarDailyORM).where(MarketBarDailyORM.symbol == symbol)
        if start:
            q = q.where(MarketBarDailyORM.trade_date >= start)
        if end:
            q = q.where(MarketBarDailyORM.trade_date <= end)
        q = q.order_by(MarketBarDailyORM.trade_date.asc())
        rows = self.session.execute(q).scalars().all()
        return [
            MarketBar(
                symbol=r.symbol,
                trade_date=date.fromisoformat(r.trade_date),
                open=r.open, high=r.high, low=r.low, close=r.close,
                volume=r.volume, amount=r.amount,
                turnover_rate=r.turnover_rate,
                adj_type=r.adj_type, data_source=r.data_source,
            )
            for r in rows
        ]


class OrderRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, order: Order) -> None:
        self.session.merge(OrderORM(
            order_id=order.order_id,
            account_id=order.account_id,
            symbol=order.symbol,
            side=order.side,
            order_type=order.order_type,
            price=order.price,
            quantity=order.quantity,
            filled_quantity=order.filled_quantity,
            status=order.status,
            broker_order_id=order.broker_order_id,
            source=order.source,
            reject_reason=order.reject_reason,
            created_at=order.created_at,
            updated_at=order.updated_at,
        ))

    def get(self, order_id: str) -> Optional[Order]:
        row = self.session.execute(
            select(OrderORM).where(OrderORM.order_id == order_id)
        ).scalar_one_or_none()
        if row is None:
            return None
        return self._to_domain(row)

    def list_by_account(self, account_id: str, limit: int = 50) -> list[Order]:
        rows = self.session.execute(
            select(OrderORM)
            .where(OrderORM.account_id == account_id)
            .order_by(desc(OrderORM.created_at))
            .limit(limit)
        ).scalars().all()
        return [self._to_domain(r) for r in rows]

    def update_status(self, order_id: str, status: str, broker_order_id: Optional[str],
                      filled_quantity: int, reject_reason: Optional[str],
                      updated_at: datetime) -> None:
        row = self.session.execute(
            select(OrderORM).where(OrderORM.order_id == order_id)
        ).scalar_one_or_none()
        if row:
            row.status = status
            row.filled_quantity = filled_quantity
            row.updated_at = updated_at
            if broker_order_id is not None:
                row.broker_order_id = broker_order_id
            if reject_reason is not None:
                row.reject_reason = reject_reason

    @staticmethod
    def _to_domain(row: OrderORM) -> Order:
        return Order(
            order_id=row.order_id,
            account_id=row.account_id,
            symbol=row.symbol,
            side=row.side,
            order_type=row.order_type,
            price=row.price,
            quantity=row.quantity,
            filled_quantity=row.filled_quantity,
            status=row.status,
            broker_order_id=row.broker_order_id,
            source=row.source,
            reject_reason=row.reject_reason,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


class TradeFillRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, fill: TradeFill) -> None:
        self.session.merge(TradeFillORM(
            fill_id=fill.fill_id,
            order_id=fill.order_id,
            symbol=fill.symbol,
            fill_price=fill.fill_price,
            fill_quantity=fill.fill_quantity,
            fill_time=fill.fill_time,
            commission=fill.commission,
        ))

    def list_by_order(self, order_id: str) -> list[TradeFill]:
        rows = self.session.execute(
            select(TradeFillORM).where(TradeFillORM.order_id == order_id)
            .order_by(TradeFillORM.fill_time.asc())
        ).scalars().all()
        return [TradeFill(
            fill_id=r.fill_id, order_id=r.order_id, symbol=r.symbol,
            fill_price=r.fill_price, fill_quantity=r.fill_quantity,
            fill_time=r.fill_time, commission=r.commission,
        ) for r in rows]


class RiskRuleRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_enabled(self) -> list[RiskRuleConfig]:
        rows = self.session.execute(
            select(RiskRuleORM).where(RiskRuleORM.enabled == True)
        ).scalars().all()
        return [self._to_domain(r) for r in rows]

    def list_all(self) -> list[RiskRuleConfig]:
        rows = self.session.execute(select(RiskRuleORM)).scalars().all()
        return [self._to_domain(r) for r in rows]

    def get(self, rule_id: str) -> Optional[RiskRuleConfig]:
        row = self.session.execute(
            select(RiskRuleORM).where(RiskRuleORM.rule_id == rule_id)
        ).scalar_one_or_none()
        return self._to_domain(row) if row else None

    def save(self, rule: RiskRuleConfig) -> None:
        self.session.merge(RiskRuleORM(
            rule_id=rule.rule_id, rule_type=rule.rule_type, scope=rule.scope,
            threshold=rule.threshold, action_on_breach=rule.action_on_breach,
            enabled=rule.enabled, description=rule.description, updated_at=rule.updated_at,
        ))

    def delete(self, rule_id: str) -> bool:
        row = self.session.execute(
            select(RiskRuleORM).where(RiskRuleORM.rule_id == rule_id)
        ).scalar_one_or_none()
        if row is None:
            return False
        self.session.delete(row)
        return True

    @staticmethod
    def _to_domain(row: RiskRuleORM) -> RiskRuleConfig:
        return RiskRuleConfig(
            rule_id=row.rule_id, rule_type=row.rule_type, scope=row.scope,
            threshold=row.threshold, action_on_breach=row.action_on_breach,
            enabled=row.enabled, description=row.description, updated_at=row.updated_at,
        )


class RiskEventRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, event: RiskEvent) -> None:
        self.session.merge(RiskEventORM(
            event_id=event.event_id, rule_id=event.rule_id, symbol=event.symbol,
            severity=event.severity, message=event.message, decision=event.decision,
            details=event.details, created_at=event.created_at,
        ))

    def list_recent(self, limit: int = 50) -> list[RiskEvent]:
        rows = self.session.execute(
            select(RiskEventORM).order_by(desc(RiskEventORM.created_at)).limit(limit)
        ).scalars().all()
        return [RiskEvent(
            event_id=r.event_id, rule_id=r.rule_id, symbol=r.symbol,
            severity=r.severity, message=r.message, decision=r.decision,
            details=dict(r.details or {}), created_at=r.created_at,
        ) for r in rows]


class NewsRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def article_exists(self, content_hash: str) -> bool:
        row = self.session.execute(
            select(NewsArticleORM).where(NewsArticleORM.content_hash == content_hash)
        ).scalar_one_or_none()
        return row is not None

    def save_article(self, article: NewsArticleRecord) -> None:
        self.session.merge(NewsArticleORM(
            article_id=article.article_id,
            source=article.source,
            title=article.title,
            published_at=article.published_at,
            url=article.url,
            content_hash=article.content_hash,
            raw_text=article.raw_text,
            symbols=article.symbols,
            created_at=article.created_at,
        ))

    def save_event(self, event: NewsEventRecord) -> None:
        self.session.merge(NewsEventORM(
            event_id=event.event_id,
            article_id=event.article_id,
            event_type=event.event_type,
            sentiment_score=event.sentiment_score,
            urgency_score=event.urgency_score,
            relevance_score=event.relevance_score,
            summary=event.summary,
            llm_reasoning_version=event.llm_reasoning_version,
            created_at=event.created_at,
        ))

    def list_articles(self, symbol: Optional[str] = None,
                      limit: int = 20) -> list[NewsArticleRecord]:
        # Order in DB; if symbol filter is requested we cannot push it down
        # (JSON column), so fetch a wider window and post-filter, then limit.
        fetch_limit = limit if symbol is None else max(limit * 10, 200)
        q = (
            select(NewsArticleORM)
            .order_by(desc(NewsArticleORM.published_at))
            .limit(fetch_limit)
        )
        rows = self.session.execute(q).scalars().all()
        results: list[NewsArticleRecord] = []
        for r in rows:
            syms = list(r.symbols or [])
            if symbol and symbol not in syms:
                continue
            results.append(NewsArticleRecord(
                article_id=r.article_id, source=r.source, title=r.title,
                published_at=r.published_at, url=r.url, content_hash=r.content_hash,
                raw_text=r.raw_text, symbols=syms, created_at=r.created_at,
            ))
            if len(results) >= limit:
                break
        return results

    def list_events_for_symbol(self, symbol: str, limit: int = 20) -> list[NewsEventRecord]:
        articles = self.session.execute(
            select(NewsArticleORM).where(
                NewsArticleORM.symbols.contains(symbol)  # type: ignore[arg-type]
            )
        ).scalars().all()
        article_ids = [a.article_id for a in articles]
        if not article_ids:
            return []
        rows = self.session.execute(
            select(NewsEventORM)
            .where(NewsEventORM.article_id.in_(article_ids))
            .order_by(desc(NewsEventORM.created_at))
            .limit(limit)
        ).scalars().all()
        return [NewsEventRecord(
            event_id=r.event_id, article_id=r.article_id, event_type=r.event_type,
            sentiment_score=r.sentiment_score, urgency_score=r.urgency_score,
            relevance_score=r.relevance_score, summary=r.summary,
            llm_reasoning_version=r.llm_reasoning_version, created_at=r.created_at,
        ) for r in rows]


class SignalRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, snap: SignalSnapshot) -> None:
        self.session.merge(SignalSnapshotORM(
            signal_id=snap.signal_id, symbol=snap.symbol, as_of_time=snap.as_of_time,
            signal_type=snap.signal_type, raw_score=snap.raw_score,
            confidence=snap.confidence, components=snap.components,
            expected_horizon=snap.expected_horizon, model_version=snap.model_version,
        ))

    def list_latest_per_symbol(self) -> list[SignalSnapshot]:
        from sqlalchemy import func
        sub = (
            select(SignalSnapshotORM.symbol,
                   func.max(SignalSnapshotORM.as_of_time).label("max_time"))
            .group_by(SignalSnapshotORM.symbol)
            .subquery()
        )
        rows = self.session.execute(
            select(SignalSnapshotORM).join(
                sub,
                (SignalSnapshotORM.symbol == sub.c.symbol) &
                (SignalSnapshotORM.as_of_time == sub.c.max_time),
            )
        ).scalars().all()
        return [SignalSnapshot(
            signal_id=r.signal_id, symbol=r.symbol, as_of_time=r.as_of_time,
            signal_type=r.signal_type, raw_score=r.raw_score, confidence=r.confidence,
            components=dict(r.components or {}), expected_horizon=r.expected_horizon,
            model_version=r.model_version,
        ) for r in rows]


class AuditLogRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, log: AuditLog) -> None:
        self.session.add(AuditLogORM(
            log_id=log.log_id, action=log.action, actor=log.actor,
            resource_type=log.resource_type, resource_id=log.resource_id,
            details=log.details, created_at=log.created_at,
        ))

    def list_recent(self, limit: int = 100, action: Optional[str] = None) -> list[AuditLog]:
        q = select(AuditLogORM).order_by(desc(AuditLogORM.created_at)).limit(limit)
        if action:
            q = q.where(AuditLogORM.action == action)
        rows = self.session.execute(q).scalars().all()
        return [AuditLog(
            log_id=r.log_id, action=r.action, actor=r.actor,
            resource_type=r.resource_type, resource_id=r.resource_id,
            details=dict(r.details or {}), created_at=r.created_at,
        ) for r in rows]



# ---------------------------------------------------------------------------
# Research tracing repositories (Design Doc §5.3.8 / §5.3.9)
# ---------------------------------------------------------------------------

class FactorSnapshotRepository:
    """Persist versioned feature values for trace-back."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def save_batch(
        self,
        symbol: str,
        as_of_time: datetime,
        factors: dict[str, float],
        feature_set_version: str = "v1",
        data_source: Optional[str] = None,
    ) -> int:
        """Insert a batch of (factor_name, value) pairs for a symbol."""
        n = 0
        for name, value in factors.items():
            if value is None:
                continue
            self.session.merge(FactorSnapshotORM(
                symbol=symbol,
                as_of_time=as_of_time,
                factor_name=name,
                factor_value=float(value),
                feature_set_version=feature_set_version,
                data_source=data_source,
                created_at=_utc_now(),
            ))
            n += 1
        return n

    def list_for_symbol(
        self,
        symbol: str,
        feature_set_version: Optional[str] = None,
        limit: int = 200,
    ) -> list[dict]:
        q = select(FactorSnapshotORM).where(FactorSnapshotORM.symbol == symbol)
        if feature_set_version:
            q = q.where(FactorSnapshotORM.feature_set_version == feature_set_version)
        q = q.order_by(desc(FactorSnapshotORM.as_of_time)).limit(limit)
        return [
            {
                "symbol": r.symbol,
                "as_of_time": r.as_of_time,
                "factor_name": r.factor_name,
                "factor_value": r.factor_value,
                "feature_set_version": r.feature_set_version,
                "data_source": r.data_source,
            }
            for r in self.session.execute(q).scalars().all()
        ]


class ModelRunRepository:
    """Record every model train / inference / backtest run."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def save(
        self,
        run_id: str,
        model_name: str,
        model_version: str,
        run_type: str,
        started_at: datetime,
        finished_at: Optional[datetime] = None,
        train_window_start=None,
        train_window_end=None,
        score_metrics: Optional[str] = None,
        params: Optional[str] = None,
        artifact_uri: Optional[str] = None,
        status: str = "success",
        error_message: Optional[str] = None,
    ) -> None:
        self.session.merge(ModelRunORM(
            run_id=run_id,
            model_name=model_name,
            model_version=model_version,
            run_type=run_type,
            train_window_start=train_window_start,
            train_window_end=train_window_end,
            score_metrics=score_metrics,
            params=params,
            artifact_uri=artifact_uri,
            status=status,
            error_message=error_message,
            started_at=started_at,
            finished_at=finished_at,
        ))

    def list_recent(self, limit: int = 50, model_name: Optional[str] = None) -> list[dict]:
        q = select(ModelRunORM).order_by(desc(ModelRunORM.started_at)).limit(limit)
        if model_name:
            q = q.where(ModelRunORM.model_name == model_name)
        return [
            {
                "run_id": r.run_id, "model_name": r.model_name,
                "model_version": r.model_version, "run_type": r.run_type,
                "train_window_start": r.train_window_start,
                "train_window_end": r.train_window_end,
                "score_metrics": r.score_metrics, "params": r.params,
                "artifact_uri": r.artifact_uri, "status": r.status,
                "error_message": r.error_message,
                "started_at": r.started_at, "finished_at": r.finished_at,
            }
            for r in self.session.execute(q).scalars().all()
        ]
