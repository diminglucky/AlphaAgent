"""Market scanner + position monitor REST endpoints."""

from __future__ import annotations

from dataclasses import asdict
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from apps.api.app.db.session import get_db
from apps.api.app.services.market_scanner import MarketScanner
from apps.api.app.services.position_monitor import PositionMonitor

router = APIRouter(prefix="/scanner", tags=["scanner"])


# ---------------------------------------------------------------------------
# In-memory cache populated by background loop in ws.py
# ---------------------------------------------------------------------------

_last_scan: dict | None = None
_last_monitor: dict | None = None


def set_last_scan(payload: dict) -> None:
    global _last_scan
    _last_scan = payload


def set_last_monitor(payload: dict) -> None:
    global _last_monitor
    _last_monitor = payload


def get_last_scan() -> dict | None:
    return _last_scan


def get_last_monitor() -> dict | None:
    return _last_monitor


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/top-picks")
def top_picks(
    fresh: bool = Query(False, description="If true, run a synchronous scan"),
    top_n: int = 10,
    max_symbols: int = 500,
    db: Session = Depends(get_db),
):
    """Return latest scanner output: top BUY + top SELL candidates."""
    if fresh or _last_scan is None:
        report = MarketScanner().run(top_n=top_n, max_symbols=max_symbols)
        payload = _scan_to_dict(report)
        # Also invoke MarketScout agent for the reasoning layer
        try:
            from libs.agents.market_scout import MarketScoutAgent
            run = MarketScoutAgent().run(
                "为我找出今日 3 只最有买入潜力的 A 股", context={"db": db},
            )
            payload["agent"] = {
                "agent": run.agent_name, "run_id": run.run_id,
                "status": run.status, "llm_powered": run.llm_powered,
                "tool_calls_made": run.tool_calls_made,
                "duration_ms": round(run.duration_ms, 1),
                "final_answer": run.final_answer,
            }
        except Exception as exc:  # noqa: BLE001
            payload["agent"] = {"status": "failed", "error": str(exc)}
        set_last_scan(payload)
        return payload
    return _last_scan


@router.get("/sell-warnings")
def sell_warnings(
    fresh: bool = Query(False, description="If true, run a synchronous monitor pass"),
    db: Session = Depends(get_db),
):
    """Return active sell-warning alerts for held positions."""
    if fresh or _last_monitor is None:
        report = PositionMonitor(db).run()
        payload = _monitor_to_dict(report)
        try:
            from libs.agents.portfolio_guardian import PortfolioGuardianAgent
            run = PortfolioGuardianAgent().run(
                "诊断当前所有持仓，对每只给出 HOLD/REDUCE/SELL 建议。",
                context={"db": db},
            )
            payload["agent"] = {
                "agent": run.agent_name, "run_id": run.run_id,
                "status": run.status, "llm_powered": run.llm_powered,
                "tool_calls_made": run.tool_calls_made,
                "duration_ms": round(run.duration_ms, 1),
                "verdicts": (run.final_answer or {}).get("verdicts", []) if isinstance(run.final_answer, dict) else [],
            }
        except Exception as exc:  # noqa: BLE001
            payload["agent"] = {"status": "failed", "error": str(exc)}
        set_last_monitor(payload)
        return payload
    return _last_monitor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scan_to_dict(report) -> dict:
    return {
        "generated_at": report.generated_at.isoformat(),
        "universe_size": report.universe_size,
        "successful": report.successful,
        "errors": report.errors,
        "top_buy": [asdict(c) for c in report.top_buy],
        "top_sell": [asdict(c) for c in report.top_sell],
    }


def _monitor_to_dict(report) -> dict:
    return {
        "generated_at": report.generated_at.isoformat(),
        "positions_checked": report.positions_checked,
        "alerts": [
            {
                **asdict(a),
                "triggered_at": a.triggered_at.isoformat(),
            }
            for a in report.alerts
        ],
    }
