from apps.qmt_gateway.backends import MockBackend, PlaceOrder


def test_mock_backend_rejects_invalid_lot_size() -> None:
    backend = MockBackend()
    order = backend.place_order(PlaceOrder(
        symbol="600519.SH",
        side="BUY",
        quantity=50,
        order_type="LIMIT",
        price=100.0,
    ))

    assert order.status == "REJECTED"
    assert "100" in order.error_message


def test_mock_backend_buy_fill_updates_account_and_position() -> None:
    backend = MockBackend(initial_cash=100_000)
    order = backend.place_order(PlaceOrder(
        symbol="600519.SH",
        side="BUY",
        quantity=100,
        order_type="LIMIT",
        price=100.0,
    ))

    filled = backend.simulate_fill(order.order_id, fill_price=100.0)
    assert filled.status == "FILLED"

    account = backend.get_account()
    assert account.cash == 90_000
    assert account.market_value == 10_000
    assert backend.list_positions()[0].quantity == 100
