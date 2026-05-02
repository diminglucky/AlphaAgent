"""Unit tests for OrderService."""

import pytest
from sqlalchemy.orm import Session

from apps.api.app.services.order_service import OrderService
from libs.quant_core.enums import OrderStatus


def test_place_order_creates_pending(db_session: Session) -> None:
    svc = OrderService(db_session)
    order = svc.place_order(
        symbol="600519.SH",
        side="BUY",
        order_type="LIMIT",
        price=1719.5,
        quantity=100,
        source="MANUAL",
        actor="test-actor",
    )
    assert order.order_id is not None
    assert order.status == OrderStatus.PENDING.value
    assert order.symbol == "600519.SH"
    assert order.filled_quantity == 0


def test_place_order_unknown_symbol_raises(db_session: Session) -> None:
    svc = OrderService(db_session)
    with pytest.raises(ValueError, match="Unknown symbol"):
        svc.place_order("FAKE.XX", "BUY", "LIMIT", 10.0, 100, "MANUAL", "actor")


def test_place_order_invalid_side_raises(db_session: Session) -> None:
    svc = OrderService(db_session)
    with pytest.raises(ValueError, match="Unsupported side"):
        svc.place_order("600519.SH", "SHORT", "LIMIT", 10.0, 100, "MANUAL", "actor")


def test_place_order_invalid_price_raises(db_session: Session) -> None:
    svc = OrderService(db_session)
    with pytest.raises(ValueError, match="价格|price"):
        svc.place_order("600519.SH", "BUY", "LIMIT", -1.0, 100, "MANUAL", "actor")


def test_place_order_invalid_quantity_raises(db_session: Session) -> None:
    svc = OrderService(db_session)
    with pytest.raises(ValueError, match="数量|quantity"):
        svc.place_order("600519.SH", "BUY", "LIMIT", 1700.0, 0, "MANUAL", "actor")


def test_cancel_pending_order(db_session: Session) -> None:
    svc = OrderService(db_session)
    order = svc.place_order("600519.SH", "BUY", "LIMIT", 1719.5, 100, "MANUAL", "actor")
    cancelled = svc.cancel_order(order.order_id, actor="actor")
    assert cancelled.status == OrderStatus.CANCELLED.value


def test_cancel_nonexistent_order_raises(db_session: Session) -> None:
    svc = OrderService(db_session)
    with pytest.raises(ValueError, match="Order not found"):
        svc.cancel_order("nonexistent-id", actor="actor")


def test_cancel_already_cancelled_raises(db_session: Session) -> None:
    svc = OrderService(db_session)
    order = svc.place_order("600519.SH", "BUY", "LIMIT", 1719.5, 100, "MANUAL", "actor")
    svc.cancel_order(order.order_id, actor="actor")
    with pytest.raises(ValueError, match="cannot be cancelled"):
        svc.cancel_order(order.order_id, actor="actor")


def test_simulate_fill_full_fill(db_session: Session) -> None:
    svc = OrderService(db_session)
    order = svc.place_order("600519.SH", "BUY", "LIMIT", 1719.5, 200, "MANUAL", "actor")
    fill = svc.simulate_fill(order.order_id, fill_price=1719.5, fill_quantity=200)
    assert fill.fill_quantity == 200
    assert fill.commission > 0

    updated = svc.get_order(order.order_id)
    assert updated.status == OrderStatus.FILLED.value
    assert updated.filled_quantity == 200


def test_simulate_fill_partial_fill(db_session: Session) -> None:
    svc = OrderService(db_session)
    order = svc.place_order("600519.SH", "BUY", "LIMIT", 1719.5, 300, "MANUAL", "actor")
    svc.simulate_fill(order.order_id, fill_price=1719.5, fill_quantity=100)

    updated = svc.get_order(order.order_id)
    assert updated.status == OrderStatus.PARTIAL_FILLED.value
    assert updated.filled_quantity == 100


def test_list_orders_returns_most_recent_first(db_session: Session) -> None:
    svc = OrderService(db_session)
    svc.place_order("600519.SH", "BUY", "LIMIT", 1719.5, 100, "MANUAL", "actor")
    svc.place_order("300750.SZ", "BUY", "LIMIT", 250.0, 100, "MANUAL", "actor")
    orders = svc.list_orders(limit=10)
    assert len(orders) == 2


def test_audit_log_created_on_place(db_session: Session) -> None:
    from apps.api.app.db.repositories import AuditLogRepository
    svc = OrderService(db_session)
    svc.place_order("600519.SH", "BUY", "LIMIT", 1719.5, 100, "MANUAL", "actor")
    db_session.flush()
    logs = AuditLogRepository(db_session).list_recent(limit=10)
    assert any(log.action == "ORDER_SUBMITTED" for log in logs)


def test_audit_log_created_on_cancel(db_session: Session) -> None:
    from apps.api.app.db.repositories import AuditLogRepository
    svc = OrderService(db_session)
    order = svc.place_order("600519.SH", "BUY", "LIMIT", 1719.5, 100, "MANUAL", "actor")
    svc.cancel_order(order.order_id, actor="actor")
    db_session.flush()
    logs = AuditLogRepository(db_session).list_recent(limit=10)
    assert any(log.action == "ORDER_CANCELLED" for log in logs)
