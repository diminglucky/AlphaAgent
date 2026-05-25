from apps.qmt_gateway.backends import MockBackend, PlaceOrder


def test_qmt_mock_market_order_auto_fills() -> None:
    backend = MockBackend(initial_cash=50_000)
    order = backend.place_order(PlaceOrder(
        symbol="000001.SZ",
        side="BUY",
        quantity=100,
        order_type="MARKET",
    ))

    assert order.status == "FILLED"
    assert order.filled_quantity == 100
    assert backend.get_account().cash < 50_000


def test_qmt_mock_cancel_pending_order() -> None:
    backend = MockBackend()
    order = backend.place_order(PlaceOrder(
        symbol="000001.SZ",
        side="BUY",
        quantity=100,
        order_type="LIMIT",
        price=10.0,
    ))

    cancelled = backend.cancel_order(order.order_id)
    assert cancelled.status == "CANCELLED"
