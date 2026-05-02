"""Risk management service: rule CRUD + event recording."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from apps.api.app.db.repositories import AuditLogRepository, RiskEventRepository, RiskRuleRepository
from libs.quant_core.enums import AuditAction
from libs.quant_core.models import AuditLog, RiskEvent, RiskRuleConfig


def _now() -> datetime:
    return datetime.now(tz=timezone.utc).replace(tzinfo=None)


class RiskService:
    def __init__(self, session: Session) -> None:
        self._rules = RiskRuleRepository(session)
        self._events = RiskEventRepository(session)
        self._audit = AuditLogRepository(session)

    def list_rules(self) -> list[RiskRuleConfig]:
        return self._rules.list_all()

    def get_rule(self, rule_id: str) -> RiskRuleConfig:
        rule = self._rules.get(rule_id)
        if rule is None:
            raise ValueError(f"Risk rule not found: {rule_id}")
        return rule

    def create_rule(self, rule_type: str, scope: str, threshold: float,
                    action_on_breach: str, description: str, actor: str) -> RiskRuleConfig:
        now = _now()
        rule = RiskRuleConfig(
            rule_id=str(uuid.uuid4()),
            rule_type=rule_type,
            scope=scope,
            threshold=threshold,
            action_on_breach=action_on_breach,
            enabled=True,
            description=description,
            updated_at=now,
        )
        self._rules.save(rule)
        self._audit.save(AuditLog(
            log_id=str(uuid.uuid4()),
            action=AuditAction.RISK_RULE_CHANGED.value,
            actor=actor,
            resource_type="risk_rule",
            resource_id=rule.rule_id,
            details={"op": "create", "rule_type": rule_type, "threshold": threshold},
            created_at=now,
        ))
        return rule

    def update_rule(self, rule_id: str, threshold: float | None,
                    enabled: bool | None, description: str | None,
                    actor: str) -> RiskRuleConfig:
        existing = self.get_rule(rule_id)
        now = _now()
        updated = RiskRuleConfig(
            rule_id=existing.rule_id,
            rule_type=existing.rule_type,
            scope=existing.scope,
            threshold=threshold if threshold is not None else existing.threshold,
            action_on_breach=existing.action_on_breach,
            enabled=enabled if enabled is not None else existing.enabled,
            description=description if description is not None else existing.description,
            updated_at=now,
        )
        self._rules.save(updated)
        self._audit.save(AuditLog(
            log_id=str(uuid.uuid4()),
            action=AuditAction.RISK_RULE_CHANGED.value,
            actor=actor,
            resource_type="risk_rule",
            resource_id=rule_id,
            details={"op": "update", "threshold": threshold, "enabled": enabled},
            created_at=now,
        ))
        return updated

    def delete_rule(self, rule_id: str, actor: str) -> None:
        deleted = self._rules.delete(rule_id)
        if not deleted:
            raise ValueError(f"Risk rule not found: {rule_id}")
        now = _now()
        self._audit.save(AuditLog(
            log_id=str(uuid.uuid4()),
            action=AuditAction.RISK_RULE_CHANGED.value,
            actor=actor,
            resource_type="risk_rule",
            resource_id=rule_id,
            details={"op": "delete"},
            created_at=now,
        ))

    def record_event(self, rule_id: str, symbol: str | None, severity: str,
                     message: str, decision: str, details: dict) -> RiskEvent:
        event = RiskEvent(
            event_id=str(uuid.uuid4()),
            rule_id=rule_id,
            symbol=symbol,
            severity=severity,
            message=message,
            decision=decision,
            details=details,
            created_at=_now(),
        )
        self._events.save(event)
        return event

    def list_recent_events(self, limit: int = 50) -> list[RiskEvent]:
        return self._events.list_recent(limit=limit)

    # ------------------------------------------------------------------
    # Pre-trade evaluation
    # ------------------------------------------------------------------

    def evaluate_order(
        self,
        symbol: str,
        side: str,
        price: float,
        quantity: int,
        positions: list,
        portfolio_total_value: float,
    ) -> tuple[bool, list[RiskEvent]]:
        """
        Run all enabled rules against a proposed order.

        Returns: (allowed, events)
            - allowed: False if any rule with action_on_breach=BLOCK fires
            - events:  every RiskEvent created (always persisted for audit)
        """
        rules = [r for r in self._rules.list_all() if r.enabled]
        events: list[RiskEvent] = []
        allowed = True

        order_value = price * quantity

        for rule in rules:
            triggered = False
            triggered_value: float = 0.0

            if rule.rule_type == "single_stock_max_weight":
                # Compute hypothetical post-trade weight
                cur_pos = next((p for p in positions if p.symbol == symbol), None)
                cur_value = cur_pos.market_value if cur_pos else 0.0
                if side.upper() == "BUY":
                    new_value = cur_value + order_value
                else:
                    new_value = max(0.0, cur_value - order_value)
                total = max(portfolio_total_value, 1e-9)
                weight = new_value / total
                triggered_value = weight
                triggered = weight > rule.threshold

            elif rule.rule_type == "max_position_value":
                if side.upper() == "BUY":
                    triggered_value = order_value
                    triggered = order_value > rule.threshold

            elif rule.rule_type == "max_daily_loss":
                # Placeholder — requires P&L tracking; skip if no info
                continue

            elif rule.rule_type == "industry_max_weight":
                # Lacking industry mapping in this scope; skip silently
                continue

            else:
                continue

            if not triggered:
                continue

            severity = "HIGH" if rule.action_on_breach == "BLOCK" else "MEDIUM"
            event = self.record_event(
                rule_id=rule.rule_id,
                symbol=symbol,
                severity=severity,
                message=(
                    f"{rule.rule_type} 触发（值 {triggered_value:.4f} "
                    f"vs 阈值 {rule.threshold}）"
                ),
                decision=rule.action_on_breach,
                details={
                    "rule_type": rule.rule_type,
                    "triggered_value": triggered_value,
                    "threshold": rule.threshold,
                    "side": side,
                    "price": price,
                    "quantity": quantity,
                },
            )
            events.append(event)
            if rule.action_on_breach == "BLOCK":
                allowed = False

        return allowed, events
