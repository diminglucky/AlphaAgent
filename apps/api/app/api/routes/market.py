"""行情路由"""
from fastapi import APIRouter, Depends, Query

from apps.api.app.core.auth import get_current_user
from apps.api.app.services import market_service

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/quote/{symbol}")
def get_quote(symbol: str, _: object = Depends(get_current_user)):
    q = market_service.get_single_quote(symbol)
    if not q:
        return {"error": "获取行情失败", "symbol": symbol}
    return q


@router.get("/quotes")
def get_quotes(
    symbols: str = Query(..., description="逗号分隔的股票代码"),
    _: object = Depends(get_current_user),
):
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    return market_service.get_realtime_quotes(symbol_list)


@router.get("/kline/{symbol}")
def get_kline(
    symbol: str,
    period: str = Query("daily", description="daily/weekly/monthly"),
    count: int = Query(120, ge=20, le=500),
    _: object = Depends(get_current_user),
):
    return market_service.get_kline(symbol, period=period, count=count)


@router.get("/search")
def search(keyword: str = Query(..., min_length=1), _: object = Depends(get_current_user)):
    return market_service.search_stocks(keyword)


@router.get("/news/{symbol}")
def get_news(symbol: str, count: int = Query(10, ge=1, le=30), _: object = Depends(get_current_user)):
    return market_service.get_stock_news(symbol, count=count)


@router.get("/hot")
def get_hot(top_n: int = Query(50, ge=5, le=5000), _: object = Depends(get_current_user)):
    """涨幅榜（同时包含全量数据，前端自行排序）"""
    return market_service.get_hot_stocks(top_n=top_n)


@router.get("/cache-status")
def cache_status(_: object = Depends(get_current_user)):
    """返回行情缓存状态"""
    from apps.api.app.services.market_service import get_all_quotes_snapshot
    all_q = get_all_quotes_snapshot()
    provider = getattr(market_service, "_provider_name", lambda: "")()
    is_mock = provider == "mock"
    min_ready = 1 if is_mock else 1000
    return {
        "total": len(all_q),
        "ready": len(all_q) >= min_ready,
        "provider": provider,
        "mock": is_mock,
        "min_ready": min_ready,
        "real_time": not is_mock,
        "live_trading_safe": not is_mock,
    }


@router.get("/losers")
def get_losers(top_n: int = Query(15, ge=5, le=50), _: object = Depends(get_current_user)):
    """跌幅榜"""
    from apps.api.app.services.market_service import get_all_quotes_snapshot
    all_q = get_all_quotes_snapshot()
    losers = sorted(
        [q for q in all_q if q.get("change_pct", 0) < 0],
        key=lambda x: x["change_pct"]
    )[:top_n]
    return losers


@router.get("/active")
def get_most_active(top_n: int = Query(15, ge=5, le=50), _: object = Depends(get_current_user)):
    """成交额榜"""
    from apps.api.app.services.market_service import get_all_quotes_snapshot
    all_q = get_all_quotes_snapshot()
    active = sorted(
        [q for q in all_q if q.get("turnover", 0) > 0],
        key=lambda x: x.get("turnover", 0),
        reverse=True
    )[:top_n]
    return active
