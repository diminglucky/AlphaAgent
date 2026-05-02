from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache

from sqlalchemy.orm import Session

from apps.api.app.core.config import get_settings
from apps.api.app.db.base import Base
from apps.api.app.db.models import (
    InstrumentORM,
    PortfolioSnapshotORM,
    PositionORM,
    RecommendationExplanationORM,
    RecommendationORM,
    RiskRuleORM,
)
from apps.api.app.db.session import get_engine, session_scope
from apps.api.app.services.sample_data import (
    EXPLANATIONS,
    INSTRUMENTS,
    NOW,
    PORTFOLIO_SUMMARY,
    POSITIONS,
    RECOMMENDATIONS,
)


def create_schema() -> None:
    Base.metadata.create_all(bind=get_engine())


_DEFAULT_RISK_RULES = [
    {
        "rule_id": "single_stock_max_weight",
        "rule_type": "single_stock_max_weight",
        "scope": "symbol",
        "threshold": 0.30,
        "action_on_breach": "BLOCK",
        "enabled": True,
        "description": "单票权重不得超过30%",
    },
    {
        "rule_id": "industry_max_weight",
        "rule_type": "industry_max_weight",
        "scope": "industry",
        "threshold": 0.40,
        "action_on_breach": "WARN",
        "enabled": True,
        "description": "单行业权重不得超过40%",
    },
    {
        "rule_id": "daily_max_turnover",
        "rule_type": "daily_max_turnover",
        "scope": "portfolio",
        "threshold": 0.50,
        "action_on_breach": "BLOCK",
        "enabled": True,
        "description": "单日换手率不得超过50%",
    },
    {
        "rule_id": "single_order_cash_limit",
        "rule_type": "single_order_cash_limit",
        "scope": "order",
        "threshold": 0.25,
        "action_on_breach": "BLOCK",
        "enabled": True,
        "description": "单笔订单不得超过总资产25%",
    },
]


def seed_demo_data(session: Session) -> None:
    for instr in INSTRUMENTS:
        session.merge(InstrumentORM(
            symbol=instr.symbol,
            exchange=instr.exchange,
            name=instr.name,
            industry=instr.industry,
            list_date=instr.list_date.isoformat() if instr.list_date else None,
            delist_date=instr.delist_date.isoformat() if instr.delist_date else None,
            status=instr.status,
            is_st=instr.is_st,
            updated_at=NOW,
        ))

    for rule in _DEFAULT_RISK_RULES:
        session.merge(RiskRuleORM(
            rule_id=rule["rule_id"],
            rule_type=rule["rule_type"],
            scope=rule["scope"],
            threshold=rule["threshold"],
            action_on_breach=rule["action_on_breach"],
            enabled=rule["enabled"],
            description=rule["description"],
            updated_at=NOW,
        ))

    session.merge(
        PortfolioSnapshotORM(
            account_id=PORTFOLIO_SUMMARY.account_id,
            portfolio_name=PORTFOLIO_SUMMARY.portfolio_name,
            base_currency=PORTFOLIO_SUMMARY.base_currency,
            total_asset=PORTFOLIO_SUMMARY.total_asset,
            cash=PORTFOLIO_SUMMARY.cash,
            market_value=PORTFOLIO_SUMMARY.market_value,
            daily_pnl=PORTFOLIO_SUMMARY.daily_pnl,
            total_pnl=PORTFOLIO_SUMMARY.total_pnl,
            updated_at=PORTFOLIO_SUMMARY.updated_at,
        )
    )

    for item in POSITIONS:
        session.merge(
            PositionORM(
                position_id=item.position_id,
                account_id=item.account_id,
                symbol=item.symbol,
                quantity=item.quantity,
                available_quantity=item.available_quantity,
                avg_cost=item.avg_cost,
                market_value=item.market_value,
                unrealized_pnl=item.unrealized_pnl,
                realized_pnl=item.realized_pnl,
                updated_at=item.updated_at,
            )
        )

    for item in RECOMMENDATIONS:
        session.merge(
            RecommendationORM(
                recommendation_id=item.recommendation_id,
                symbol=item.symbol,
                action=item.action,
                target_weight=item.target_weight,
                confidence=item.confidence,
                time_horizon=item.time_horizon,
                reason_summary=item.reason_summary,
                risk_flags=item.risk_flags,
                status=item.status,
                created_at=item.created_at,
            )
        )

    explanation_updated_at = (
        NOW if isinstance(NOW, datetime)
        else datetime.now(timezone.utc).replace(tzinfo=None)
    )
    for symbol, payload in EXPLANATIONS.items():
        session.merge(
            RecommendationExplanationORM(
                symbol=symbol,
                summary=str(payload["summary"]),
                drivers=list(payload["drivers"]),
                risk_notes=list(payload["risk_notes"]),
                sources=list(payload["sources"]),
                updated_at=explanation_updated_at,
            )
        )


def bootstrap_database() -> None:
    create_schema()
    settings = get_settings()
    if not settings.seed_demo_data:
        return
    with session_scope() as session:
        seed_demo_data(session)


@lru_cache(maxsize=1)
def ensure_database_initialized() -> None:
    bootstrap_database()


def reset_bootstrap_cache() -> None:
    ensure_database_initialized.cache_clear()
