"""Market data skills."""

from __future__ import annotations

from datetime import date, timedelta
from libs.agents.skills import Skill, SkillRegistry


def register_market_skills(reg: SkillRegistry) -> None:
    from apps.api.app.services.market_service import MarketService
    market = MarketService()

    def _list_universe(max_count: int = 50, exclude_st: bool = True) -> list[dict]:
        instruments = market.list_instruments()
        out = []
        for i in instruments:
            if exclude_st and i.is_st:
                continue
            out.append({
                "symbol": i.symbol, "name": i.name, "industry": i.industry,
                "is_st": i.is_st, "status": i.status,
            })
            if len(out) >= max_count:
                break
        return out

    def _get_quote(symbol: str) -> dict:
        quotes = market.get_realtime_quotes([symbol])
        if not quotes:
            return {"error": f"no quote for {symbol}"}
        q = quotes[0]
        return {
            "symbol": q.symbol, "last_price": q.last_price, "bid1": q.bid1,
            "ask1": q.ask1, "volume": q.volume, "pct_change": q.pct_change,
            "limit_up": q.limit_up, "limit_down": q.limit_down,
            "quote_time": q.quote_time.isoformat() if q.quote_time else None,
        }

    def _get_bars(symbol: str, days: int = 30) -> dict:
        bars = market.get_bars(symbol=symbol, freq="1d")
        bars = bars[-days:] if len(bars) > days else bars
        return {
            "symbol": symbol,
            "bars": [
                {"date": str(b.trade_date), "open": b.open, "high": b.high,
                 "low": b.low, "close": b.close, "volume": b.volume,
                 "turnover_rate": b.turnover_rate}
                for b in bars
            ],
            "count": len(bars),
        }

    reg.register_many([
        Skill(
            name="list_universe",
            description="列出当前可投资的股票宇宙（按市场全量）。返回代码、名称、行业、是否ST。用于 Agent 探索可投资范围。",
            parameters={
                "type": "object",
                "properties": {
                    "max_count": {"type": "integer", "default": 50, "description": "返回的最大数量"},
                    "exclude_st": {"type": "boolean", "default": True, "description": "是否排除 ST 股票"},
                },
            },
            handler=_list_universe,
            category="market",
        ),
        Skill(
            name="get_realtime_quote",
            description="获取某只股票的实时报价（最新价、涨跌、买一/卖一价、涨停板）。",
            parameters={
                "type": "object",
                "properties": {"symbol": {"type": "string", "description": "如 600519.SH"}},
                "required": ["symbol"],
            },
            handler=_get_quote,
            category="market",
        ),
        Skill(
            name="get_daily_bars",
            description="获取某只股票最近 N 天的日 K 线数据（open/high/low/close/volume/换手率）。Agent 可基于此判断趋势、形态、放量等。",
            parameters={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "days": {"type": "integer", "default": 30, "description": "回溯天数 (5-250)"},
                },
                "required": ["symbol"],
            },
            handler=_get_bars,
            category="market",
        ),
    ])
