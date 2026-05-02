"""Operational metrics endpoint (§7.1.2)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.app.db.models import (
    AuditLogORM,
    OrderORM,
    RecommendationORM,
    RiskEventORM,
    SignalSnapshotORM,
)
from apps.api.app.db.session import get_db
from libs.market_data.cache import cache_stats

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("")
def get_metrics(db: Session = Depends(get_db)):
    """Return platform-wide counters useful for dashboards / SLO tracking."""
    from apps.api.app.api.routes.ws import manager, _last_advisor_report

    counts = {
        "orders_total": db.execute(select(func.count(OrderORM.order_id))).scalar() or 0,
        "orders_pending": db.execute(
            select(func.count(OrderORM.order_id)).where(OrderORM.status == "PENDING")
        ).scalar() or 0,
        "orders_filled": db.execute(
            select(func.count(OrderORM.order_id)).where(OrderORM.status == "FILLED")
        ).scalar() or 0,
        "orders_cancelled": db.execute(
            select(func.count(OrderORM.order_id)).where(OrderORM.status == "CANCELLED")
        ).scalar() or 0,
        "signals_total": db.execute(select(func.count(SignalSnapshotORM.signal_id))).scalar() or 0,
        "recommendations_total": db.execute(select(func.count(RecommendationORM.recommendation_id))).scalar() or 0,
        "risk_events_total": db.execute(select(func.count(RiskEventORM.event_id))).scalar() or 0,
        "risk_events_blocked": db.execute(
            select(func.count(RiskEventORM.event_id)).where(RiskEventORM.decision == "BLOCK")
        ).scalar() or 0,
        "audit_logs_total": db.execute(select(func.count(AuditLogORM.log_id))).scalar() or 0,
    }

    return {
        "counters": counts,
        "websocket": {
            "quotes_subscribers": manager.count("quotes"),
            "alerts_subscribers": manager.count("alerts"),
            "advisor_subscribers": manager.count("advisor"),
        },
        "advisor_cache": {
            "available": _last_advisor_report is not None,
            "generated_at": _last_advisor_report["generated_at"] if _last_advisor_report else None,
        },
        "market_cache": cache_stats(),
        "kv_cache": _kv_cache_stats(),
    }


def _kv_cache_stats() -> dict:
    try:
        from libs.infra.cache import get_cache
        return get_cache().stats()
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Prometheus text exposition (Design Doc §10.3)
# ---------------------------------------------------------------------------

@router.get("/prom", response_class=PlainTextResponse, include_in_schema=False)
def get_metrics_prometheus(db: Session = Depends(get_db)) -> str:
    """Prometheus text exposition format. Scrape with `scrape_interval: 15s`."""
    from apps.api.app.api.routes.ws import manager, _last_advisor_report

    counts = {
        "quant_orders_total": db.execute(select(func.count(OrderORM.order_id))).scalar() or 0,
        "quant_orders_pending": db.execute(
            select(func.count(OrderORM.order_id)).where(OrderORM.status == "PENDING")
        ).scalar() or 0,
        "quant_orders_filled": db.execute(
            select(func.count(OrderORM.order_id)).where(OrderORM.status == "FILLED")
        ).scalar() or 0,
        "quant_orders_cancelled": db.execute(
            select(func.count(OrderORM.order_id)).where(OrderORM.status == "CANCELLED")
        ).scalar() or 0,
        "quant_signals_total": db.execute(select(func.count(SignalSnapshotORM.signal_id))).scalar() or 0,
        "quant_recommendations_total": db.execute(
            select(func.count(RecommendationORM.recommendation_id))
        ).scalar() or 0,
        "quant_risk_events_total": db.execute(
            select(func.count(RiskEventORM.event_id))
        ).scalar() or 0,
        "quant_risk_events_blocked": db.execute(
            select(func.count(RiskEventORM.event_id)).where(RiskEventORM.decision == "BLOCK")
        ).scalar() or 0,
        "quant_audit_logs_total": db.execute(
            select(func.count(AuditLogORM.log_id))
        ).scalar() or 0,
        "quant_ws_subscribers_quotes": manager.count("quotes"),
        "quant_ws_subscribers_alerts": manager.count("alerts"),
        "quant_ws_subscribers_advisor": manager.count("advisor"),
        "quant_advisor_cache_ready": 1 if _last_advisor_report is not None else 0,
    }

    # KV cache stats
    kv = _kv_cache_stats()
    if "hits" in kv:
        counts["quant_kv_cache_hits_total"] = kv["hits"]
        counts["quant_kv_cache_misses_total"] = kv["misses"]
        counts["quant_kv_cache_hit_rate"] = kv["hit_rate"]

    lines: list[str] = []
    for name, value in counts.items():
        lines.append(f"# HELP {name} {name.replace('_', ' ')}")
        lines.append(f"# TYPE {name} gauge")
        lines.append(f"{name} {value}")

    # Per-cache stats (labelled)
    market_cache = cache_stats()
    if market_cache:
        lines.append("# HELP quant_market_cache_size cached entries per function")
        lines.append("# TYPE quant_market_cache_size gauge")
        for fn_name, st in market_cache.items():
            label = fn_name.replace('"', '')
            lines.append(f'quant_market_cache_size{{fn="{label}"}} {st["size"]}')
            lines.append(f'quant_market_cache_hits{{fn="{label}"}} {st["hits"]}')
            lines.append(f'quant_market_cache_misses{{fn="{label}"}} {st["misses"]}')

    return "\n".join(lines) + "\n"
