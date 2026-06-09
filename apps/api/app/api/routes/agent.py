"""Agent 分析路由 — 使用 SuperAnalystAgent 进行深度分析"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.app.core.auth import get_current_user, require_admin, require_trader
from apps.api.app.db.session import get_db
from apps.api.app.db.models import WatchlistORM, AnalysisCacheORM
from apps.api.app.services import market_service, alert_service

log = logging.getLogger("quant.agent.route")
router = APIRouter(prefix="/agent", tags=["agent"])


def _run_super_analyst(symbol: str, name: str, db: Session) -> dict:
    """运行 SuperAnalystAgent，返回结构化分析结果。"""
    try:
        from libs.agents.super_analyst import SuperAnalystAgent
        agent = SuperAnalystAgent()
        run = agent.run(
            goal=f"深度分析 {symbol} {name}，给出完整的投资建议报告",
            context={"db": db, "symbol": symbol},
        )
        result = run.final_answer or {}
        if not isinstance(result, dict):
            result = {"summary": str(result)}

        # 补充元数据
        result.setdefault("symbol", symbol)
        result.setdefault("name", name)
        result.setdefault("llm_powered", run.llm_powered)
        result["agent_run_id"] = run.run_id
        result["agent_status"] = run.status
        result["agent_tool_calls"] = run.tool_calls_made
        result["agent_duration_ms"] = round(run.duration_ms, 1)

        # 从工具调用结果里补充 current_price（LLM 有时不回填）
        if not result.get("current_price"):
            for step in run.steps:
                if step.role == "tool_result" and isinstance(step.content, dict):
                    out = step.content.get("output", {})
                    if isinstance(out, dict):
                        price = out.get("price") or out.get("last_price") or out.get("current_close") or out.get("current")
                        if price and float(price) > 0:
                            result["current_price"] = float(price)
                            break
        return result

    except Exception as e:
        log.warning("SuperAnalystAgent failed for %s: %s", symbol, e, exc_info=True)
        # 回退到简单 LLM 分析
        from apps.api.app.services import llm_service
        quote = market_service.get_single_quote(symbol) or {}
        kline = market_service.get_kline(symbol, count=60)
        news = market_service.get_stock_news(symbol, count=8)
        return llm_service.analyze_stock(
            symbol=symbol, name=name, quote=quote, kline=kline, news=news,
        )


@router.post("/analyze/{symbol}")
async def analyze_stock(
    symbol: str,
    _: object = Depends(require_trader),
    db: Session = Depends(get_db),
):
    """深度分析单只股票（SuperAnalystAgent）— 在线程池执行避免阻塞"""
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    # 先获取股票名称（快速）
    quote = market_service.get_single_quote(symbol) or {}
    name = quote.get("name", symbol)

    def _run():
        return _run_super_analyst(symbol, name, db)

    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = await loop.run_in_executor(pool, _run)

    # 缓存结果（更新 updated_at，且若是新创建会写入 created_at）
    from datetime import datetime, timezone
    now_dt = datetime.now(timezone.utc).replace(tzinfo=None)
    cache = db.query(AnalysisCacheORM).filter(AnalysisCacheORM.symbol == symbol).first()
    if cache:
        cache.result = result
        cache.name = name
        cache.updated_at = now_dt
    else:
        cache = AnalysisCacheORM(symbol=symbol, name=name, result=result, updated_at=now_dt)
        db.add(cache)

    # BUY 信号 → 飞书提醒
    if result.get("action") == "BUY":
        try:
            alert_service.create_agent_alert(db, result)
        except Exception as e:
            log.warning("create_agent_alert failed: %s", e)

    db.commit()
    return result


@router.post("/scan")
def scan_watchlist(_: object = Depends(require_trader), db: Session = Depends(get_db)):
    """扫描全部自选股，逐一深度分析"""
    items = db.query(WatchlistORM).order_by(WatchlistORM.sort_order).all()
    if not items:
        return {"results": [], "message": "自选股为空，请先添加股票"}

    results = []
    for item in items:
        try:
            result = _run_super_analyst(item.symbol, item.name or item.symbol, db)
            results.append(result)

            # 缓存
            from datetime import datetime as _dt, timezone as _tz
            _now = _dt.now(_tz.utc).replace(tzinfo=None)
            cache = db.query(AnalysisCacheORM).filter(AnalysisCacheORM.symbol == item.symbol).first()
            if cache:
                cache.result = result
                cache.updated_at = _now
            else:
                db.add(AnalysisCacheORM(
                    symbol=item.symbol,
                    name=item.name or item.symbol,
                    result=result,
                    updated_at=_now,
                ))

            if result.get("action") == "BUY":
                try:
                    alert_service.create_agent_alert(db, result)
                except Exception:
                    pass

        except Exception as e:
            log.warning("scan %s failed: %s", item.symbol, e)

    db.commit()

    # 按 confidence 降序，BUY/WATCH 优先
    action_order = {"BUY": 0, "WATCH": 1, "HOLD": 2, "SELL": 3}
    results.sort(key=lambda x: (action_order.get(x.get("action", "HOLD"), 2), -x.get("confidence", 0)))

    return {"results": results, "scanned": len(results)}


@router.get("/cache")
def get_cached_analyses(
    _: object = Depends(get_current_user),
    db: Session = Depends(get_db),
    max_age_hours: int = 24,
):
    """返回所有分析缓存。max_age_hours 控制返回的缓存最大年龄（默认 24 小时）。"""
    from datetime import datetime, timezone, timedelta
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=max_age_hours)
    caches = db.query(AnalysisCacheORM).filter(
        AnalysisCacheORM.updated_at >= cutoff
    ).order_by(AnalysisCacheORM.updated_at.desc()).all()
    return [
        {
            "symbol": c.symbol,
            "name": c.name,
            "result": c.result,
            "updated_at": c.updated_at.isoformat(),
            "age_hours": round((datetime.now(timezone.utc).replace(tzinfo=None) - c.updated_at).total_seconds() / 3600, 1),
        }
        for c in caches
    ]


@router.get("/cache/{symbol}")
def get_cached_analysis(symbol: str, _: object = Depends(get_current_user), db: Session = Depends(get_db)):
    cache = db.query(AnalysisCacheORM).filter(AnalysisCacheORM.symbol == symbol).first()
    if not cache:
        return {"symbol": symbol, "result": None}
    from datetime import datetime, timezone
    age_hours = (datetime.now(timezone.utc).replace(tzinfo=None) - cache.updated_at).total_seconds() / 3600
    return {
        "symbol": symbol,
        "name": cache.name,
        "result": cache.result,
        "updated_at": cache.updated_at.isoformat(),
        "age_hours": round(age_hours, 1),
        "is_stale": age_hours > 6,  # 超过 6 小时视为过期，前端可提示用户重新分析
    }


@router.delete("/cache")
def clear_analysis_cache(
    _: object = Depends(require_admin),
    db: Session = Depends(get_db),
    symbol: str | None = None,
):
    """清除分析缓存：传 symbol 清除单只，不传清除全部"""
    if symbol:
        db.query(AnalysisCacheORM).filter(AnalysisCacheORM.symbol == symbol).delete()
    else:
        db.query(AnalysisCacheORM).delete()
    db.commit()
    return {"ok": True}
