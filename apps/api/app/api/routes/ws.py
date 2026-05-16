"""WebSocket — 实时行情推送（3秒）+ 提醒检查"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from apps.api.app.core.config import get_settings
from apps.api.app.db.session import session_scope

log = logging.getLogger("quant.ws")
router = APIRouter(tags=["websocket"])


# ---------------------------------------------------------------------------
# 连接管理
# ---------------------------------------------------------------------------

class ConnectionManager:
    def __init__(self):
        self._clients: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, topic: str, ws: WebSocket):
        await ws.accept()
        async with self._lock:
            self._clients.setdefault(topic, set()).add(ws)

    async def disconnect(self, topic: str, ws: WebSocket):
        async with self._lock:
            self._clients.get(topic, set()).discard(ws)

    async def broadcast(self, topic: str, data: dict):
        async with self._lock:
            clients = list(self._clients.get(topic, set()))
        dead = []
        msg = json.dumps(data, ensure_ascii=False, default=str)
        for ws in clients:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._clients.get(topic, set()).discard(ws)

    def count(self, topic: Optional[str] = None) -> int:
        if topic:
            return len(self._clients.get(topic, set()))
        return sum(len(s) for s in self._clients.values())


manager = ConnectionManager()
_quote_task: Optional[asyncio.Task] = None


# ---------------------------------------------------------------------------
# 行情推送循环（3秒）
# ---------------------------------------------------------------------------

async def _quote_loop():
    from apps.api.app.db.models import WatchlistORM, PositionORM
    from apps.api.app.services import market_service, alert_service

    settings = get_settings()

    while True:
        if manager.count() == 0:
            await asyncio.sleep(settings.quote_interval)
            continue

        try:
            with session_scope() as db:
                wl_symbols = [r.symbol for r in db.query(WatchlistORM).all()]
                pos_symbols = [r.symbol for r in db.query(PositionORM).all()]

            symbols = list(set(wl_symbols + pos_symbols))
            if not symbols:
                await asyncio.sleep(settings.quote_interval)
                continue

            # 注册精准跟踪，从缓存读（毫秒级）
            market_service.register_symbols(symbols)
            quotes = market_service.get_realtime_quotes(symbols)

            if quotes:
                await manager.broadcast("quotes", {
                    "type": "quotes",
                    "data": quotes,
                    "timestamp": datetime.now().isoformat(),
                })

                # 检查提醒
                def _check():
                    with session_scope() as db:
                        p = alert_service.check_price_alerts(db, quotes)
                        q = alert_service.check_position_alerts(db, quotes)
                        return p + q

                triggered = await asyncio.to_thread(_check)
                if triggered:
                    await manager.broadcast("alerts", {
                        "type": "alerts",
                        "data": triggered,
                        "timestamp": datetime.now().isoformat(),
                    })

        except Exception as e:
            log.warning("quote_loop error: %s", e)

        await asyncio.sleep(settings.quote_interval)


async def ensure_running():
    global _quote_task
    if _quote_task is None or _quote_task.done():
        _quote_task = asyncio.create_task(_quote_loop())


# ---------------------------------------------------------------------------
# WebSocket 端点
# ---------------------------------------------------------------------------

@router.websocket("/ws/quotes")
async def ws_quotes(ws: WebSocket):
    await manager.connect("quotes", ws)
    await ensure_running()
    try:
        while True:
            await ws.receive_text()
    except (WebSocketDisconnect, Exception):
        await manager.disconnect("quotes", ws)


@router.websocket("/ws/alerts")
async def ws_alerts(ws: WebSocket):
    await manager.connect("alerts", ws)
    await ensure_running()
    try:
        while True:
            await ws.receive_text()
    except (WebSocketDisconnect, Exception):
        await manager.disconnect("alerts", ws)


@router.get("/ws/status")
async def ws_status():
    return {
        "quotes_clients": manager.count("quotes"),
        "alerts_clients": manager.count("alerts"),
        "loop_running": _quote_task is not None and not _quote_task.done(),
    }
