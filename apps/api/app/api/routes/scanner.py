"""大盘潜力股扫描器路由（三层漏斗 + AI 终审）"""
from __future__ import annotations

import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from fastapi import APIRouter, Body, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from apps.api.app.services import scanner_service

log = logging.getLogger("quant.scanner.route")

router = APIRouter(prefix="/scanner", tags=["scanner"])


class ScanReq(BaseModel):
    top_n: int = 30
    min_score: int = 50
    candidate_pool: int = 120
    use_cache: bool = True
    required_strategies: Optional[list[str]] = None
    enable_fundamental: bool = True
    enable_llm: bool = True
    llm_top_n: int = 12


@router.post("/scan")
async def scan_potential(req: Optional[ScanReq] = Body(default=None)):
    """扫描全市场，返回有上涨潜力的股票（三层漏斗）"""
    if req is None:
        req = ScanReq()

    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = await loop.run_in_executor(
            pool,
            lambda: scanner_service.scan_potential_stocks(
                top_n=req.top_n,
                min_score=req.min_score,
                candidate_pool=req.candidate_pool,
                use_cache=req.use_cache,
                required_strategies=req.required_strategies,
                enable_fundamental=req.enable_fundamental,
                enable_llm=req.enable_llm,
                llm_top_n=req.llm_top_n,
            ),
        )
    return result


@router.websocket("/ws/scan")
async def ws_scan(ws: WebSocket):
    """带进度推送的扫描接口（实时显示三层漏斗进度）"""
    await ws.accept()
    try:
        # 客户端先发参数
        raw = await ws.receive_text()
        params = json.loads(raw or "{}")
        req = ScanReq(**params)

        loop = asyncio.get_event_loop()

        async def _send(event: str, data: dict):
            try:
                await ws.send_json({"event": event, "data": data})
            except Exception:
                pass

        progress_queue: asyncio.Queue = asyncio.Queue()

        def _progress(event: str, data: dict):
            # 在工作线程里调用，转给 event loop
            loop.call_soon_threadsafe(progress_queue.put_nowait, (event, data))

        async def _drain():
            while True:
                try:
                    event, data = await asyncio.wait_for(progress_queue.get(), timeout=1.0)
                    await _send(event, data)
                except asyncio.TimeoutError:
                    return

        # 启动后台扫描
        with ThreadPoolExecutor(max_workers=1) as pool:
            task = loop.run_in_executor(
                pool,
                lambda: scanner_service.scan_potential_stocks(
                    top_n=req.top_n,
                    min_score=req.min_score,
                    candidate_pool=req.candidate_pool,
                    use_cache=req.use_cache,
                    required_strategies=req.required_strategies,
                    enable_fundamental=req.enable_fundamental,
                    enable_llm=req.enable_llm,
                    llm_top_n=req.llm_top_n,
                    progress_callback=_progress,
                ),
            )

            # 边扫边推进度
            while not task.done():
                await _drain()
                await asyncio.sleep(0.2)

            await _drain()  # 取最后剩余的事件
            result = await task

        await _send("done", {"result": result})
    except WebSocketDisconnect:
        log.info("ws scan client disconnected")
    except Exception as e:
        log.warning("ws scan error: %s", e, exc_info=True)
        try:
            await ws.send_json({"event": "error", "data": {"message": str(e)}})
        except Exception:
            pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass


@router.get("/strategies")
def list_strategies():
    """返回所有可用的经典策略"""
    return scanner_service.get_strategy_list()


@router.get("/status")
def scanner_status():
    return {
        "cache_keys": list(scanner_service._scan_cache.keys()),
        "cached": bool(scanner_service._scan_cache),
    }


@router.delete("/cache")
def clear_scanner_cache():
    scanner_service.clear_cache()
    return {"ok": True, "message": "缓存已清除"}
