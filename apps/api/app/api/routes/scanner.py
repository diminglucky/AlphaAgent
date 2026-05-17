"""大盘潜力股扫描器路由"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from fastapi import APIRouter, Body, Query
from pydantic import BaseModel

from apps.api.app.services import scanner_service

router = APIRouter(prefix="/scanner", tags=["scanner"])


class ScanReq(BaseModel):
    top_n: int = 30
    min_score: int = 50
    candidate_pool: int = 200
    use_cache: bool = True
    required_strategies: Optional[list[str]] = None  # 必须命中的策略名列表


@router.post("/scan")
async def scan_potential(req: Optional[ScanReq] = Body(default=None)):
    """扫描全市场，返回有上涨潜力的股票"""
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
            ),
        )
    return result


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
