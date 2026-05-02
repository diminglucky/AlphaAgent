"""Portfolio & holdings skills."""

from __future__ import annotations

from libs.agents.skills import Skill, SkillRegistry


def register_portfolio_skills(reg: SkillRegistry) -> None:

    def _get_portfolio(_db=None) -> dict:
        if _db is None:
            return {"error": "no db"}
        from apps.api.app.db.repositories import PortfolioRepository
        repo = PortfolioRepository(_db)
        summary = repo.get_summary()
        positions = repo.list_positions()
        return {
            "summary": {
                "total_asset": summary.total_asset if summary else 0,
                "cash": summary.cash if summary else 0,
                "market_value": summary.market_value if summary else 0,
                "daily_pnl": summary.daily_pnl if summary else 0,
                "total_pnl": summary.total_pnl if summary else 0,
            } if summary else None,
            "positions": [
                {"symbol": p.symbol, "quantity": p.quantity,
                 "available_quantity": p.available_quantity,
                 "avg_cost": p.avg_cost, "market_value": p.market_value,
                 "unrealized_pnl": p.unrealized_pnl}
                for p in positions
            ],
            "n_holdings": len(positions),
        }

    def _calc_position_health(symbol: str, _db=None) -> dict:
        """Health snapshot for one held position."""
        if _db is None:
            return {"error": "no db"}
        from apps.api.app.db.repositories import PortfolioRepository
        from apps.api.app.services.market_service import MarketService
        repo = PortfolioRepository(_db)
        positions = repo.list_positions()
        pos = next((p for p in positions if p.symbol == symbol), None)
        if pos is None:
            return {"error": f"no position for {symbol}"}
        bars = MarketService().get_bars(symbol, freq="1d")
        if not bars:
            return {"error": "no bars"}
        last_price = bars[-1].close
        pnl_pct = (last_price - pos.avg_cost) / pos.avg_cost if pos.avg_cost else 0
        peak = max(b.high for b in bars[-30:]) if bars else last_price
        drawdown = (last_price - peak) / peak if peak else 0
        return {
            "symbol": symbol,
            "quantity": pos.quantity,
            "available_quantity": pos.available_quantity,
            "avg_cost": pos.avg_cost,
            "last_price": last_price,
            "unrealized_pnl": round(pos.unrealized_pnl, 2),
            "pnl_pct": round(pnl_pct, 4),
            "peak_30d": round(peak, 2),
            "drawdown_from_peak": round(drawdown, 4),
            "is_locked_t1": pos.available_quantity == 0,
        }

    def _calc_concentration(_db=None) -> dict:
        """Industry / single-name concentration analysis."""
        if _db is None:
            return {"error": "no db"}
        from apps.api.app.db.repositories import PortfolioRepository
        from apps.api.app.services.market_service import MarketService
        repo = PortfolioRepository(_db)
        summary = repo.get_summary()
        positions = repo.list_positions()
        total = summary.total_asset if summary else max(
            sum(p.market_value for p in positions) + 1, 1
        )
        instruments = {i.symbol: i for i in MarketService().list_instruments()}
        per_symbol = []
        per_industry: dict[str, float] = {}
        for p in positions:
            w = p.market_value / total if total else 0
            per_symbol.append({"symbol": p.symbol, "weight": round(w, 4)})
            ind = (instruments.get(p.symbol).industry if instruments.get(p.symbol) else "未知") or "未知"
            per_industry[ind] = per_industry.get(ind, 0) + w

        return {
            "total_asset": total,
            "n_holdings": len(positions),
            "single_name_max_weight": round(max((s["weight"] for s in per_symbol), default=0), 4),
            "industry_distribution": [
                {"industry": k, "weight": round(v, 4)}
                for k, v in sorted(per_industry.items(), key=lambda x: -x[1])
            ],
            "per_symbol": per_symbol,
        }

    reg.register_many([
        Skill(
            name="get_portfolio_overview",
            description="获取整体组合快照：总资产、现金、持仓市值、持仓列表。Agent 决策前先看持仓上下文。",
            parameters={"type": "object", "properties": {}},
            handler=_get_portfolio,
            category="portfolio",
            requires_db=True,
        ),
        Skill(
            name="check_position_health",
            description="评估某只持仓股的盈亏率、自高点回撤、T+1 锁定状态。Agent 判断是否需要止损/止盈。",
            parameters={
                "type": "object",
                "properties": {"symbol": {"type": "string"}},
                "required": ["symbol"],
            },
            handler=_calc_position_health,
            category="portfolio",
            requires_db=True,
        ),
        Skill(
            name="calc_concentration",
            description="计算组合集中度：单票最大权重、行业分布。Agent 用于判断加仓是否合理或需要分散。",
            parameters={"type": "object", "properties": {}},
            handler=_calc_concentration,
            category="portfolio",
            requires_db=True,
        ),
    ])
