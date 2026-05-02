"""Verify simulate_fill updates Position with correct accounting."""

from __future__ import annotations

from sqlalchemy.orm import Session

from apps.api.app.db.repositories import PortfolioRepository
from apps.api.app.services.order_service import OrderService


def test_buy_creates_position(seeded_session: Session) -> None:
    svc = OrderService(seeded_session)
    portfolio = PortfolioRepository(seeded_session)

    # Place + fully fill 100 shares of an unheld stock
    order = svc.place_order(
        symbol="300750.SZ", side="BUY", order_type="LIMIT",
        price=240.0, quantity=100, source="MANUAL", actor="test",
    )
    svc.simulate_fill(order.order_id, fill_price=240.0, fill_quantity=100)

    pos = portfolio.get_position("acct-demo-001", "300750.SZ")
    assert pos is not None
    assert pos.quantity == 100
    assert abs(pos.avg_cost - 240.0) < 0.01
    # T+1 — bought today is locked
    assert pos.available_quantity == 0


def test_buy_increases_existing_with_weighted_avg(seeded_session: Session) -> None:
    """Two BUYs at different prices → weighted avg cost."""
    svc = OrderService(seeded_session)
    portfolio = PortfolioRepository(seeded_session)

    o1 = svc.place_order(symbol="300750.SZ", side="BUY", order_type="LIMIT",
                         price=200.0, quantity=100, source="MANUAL", actor="test")
    svc.simulate_fill(o1.order_id, fill_price=200.0, fill_quantity=100)

    o2 = svc.place_order(symbol="300750.SZ", side="BUY", order_type="LIMIT",
                         price=240.0, quantity=100, source="MANUAL", actor="test")
    svc.simulate_fill(o2.order_id, fill_price=240.0, fill_quantity=100)

    pos = portfolio.get_position("acct-demo-001", "300750.SZ")
    assert pos.quantity == 200
    # Weighted: (200*100 + 240*100) / 200 = 220
    assert abs(pos.avg_cost - 220.0) < 0.01


def test_cash_decreases_on_buy(seeded_session: Session) -> None:
    svc = OrderService(seeded_session)
    portfolio = PortfolioRepository(seeded_session)
    before = portfolio.get_summary().cash

    o = svc.place_order(symbol="300750.SZ", side="BUY", order_type="LIMIT",
                        price=240.0, quantity=100, source="MANUAL", actor="test")
    svc.simulate_fill(o.order_id, fill_price=240.0, fill_quantity=100)

    after = portfolio.get_summary().cash
    spent = before - after
    # 24,000 + commission (~7.2) ≈ 24,007.20
    assert 23_990 < spent < 24_020
