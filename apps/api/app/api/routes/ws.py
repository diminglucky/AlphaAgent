"""WebSocket endpoints + background real-time analysis loops.

Three topics broadcast over WebSocket:
- /ws/quotes  — live realtime quote ticks (every 3s)
- /ws/alerts  — proactive alerts (stop-loss / take-profit / breakout)
- /ws/advisor — full advisor report when it changes (every 60s)

A single background task aggregates work to minimise overhead.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from dataclasses import asdict
from datetime import datetime, time as dtime
from typing import Any, Optional

log = logging.getLogger("quant.ws")

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from apps.api.app.db.session import session_scope
from apps.api.app.services.market_service import MarketService
from apps.api.app.services.portfolio_service import PortfolioService

router = APIRouter(tags=["websocket"])


# ---------------------------------------------------------------------------
# Connection manager
# ---------------------------------------------------------------------------

class ConnectionManager:
    """Manages WebSocket clients per topic."""

    def __init__(self) -> None:
        self._active: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, topic: str, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._active.setdefault(topic, set()).add(ws)

    async def disconnect(self, topic: str, ws: WebSocket) -> None:
        async with self._lock:
            conns = self._active.get(topic)
            if conns and ws in conns:
                conns.remove(ws)

    async def broadcast(self, topic: str, payload: dict) -> None:
        async with self._lock:
            conns = list(self._active.get(topic, set()))

        dead: list[WebSocket] = []
        message = json.dumps(payload, default=str, ensure_ascii=False)
        for ws in conns:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._active.get(topic, set()).discard(ws)

    def count(self, topic: Optional[str] = None) -> int:
        if topic:
            return len(self._active.get(topic, set()))
        return sum(len(s) for s in self._active.values())


manager = ConnectionManager()


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

WATCHED_SYMBOLS: list[str] = [
    "600519.SH", "000001.SZ", "300750.SZ", "000858.SZ",
    "601318.SH", "600036.SH", "601166.SH", "000333.SZ",
]

QUOTE_INTERVAL_SEC = 3.0
ADVISOR_INTERVAL_SEC = 60.0

# Alert thresholds
STOP_LOSS_RATIO = -0.08
TAKE_PROFIT_RATIO = 0.20
LARGE_MOVE_PCT = 3.0      # > 3% intraday → emit BIG_MOVE alert

# Per-(symbol, alert_type) cooldown so the same alert won't spam.
ALERT_COOLDOWN_SEC = 300      # 5 minutes
# Optional quiet hours (no alerts pushed). Empty → always on.
QUIET_HOURS_START: Optional[dtime] = None     # e.g. dtime(22, 0)
QUIET_HOURS_END: Optional[dtime] = None       # e.g. dtime(8, 0)


def _is_quiet_now() -> bool:
    if QUIET_HOURS_START is None or QUIET_HOURS_END is None:
        return False
    now = datetime.now().time()
    if QUIET_HOURS_START <= QUIET_HOURS_END:
        return QUIET_HOURS_START <= now <= QUIET_HOURS_END
    # Wraps midnight
    return now >= QUIET_HOURS_START or now <= QUIET_HOURS_END


# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------

_feed_task: Optional[asyncio.Task] = None
_advisor_task: Optional[asyncio.Task] = None
_scanner_task: Optional[asyncio.Task] = None
_monitor_task: Optional[asyncio.Task] = None
_market_service: Optional[MarketService] = None
_last_advisor_report: dict[str, Any] = {}
# (symbol, alert_type) -> last-emitted monotonic timestamp
_alert_last_sent: dict[tuple[str, str], float] = {}


def _get_market_service() -> MarketService:
    global _market_service
    if _market_service is None:
        _market_service = MarketService()
    return _market_service


# ---------------------------------------------------------------------------
# Quote feed loop
# ---------------------------------------------------------------------------

def _resolve_watched_symbols() -> list[str]:
    """Watchlist ∪ held positions, falling back to the static defaults."""
    try:
        from apps.api.app.core.config import get_settings
        from apps.api.app.services.watchlist_service import WatchlistService
        account_id = get_settings().default_account_id
        with session_scope() as s:
            wl = WatchlistService(s).list_symbols(account_id)
        held = {p.symbol for p in PortfolioService().get_positions()}
        return list({*wl, *held}) or list(WATCHED_SYMBOLS)
    except Exception as exc:  # noqa: BLE001
        log.warning("resolve-watchlist failed: %s", exc)
        return list(WATCHED_SYMBOLS)


async def _quote_feed_loop() -> None:
    """Broadcast realtime quotes + push alerts when thresholds are crossed."""
    last_prices: dict[str, float] = {}

    while True:
        # Save CPU when no subscribers
        if manager.count() == 0:
            await asyncio.sleep(QUOTE_INTERVAL_SEC)
            continue

        symbols = _resolve_watched_symbols()
        try:
            market = _get_market_service()
            quotes = market.get_realtime_quotes(symbols)
        except Exception as exc:
            log.warning("quote-feed: failed to fetch quotes: %s", exc)
            await asyncio.sleep(QUOTE_INTERVAL_SEC)
            continue

        items: list[dict] = []
        for q in quotes:
            base = q.last_price or last_prices.get(q.symbol) or 0.0
            pct = q.pct_change / 100 if q.pct_change else 0.0
            prev_close = base / (1 + pct) if pct != 0 else base
            # Random walk ±0.3 % for visible motion in mock mode
            noise = random.uniform(-0.003, 0.003) * base
            new_price = round(max(0.01, base + noise), 2)
            change = new_price - prev_close
            change_pct = (change / prev_close * 100) if prev_close else 0.0
            last_prices[q.symbol] = new_price

            items.append({
                "symbol": q.symbol,
                "last_price": new_price,
                "prev_close": round(prev_close, 2),
                "change": round(change, 2),
                "change_pct": round(change_pct, 2),
                "bid1": q.bid1,
                "ask1": q.ask1,
                "volume": q.volume,
                "turnover": q.turnover,
                "limit_up": q.limit_up,
                "limit_down": q.limit_down,
                "timestamp": datetime.now().isoformat(),
            })

        await manager.broadcast("quotes", {
            "type": "quotes",
            "data": items,
            "timestamp": datetime.now().isoformat(),
        })

        # Check alerts against holdings
        await _check_and_emit_alerts(items)

        await asyncio.sleep(QUOTE_INTERVAL_SEC)


async def _check_and_emit_alerts(quote_items: list[dict]) -> None:
    """For each holding, compare live price vs cost basis and emit alerts."""
    try:
        portfolio = PortfolioService()
        positions = portfolio.get_positions()
    except Exception:
        return

    if not positions:
        return

    pos_by_symbol = {p.symbol: p for p in positions}
    quote_by_symbol = {q["symbol"]: q for q in quote_items}

    alerts: list[dict] = []

    for symbol, pos in pos_by_symbol.items():
        q = quote_by_symbol.get(symbol)
        if not q or pos.avg_cost <= 0:
            continue

        live_price = q["last_price"]
        pnl_ratio = (live_price - pos.avg_cost) / pos.avg_cost
        change_pct = q["change_pct"]

        alert_key: Optional[str] = None
        level: str = "info"
        title: str = ""
        body: str = ""

        if pnl_ratio <= STOP_LOSS_RATIO:
            alert_key = "STOP_LOSS"
            level = "error"
            title = f"⚠ {symbol} 触发止损"
            body = f"浮亏 {pnl_ratio*100:.2f}%，已突破 -8% 阈值，建议立即减仓"
        elif pnl_ratio >= TAKE_PROFIT_RATIO:
            alert_key = "TAKE_PROFIT"
            level = "success"
            title = f"✓ {symbol} 达到止盈位"
            body = f"浮盈 {pnl_ratio*100:.2f}%，可考虑分批止盈"
        elif abs(change_pct) >= LARGE_MOVE_PCT:
            direction = "急涨" if change_pct > 0 else "急跌"
            alert_key = f"BIG_MOVE_{direction}"
            level = "warning"
            title = f"⚡ {symbol} {direction} {abs(change_pct):.2f}%"
            body = f"短时波动较大，现价 ¥{live_price:.2f}（成本 ¥{pos.avg_cost:.2f}）"

        if not alert_key:
            continue

        # Cooldown: same (symbol, alert_type) only fires every ALERT_COOLDOWN_SEC
        import time as _t
        now_mono = _t.monotonic()
        last = _alert_last_sent.get((symbol, alert_key), 0.0)
        if now_mono - last < ALERT_COOLDOWN_SEC:
            continue

        if _is_quiet_now():
            continue

        _alert_last_sent[(symbol, alert_key)] = now_mono
        alerts.append({
            "id": f"{symbol}-{alert_key}-{int(datetime.now().timestamp())}",
            "level": level,
            "symbol": symbol,
            "alert_type": alert_key,
            "title": title,
            "body": body,
            "live_price": live_price,
            "avg_cost": pos.avg_cost,
            "pnl_ratio": round(pnl_ratio, 4),
            "change_pct": change_pct,
            "timestamp": datetime.now().isoformat(),
        })

    if alerts:
        await manager.broadcast("alerts", {
            "type": "alerts",
            "data": alerts,
            "timestamp": datetime.now().isoformat(),
        })
        # Fan-out to external channels (webhook / email) — non-blocking
        try:
            from apps.api.app.services.notify_service import get_notifier
            notifier = get_notifier()
            for a in alerts:
                # Run in thread to avoid blocking the event loop on SMTP/HTTP
                await asyncio.to_thread(notifier.send, a["title"], a["body"], a["level"])
        except Exception as exc:  # noqa: BLE001
            log.warning("notify fan-out failed: %s", exc)


# ---------------------------------------------------------------------------
# Advisor refresh loop
# ---------------------------------------------------------------------------

async def _advisor_refresh_loop() -> None:
    """Re-run the multi-agent advisor every ADVISOR_INTERVAL_SEC seconds.

    Also triggers AutoSignalService every SIGNAL_INTERVAL_SEC so that the
    `signals` and `recommendations` tables stay populated automatically.
    """
    global _last_advisor_report

    # Lazy imports to avoid cycles at startup
    from apps.api.app.services.advisor_service import AdvisorService
    from apps.api.app.services.auto_signal_service import AutoSignalService

    SIGNAL_INTERVAL_SEC = 300       # 5 min
    last_signal_run = 0.0
    import time as _t

    while True:
        # ---- Signals + Recommendations (less frequent) ------------------
        now_mono = _t.monotonic()
        if now_mono - last_signal_run >= SIGNAL_INTERVAL_SEC:
            last_signal_run = now_mono
            try:
                with session_scope() as session:
                    res = AutoSignalService(session).run_once()
                log.info(
                    "auto_signal: scanned=%d signals=%d recs=%d errors=%d",
                    res.symbols_scanned, res.signals_saved, res.recommendations_saved, len(res.errors),
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("auto_signal failed: %s", exc, exc_info=True)

        # ---- Advisor (every minute) ------------------------------------
        try:
            with session_scope() as session:
                report = AdvisorService(session).build()
            payload = {
                "generated_at": report.generated_at.isoformat(),
                "summary": report.summary,
                "items": [asdict(it) for it in report.items],
            }
            _last_advisor_report = payload

            if manager.count("advisor") > 0:
                await manager.broadcast("advisor", {
                    "type": "advisor",
                    "data": payload,
                })
        except Exception as exc:  # noqa: BLE001
            # Don't kill the loop on transient errors
            log.warning("advisor-loop: %s", exc, exc_info=True)

        await asyncio.sleep(ADVISOR_INTERVAL_SEC)


def get_cached_advisor_report() -> dict[str, Any]:
    """Return the latest advisor payload. Empty dict if not yet generated."""
    return _last_advisor_report


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

async def _scanner_loop() -> None:
    """Run MarketScoutAgent + classical scanner every SCANNER_INTERVAL_SEC.

    Both run side-by-side: classical scanner for breadth (Top-N over hundreds
    of symbols, fast deterministic), Agent for depth (chooses tools dynamically,
    LLM-aware when configured). Output is unified into one payload.
    """
    SCANNER_INTERVAL_SEC = 120  # 2 min
    from apps.api.app.services.market_scanner import MarketScanner
    from apps.api.app.api.routes.scanner import set_last_scan, _scan_to_dict
    from apps.api.app.db.session import session_scope
    from libs.agents.market_scout import MarketScoutAgent

    scout = MarketScoutAgent()

    def _run_both():
        report = MarketScanner().run(top_n=10, max_symbols=200)
        payload = _scan_to_dict(report)
        # Agent run for additional reasoning layer
        try:
            with session_scope() as session:
                run = scout.run(
                    "为我找出今日 3 只最有买入潜力的 A 股",
                    context={"db": session},
                )
            payload["agent"] = {
                "agent": run.agent_name,
                "run_id": run.run_id,
                "status": run.status,
                "llm_powered": run.llm_powered,
                "tool_calls_made": run.tool_calls_made,
                "duration_ms": round(run.duration_ms, 1),
                "final_answer": run.final_answer,
            }
        except Exception as exc:  # noqa: BLE001
            log.debug("scout-agent in loop failed: %s", exc)
            payload["agent"] = {"status": "failed", "error": str(exc)}
        return payload

    while True:
        try:
            payload = await asyncio.to_thread(_run_both)
            set_last_scan(payload)
            if manager.count("picks") > 0:
                await manager.broadcast("picks", {"type": "scan", "data": payload})
            log.info("scanner+scout: success=%s tool_calls=%s",
                     payload.get("agent", {}).get("status"),
                     payload.get("agent", {}).get("tool_calls_made"))
        except Exception as exc:  # noqa: BLE001
            log.warning("scanner-loop: %s", exc, exc_info=True)
        await asyncio.sleep(SCANNER_INTERVAL_SEC)


async def _monitor_loop() -> None:
    """Run position monitor every MONITOR_INTERVAL_SEC and push sell alerts."""
    MONITOR_INTERVAL_SEC = 30  # 30s
    from apps.api.app.services.position_monitor import PositionMonitor
    from apps.api.app.api.routes.scanner import set_last_monitor, _monitor_to_dict
    from apps.api.app.db.session import session_scope

    last_alert_keys: set = set()  # dedup by (symbol, rule)

    from libs.agents.portfolio_guardian import PortfolioGuardianAgent
    guardian = PortfolioGuardianAgent()

    while True:
        try:
            with session_scope() as session:
                report = PositionMonitor(session).run()
                # Agent reasoning pass — runs every MONITOR_INTERVAL_SEC * 4 (=2min)
                # to keep cost low.
                agent_meta = None
                if int(asyncio.get_event_loop().time()) % 120 < 30:
                    try:
                        run = guardian.run(
                            "诊断当前所有持仓，对每只给出 HOLD/REDUCE/SELL 建议。",
                            context={"db": session},
                        )
                        agent_meta = {
                            "agent": run.agent_name,
                            "run_id": run.run_id,
                            "status": run.status,
                            "llm_powered": run.llm_powered,
                            "tool_calls_made": run.tool_calls_made,
                            "duration_ms": round(run.duration_ms, 1),
                            "verdicts": (run.final_answer or {}).get("verdicts", []) if isinstance(run.final_answer, dict) else [],
                        }
                    except Exception as exc:  # noqa: BLE001
                        log.debug("guardian-agent in loop failed: %s", exc)
            payload = _monitor_to_dict(report)
            if agent_meta:
                payload["agent"] = agent_meta
            set_last_monitor(payload)

            # Push only NEW alerts (not seen since last run) to avoid spam
            current_keys = {(a.symbol, a.rule) for a in report.alerts}
            new_keys = current_keys - last_alert_keys
            last_alert_keys = current_keys

            if new_keys and manager.count("picks") > 0:
                new_alerts = [a for a in report.alerts if (a.symbol, a.rule) in new_keys]
                await manager.broadcast("picks", {
                    "type": "sell_alerts",
                    "data": {"alerts": [_monitor_to_dict(_FakeReport([a])) for a in new_alerts]},
                })

            # Also fan-out CRITICAL alerts to standard /ws/alerts channel
            for a in report.alerts:
                if a.urgency == "CRITICAL" and (a.symbol, a.rule) in new_keys:
                    if manager.count("alerts") > 0:
                        await manager.broadcast("alerts", {
                            "type": "alert",
                            "data": {
                                "level": "danger",
                                "title": f"⚠️ {a.name} 卖出预警",
                                "body": a.message,
                                "symbol": a.symbol,
                                "rule": a.rule,
                                "ts": a.triggered_at.isoformat(),
                            },
                        })

            if report.alerts:
                log.info("monitor: %d positions, %d alerts (%d new)",
                         report.positions_checked, len(report.alerts), len(new_keys))
        except Exception as exc:  # noqa: BLE001
            log.warning("monitor-loop: %s", exc, exc_info=True)
        await asyncio.sleep(MONITOR_INTERVAL_SEC)


class _FakeReport:
    """Tiny shim so we can reuse _monitor_to_dict for a single-alert payload."""
    def __init__(self, alerts):
        self.generated_at = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        self.positions_checked = 0
        self.alerts = alerts


async def ensure_background_running() -> None:
    """Start all background loops if not already running."""
    global _feed_task, _advisor_task, _scanner_task, _monitor_task
    if _feed_task is None or _feed_task.done():
        _feed_task = asyncio.create_task(_quote_feed_loop())
    if _advisor_task is None or _advisor_task.done():
        _advisor_task = asyncio.create_task(_advisor_refresh_loop())
    if _scanner_task is None or _scanner_task.done():
        _scanner_task = asyncio.create_task(_scanner_loop())
    if _monitor_task is None or _monitor_task.done():
        _monitor_task = asyncio.create_task(_monitor_loop())


# ---------------------------------------------------------------------------
# WebSocket endpoints
# ---------------------------------------------------------------------------

@router.websocket("/ws/quotes")
async def ws_quotes(ws: WebSocket) -> None:
    await manager.connect("quotes", ws)
    await ensure_background_running()
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect("quotes", ws)
    except Exception:
        await manager.disconnect("quotes", ws)


@router.websocket("/ws/alerts")
async def ws_alerts(ws: WebSocket) -> None:
    await manager.connect("alerts", ws)
    await ensure_background_running()
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect("alerts", ws)
    except Exception:
        await manager.disconnect("alerts", ws)


@router.websocket("/ws/advisor")
async def ws_advisor(ws: WebSocket) -> None:
    await manager.connect("advisor", ws)
    await ensure_background_running()
    # Send the latest cached report immediately on connection
    if _last_advisor_report:
        try:
            await ws.send_text(json.dumps(
                {"type": "advisor", "data": _last_advisor_report},
                default=str, ensure_ascii=False,
            ))
        except Exception:
            pass
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect("advisor", ws)
    except Exception:
        await manager.disconnect("advisor", ws)


@router.websocket("/ws/picks")
async def ws_picks(ws: WebSocket) -> None:
    """Stream market scanner top-picks + position monitor sell-warnings."""
    await manager.connect("picks", ws)
    await ensure_background_running()

    # Send latest cached snapshots immediately
    from apps.api.app.api.routes.scanner import get_last_scan, get_last_monitor
    try:
        scan = get_last_scan()
        if scan:
            await ws.send_text(json.dumps({"type": "scan", "data": scan}, default=str, ensure_ascii=False))
        monitor = get_last_monitor()
        if monitor:
            await ws.send_text(json.dumps({"type": "monitor", "data": monitor}, default=str, ensure_ascii=False))
    except Exception:
        pass

    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect("picks", ws)
    except Exception:
        await manager.disconnect("picks", ws)


@router.get("/ws/status")
async def ws_status() -> dict:
    return {
        "topics": {topic: manager.count(topic) for topic in ("quotes", "alerts", "advisor", "picks")},
        "feed_running": _feed_task is not None and not _feed_task.done(),
        "advisor_running": _advisor_task is not None and not _advisor_task.done(),
        "scanner_running": _scanner_task is not None and not _scanner_task.done(),
        "monitor_running": _monitor_task is not None and not _monitor_task.done(),
        "advisor_cached": bool(_last_advisor_report),
    }
