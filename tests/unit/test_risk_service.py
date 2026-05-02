"""Unit tests for RiskService."""

import pytest
from sqlalchemy.orm import Session

from apps.api.app.services.risk_service import RiskService


def _seed_rules(svc: RiskService) -> None:
    svc.create_rule("single_stock_max_weight", "symbol", 0.30, "BLOCK", "30% cap", actor="admin")
    svc.create_rule("industry_max_weight", "industry", 0.40, "WARN", "40% cap", actor="admin")


def test_create_rule(db_session: Session) -> None:
    svc = RiskService(db_session)
    rule = svc.create_rule("test_rule", "portfolio", 0.25, "BLOCK", "desc", actor="admin")
    assert rule.rule_id is not None
    assert rule.threshold == 0.25
    assert rule.enabled is True


def test_list_rules_returns_all(db_session: Session) -> None:
    svc = RiskService(db_session)
    _seed_rules(svc)
    rules = svc.list_rules()
    assert len(rules) == 2


def test_get_rule_found(db_session: Session) -> None:
    svc = RiskService(db_session)
    created = svc.create_rule("r1", "symbol", 0.20, "BLOCK", "", actor="admin")
    fetched = svc.get_rule(created.rule_id)
    assert fetched.rule_id == created.rule_id


def test_get_rule_not_found_raises(db_session: Session) -> None:
    svc = RiskService(db_session)
    with pytest.raises(ValueError, match="Risk rule not found"):
        svc.get_rule("nonexistent")


def test_update_rule_threshold(db_session: Session) -> None:
    svc = RiskService(db_session)
    rule = svc.create_rule("r2", "symbol", 0.25, "BLOCK", "", actor="admin")
    updated = svc.update_rule(rule.rule_id, threshold=0.15, enabled=None, description=None, actor="admin")
    assert updated.threshold == 0.15
    assert updated.enabled is True


def test_update_rule_disable(db_session: Session) -> None:
    svc = RiskService(db_session)
    rule = svc.create_rule("r3", "symbol", 0.25, "BLOCK", "", actor="admin")
    updated = svc.update_rule(rule.rule_id, threshold=None, enabled=False, description=None, actor="admin")
    assert updated.enabled is False


def test_update_rule_not_found_raises(db_session: Session) -> None:
    svc = RiskService(db_session)
    with pytest.raises(ValueError, match="Risk rule not found"):
        svc.update_rule("missing", threshold=0.1, enabled=None, description=None, actor="admin")


def test_delete_rule(db_session: Session) -> None:
    svc = RiskService(db_session)
    rule = svc.create_rule("r4", "symbol", 0.25, "BLOCK", "", actor="admin")
    svc.delete_rule(rule.rule_id, actor="admin")
    with pytest.raises(ValueError, match="Risk rule not found"):
        svc.get_rule(rule.rule_id)


def test_delete_rule_not_found_raises(db_session: Session) -> None:
    svc = RiskService(db_session)
    with pytest.raises(ValueError, match="Risk rule not found"):
        svc.delete_rule("nonexistent", actor="admin")


def test_record_and_list_events(db_session: Session) -> None:
    svc = RiskService(db_session)
    rule = svc.create_rule("r5", "symbol", 0.30, "BLOCK", "", actor="admin")
    svc.record_event(
        rule_id=rule.rule_id,
        symbol="600519.SH",
        severity="ERROR",
        message="weight exceeded",
        decision="BLOCK",
        details={"weight": 0.35},
    )
    events = svc.list_recent_events(limit=10)
    assert len(events) == 1
    assert events[0].symbol == "600519.SH"
    assert events[0].decision == "BLOCK"


def test_audit_log_written_on_create(db_session: Session) -> None:
    from apps.api.app.db.repositories import AuditLogRepository
    svc = RiskService(db_session)
    svc.create_rule("audit_rule", "symbol", 0.10, "WARN", "", actor="admin")
    db_session.flush()
    logs = AuditLogRepository(db_session).list_recent(limit=10)
    assert any(log.action == "RISK_RULE_CHANGED" for log in logs)
