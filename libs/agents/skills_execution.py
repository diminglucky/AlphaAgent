"""Execution skills — preview / draft / record decisions.

NOTE: place_order is exposed but only callable when the agent is invoked
with `allow_execution=True`. Otherwise it returns a dry-run preview.
"""

from __future__ import annotations

from libs.agents.skills import Skill, SkillRegistry


def register_execution_skills(reg: SkillRegistry) -> None:

    def _preview_order(
        symbol: str, side: str, price: float, quantity: int, _db=None,
    ) -> dict:
        if _db is None:
            return {"error": "no db"}
        from apps.api.app.services.risk_service import RiskService
        from apps.api.app.db.repositories import PortfolioRepository
        from libs.execution.a_share_rules import check_order, OrderSide
        from apps.api.app.services.market_service import MarketService

        try:
            bars = MarketService().get_bars(symbol, freq="1d")
            prev_close = bars[-2].close if len(bars) >= 2 else 0
        except Exception as exc:
            return {"error": str(exc)}

        a_rule = check_order(
            symbol=symbol, side=OrderSide(side), quantity=quantity, price=price,
            prev_close=prev_close, available_quantity=quantity,
            is_st="ST" in symbol,
        )

        port = PortfolioRepository(_db)
        positions = port.list_positions()
        summary = port.get_summary()
        total = summary.total_asset if summary else 1_000_000
        allowed, events = RiskService(_db).evaluate_order(
            symbol=symbol, side=side, price=price, quantity=quantity,
            positions=positions, portfolio_total_value=total,
        )
        notional = price * quantity

        return {
            "preview": True,
            "symbol": symbol,
            "side": side,
            "price": price,
            "quantity": quantity,
            "notional": round(notional, 2),
            "estimated_commission": round(notional * 0.0003, 2),
            "a_share_rules": {"ok": a_rule.ok, "code": a_rule.code, "message": a_rule.message},
            "risk_engine": {
                "allowed": allowed,
                "events": [
                    {"decision": e.decision, "severity": e.severity, "message": e.message}
                    for e in events
                ],
            },
            "would_succeed": a_rule.ok and allowed,
        }

    def _record_recommendation(
        symbol: str, action: str, confidence: float, reason: str,
        risk_flags: list[str] = None, _db=None,
    ) -> dict:
        """Persist an agent-derived recommendation into the recommendations table."""
        if _db is None:
            return {"error": "no db"}
        import uuid
        from datetime import datetime
        from apps.api.app.db.repositories import RecommendationRepository
        from libs.quant_core.models import Recommendation
        rec = Recommendation(
            recommendation_id=f"rec-agent-{symbol}-{int(datetime.now().timestamp())}",
            symbol=symbol,
            action=action.upper(),
            target_weight=0.0,
            confidence=float(confidence),
            time_horizon="day_trade",
            reason_summary=reason[:200],
            risk_flags=list(risk_flags or []),
            status="READY",
            created_at=datetime.now(),
        )
        RecommendationRepository(_db).save(rec)
        return {"ok": True, "recommendation_id": rec.recommendation_id}

    reg.register_many([
        Skill(
            name="preview_order",
            description="模拟一笔订单（不真实下单），返回风控/A股规则评估、预估手续费、是否会成功。Agent 在给建议前可先 preview。",
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
            handler=_preview_order,
            category="execution",
            requires_db=True,
        ),
        Skill(
            name="record_recommendation",
            description="把 Agent 的最终结论作为正式 Recommendation 写入数据库（用户可查看历史）。Agent 在结束推理后调用。",
            parameters={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "action": {"type": "string", "enum": ["BUY", "SELL", "HOLD"]},
                    "confidence": {"type": "number", "description": "0~1"},
                    "reason": {"type": "string"},
                    "risk_flags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["symbol", "action", "confidence", "reason"],
            },
            handler=_record_recommendation,
            category="execution",
            requires_db=True,
        ),
    ])
