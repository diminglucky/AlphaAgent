from __future__ import annotations

from types import SimpleNamespace

import pytest

from apps.qmt_gateway.backends import PlaceOrder, XtQuantBackend


class FakeXtConstant:
    STOCK_BUY = 23
    STOCK_SELL = 24
    FIX_PRICE = 11
    MARKET_SH_CONVERT_5_CANCEL = 42
    MARKET_SZ_CONVERT_5_CANCEL = 52
    ORDER_REPORTED = 50
    ORDER_SUCCEEDED = 56
    ORDER_CANCELED = 57
    ORDER_JUNK = 59


class FakeTrader:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.orders: list[SimpleNamespace] = []
        self.asset = SimpleNamespace(
            account_id="QMT-001",
            cash=800_000.0,
            available_cash=790_000.0,
            market_value=210_000.0,
            total_asset=1_010_000.0,
        )
        self.positions = [
            SimpleNamespace(
                stock_code="300750.SZ",
                stock_name="宁德时代",
                volume=200,
                can_use_volume=100,
                open_price=210.0,
                market_value=42_000.0,
            )
        ]

    def order_stock(
        self,
        account,
        stock_code,
        order_type,
        order_volume,
        price_type,
        price,
        strategy_name,
        order_remark,
    ):
        self.calls.append((
            "order_stock",
            account.account_id,
            stock_code,
            order_type,
            order_volume,
            price_type,
            price,
            strategy_name,
            order_remark,
        ))
        order_id = str(10_000 + len(self.orders) + 1)
        self.orders.append(SimpleNamespace(
            order_id=order_id,
            account_id=account.account_id,
            stock_code=stock_code,
            order_type=order_type,
            order_volume=order_volume,
            price_type=price_type,
            price=price,
            traded_volume=0,
            traded_price=0.0,
            order_status=FakeXtConstant.ORDER_REPORTED,
            status_msg="",
            order_time=20260603103045,
            order_remark=order_remark,
        ))
        return order_id

    def cancel_order_stock(self, account, order_id):
        self.calls.append(("cancel_order_stock", account.account_id, str(order_id)))
        for order in self.orders:
            if str(order.order_id) == str(order_id):
                order.order_status = FakeXtConstant.ORDER_CANCELED
        return 0

    def query_stock_orders(self, account):
        self.calls.append(("query_stock_orders", account.account_id))
        return self.orders

    def query_stock_positions(self, account):
        self.calls.append(("query_stock_positions", account.account_id))
        return self.positions

    def query_stock_asset(self, account):
        self.calls.append(("query_stock_asset", account.account_id))
        return self.asset


def _backend() -> tuple[XtQuantBackend, FakeTrader]:
    trader = FakeTrader()
    account = SimpleNamespace(account_id="QMT-001")
    backend = XtQuantBackend(
        trader=trader,
        account=account,
        xtconstant=FakeXtConstant,
        xtdata=SimpleNamespace(),
    )
    return backend, trader


def test_xtquant_backend_requires_windows_without_injected_trader() -> None:
    with pytest.raises(RuntimeError, match="requires Windows"):
        XtQuantBackend(platform_name="Darwin")


def test_xtquant_backend_places_limit_order_and_maps_query_result() -> None:
    backend, trader = _backend()

    order = backend.place_order(PlaceOrder(
        symbol="300750.SZ",
        side="BUY",
        quantity=100,
        order_type="LIMIT",
        price=210.5,
        client_order_id="AA-test",
    ))

    assert order.order_id == "10001"
    assert order.client_order_id == "AA-test"
    assert order.symbol == "300750.SZ"
    assert order.side == "BUY"
    assert order.order_type == "LIMIT"
    assert order.status == "ACCEPTED"
    assert order.account_id == "QMT-001"
    assert trader.calls[0] == (
        "order_stock",
        "QMT-001",
        "300750.SZ",
        FakeXtConstant.STOCK_BUY,
        100,
        FakeXtConstant.FIX_PRICE,
        210.5,
        "AlphaAgent",
        "AA-test",
    )


def test_xtquant_backend_places_market_order_with_exchange_price_type() -> None:
    backend, trader = _backend()

    order = backend.place_order(PlaceOrder(
        symbol="600519.SH",
        side="SELL",
        quantity=100,
        order_type="MARKET",
        client_order_id="AA-market",
    ))

    assert order.status == "ACCEPTED"
    assert trader.calls[0][2] == "600519.SH"
    assert trader.calls[0][3] == FakeXtConstant.STOCK_SELL
    assert trader.calls[0][5] == FakeXtConstant.MARKET_SH_CONVERT_5_CANCEL
    assert trader.calls[0][6] == 0.0


def test_xtquant_backend_cancel_order_maps_cancelled_status() -> None:
    backend, _ = _backend()
    order = backend.place_order(PlaceOrder(
        symbol="300750.SZ",
        side="BUY",
        quantity=100,
        order_type="LIMIT",
        price=210.0,
    ))

    cancelled = backend.cancel_order(order.order_id)

    assert cancelled.order_id == order.order_id
    assert cancelled.status == "CANCELLED"


def test_xtquant_backend_maps_account_positions_and_filled_order() -> None:
    backend, trader = _backend()
    order = backend.place_order(PlaceOrder(
        symbol="300750.SZ",
        side="BUY",
        quantity=100,
        order_type="LIMIT",
        price=210.0,
    ))
    trader.orders[0].traded_volume = 100
    trader.orders[0].traded_price = 211.0
    trader.orders[0].order_status = FakeXtConstant.ORDER_SUCCEEDED

    account = backend.get_account()
    positions = backend.list_positions()
    fetched = backend.get_order(order.order_id)

    assert account.account_id == "QMT-001"
    assert account.cash == 800_000.0
    assert account.available_cash == 790_000.0
    assert account.total_asset == 1_010_000.0
    assert positions[0].symbol == "300750.SZ"
    assert positions[0].available_quantity == 100
    assert positions[0].name == "宁德时代"
    assert fetched.status == "FILLED"
    assert fetched.filled_quantity == 100
    assert fetched.avg_fill_price == 211.0


def test_xtquant_backend_rejects_failed_cancel_even_when_order_is_queryable() -> None:
    backend, trader = _backend()
    order = backend.place_order(PlaceOrder(
        symbol="300750.SZ",
        side="BUY",
        quantity=100,
        order_type="LIMIT",
        price=210.0,
    ))

    def failed_cancel(account, order_id):
        trader.calls.append(("cancel_order_stock", account.account_id, str(order_id)))
        return -1

    trader.cancel_order_stock = failed_cancel

    with pytest.raises(KeyError, match="Cancel failed"):
        backend.cancel_order(order.order_id)


def test_xtquant_backend_none_query_results_fail_closed() -> None:
    backend, trader = _backend()

    trader.asset = None
    with pytest.raises(RuntimeError, match="query_stock_asset returned None"):
        backend.get_account()

    trader.positions = None
    with pytest.raises(RuntimeError, match="query_stock_positions returned None"):
        backend.list_positions()

    trader.orders = None
    with pytest.raises(RuntimeError, match="query_stock_orders returned None"):
        backend.list_orders()


def test_xtquant_backend_maps_limit_order_when_price_type_is_missing_but_price_exists() -> None:
    backend, trader = _backend()
    backend.place_order(PlaceOrder(
        symbol="300750.SZ",
        side="BUY",
        quantity=100,
        order_type="LIMIT",
        price=210.0,
    ))
    trader.orders[0].price_type = None
    trader.orders[0].order_volume = "100.0"

    fetched = backend.get_order("10001")

    assert fetched.order_type == "LIMIT"
    assert fetched.quantity == 100
