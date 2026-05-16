"""Market data skills — 使用新版 market_service 模块"""
from __future__ import annotations

from libs.agents.skills import Skill, SkillRegistry


def register_market_skills(reg: SkillRegistry) -> None:
    from apps.api.app.services import market_service

    def _get_quote(symbol: str) -> dict:
        q = market_service.get_single_quote(symbol)
        if not q:
            return {"error": f"no quote for {symbol}"}
        return q

    def _get_bars(symbol: str, days: int = 60) -> dict:
        bars = market_service.get_kline(symbol, period="daily", count=days)
        return {
            "symbol": symbol,
            "bars": bars,
            "count": len(bars),
        }

    def _list_universe(max_count: int = 50, exclude_st: bool = True) -> list[dict]:
        """搜索股票宇宙（简化版，返回涨幅榜前N只）"""
        hot = market_service.get_hot_stocks(top_n=max_count)
        return hot

    reg.register_many([
        Skill(
            name="list_universe",
            description="列出当前活跃股票（涨幅榜），返回代码、名称、价格、涨跌幅。",
            parameters={
                "type": "object",
                "properties": {
                    "max_count": {"type": "integer", "default": 50},
                    "exclude_st": {"type": "boolean", "default": True},
                },
            },
            handler=_list_universe,
            category="market",
        ),
        Skill(
            name="get_realtime_quote",
            description="获取某只股票的实时报价（最新价、涨跌幅、开高低收、成交额等）。",
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
            description="获取某只股票最近 N 天的日 K 线数据（open/high/low/close/volume/涨跌幅）。",
            parameters={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "days": {"type": "integer", "default": 60, "description": "回溯天数 (20-250)"},
                },
                "required": ["symbol"],
            },
            handler=_get_bars,
            category="market",
        ),
    ])
