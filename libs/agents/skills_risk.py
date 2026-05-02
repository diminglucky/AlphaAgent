"""Risk-management skills."""

from __future__ import annotations

from libs.agents.skills import Skill, SkillRegistry


def register_risk_skills(reg: SkillRegistry) -> None:

    def _list_rules(_db=None) -> dict:
        if _db is None:
            return {"error": "no db"}
        from apps.api.app.services.risk_service import RiskService
        rules = RiskService(_db).list_rules()
        return {
            "rules": [
                {"rule_id": r.rule_id, "rule_type": r.rule_type, "scope": r.scope,
                 "threshold": r.threshold, "action_on_breach": r.action_on_breach,
                 "enabled": r.enabled, "description": r.description}
                for r in rules
            ]
        }

    def _evaluate_proposed_order(
        symbol: str, side: str, price: float, quantity: int, _db=None,
    ) -> dict:
        """Run the risk engine evaluator without placing an order."""
        if _db is None:
            return {"error": "no db"}
        from apps.api.app.services.risk_service import RiskService
        from apps.api.app.db.repositories import PortfolioRepository
        port = PortfolioRepository(_db)
        positions = port.list_positions()
        summary = port.get_summary()
        total = summary.total_asset if summary else (
            sum(p.market_value for p in positions) + 1
        )
        allowed, events = RiskService(_db).evaluate_order(
            symbol=symbol, side=side, price=price, quantity=quantity,
            positions=positions, portfolio_total_value=total,
        )
        return {
            "allowed": allowed,
            "events": [
                {"rule_id": e.rule_id, "decision": e.decision, "severity": e.severity,
                 "message": e.message}
                for e in events
            ],
            "n_events": len(events),
        }

    def _check_a_share_rules(
        symbol: str, side: str, price: float, quantity: int,
    ) -> dict:
        """T+1 / 100-shares / price-limit check (without DB risk rules)."""
        from libs.execution.a_share_rules import check_order, OrderSide
        from apps.api.app.services.market_service import MarketService
        try:
            bars = MarketService().get_bars(symbol, freq="1d")
        except Exception as exc:
            return {"error": str(exc)}
        prev_close = bars[-2].close if len(bars) >= 2 else (bars[-1].close if bars else 0)
        is_st = "*ST" in symbol or "ST" in symbol  # simple proxy
        result = check_order(
            symbol=symbol, side=OrderSide(side), quantity=quantity, price=price,
            prev_close=prev_close, available_quantity=quantity, is_st=is_st,
        )
        return {"ok": result.ok, "code": result.code, "message": result.message}

    reg.register_many([
        Skill(
            name="list_risk_rules",
            description="列出所有风控规则（单票上限、行业上限、最大日亏损等）。Agent 用于了解组合约束。",
            parameters={"type": "object", "properties": {}},
            handler=_list_rules,
            category="risk",
            requires_db=True,
        ),
        Skill(
            name="evaluate_proposed_order",
            description="风控引擎预评估某笔拟下订单，但不真正下单。返回是否会被拦截及触发的规则。Agent 在建议下单前调用。",
            parameters={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "side": {"type": "string", "enum": ["BUY", "SELL"]},
                    "price": {"type": "number"},
                    "quantity": {"type": "integer"},
                },
                "required": ["symbol", "side", "price", "quantity"],
            },
            handler=_evaluate_proposed_order,
            category="risk",
            requires_db=True,
        ),
        Skill(
            name="check_a_share_rules",
            description="检查 A 股交易规则：T+1、100 股倍数、涨跌停板。Agent 在下单前确认合规。",
            parameters={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "side": {"type": "string", "enum": ["BUY", "SELL"]},
                    "price": {"type": "number"},
                    "quantity": {"type": "integer"},
                },
                "required": ["symbol", "side", "price", "quantity"],
            },
            handler=_check_a_share_rules,
            category="risk",
        ),
    ])
