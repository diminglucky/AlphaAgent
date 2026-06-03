from __future__ import annotations

import pytest

from apps.api.app.db.models import PositionORM, TradeFillORM, TradeOrderORM, TradingAccountORM, TradingPositionORM
from apps.api.app.services import trading_service


@pytest.fixture(autouse=True)
def _paper_env(monkeypatch):
    monkeypatch.setenv("QUANT_TRADING_MODE", "paper")
    monkeypatch.setenv("QUANT_PAPER_INITIAL_CASH", "100000")
    from apps.api.app.core import config as config_mod
    config_mod.reset_settings_cache()


def test_paper_buy_order_fills_and_updates_position(monkeypatch, db_session) -> None:
    monkeypatch.setattr(trading_service.market_service, "get_single_quote", lambda symbol: {"name": "宁德时代", "price": 200.0, "prev_close": 200.0})
    monkeypatch.setattr(trading_service.market_service, "get_realtime_quotes", lambda symbols: [{"symbol": s, "price": 200.0} for s in symbols])

    order = trading_service.place_order(
        db_session,
        symbol="300750.SZ",
        side="BUY",
        quantity=100,
        price=200.0,
        name="宁德时代",
    )

    assert order["status"] == "FILLED"
    assert order["filled_quantity"] == 100
    assert db_session.query(TradeOrderORM).count() == 1
    assert db_session.query(TradeFillORM).count() == 1
    pos = db_session.query(TradingPositionORM).filter_by(account_id="PAPER", symbol="300750.SZ").one()
    assert pos.quantity == 100
    assert pos.available_quantity == 100
    assert pos.avg_cost == 200.0
    assert db_session.query(PositionORM).filter_by(symbol="300750.SZ").count() == 0
    acct = db_session.query(TradingAccountORM).filter_by(account_id="PAPER").one()
    assert acct.cash == pytest.approx(80000.0)


def test_paper_sell_order_reduces_position(monkeypatch, db_session) -> None:
    db_session.add(TradingPositionORM(
        account_id="PAPER",
        broker="paper",
        symbol="300750.SZ",
        name="宁德时代",
        quantity=200,
        available_quantity=200,
        avg_cost=100.0,
        market_value=20000.0,
    ))
    db_session.flush()
    monkeypatch.setattr(trading_service.market_service, "get_single_quote", lambda symbol: {"name": "宁德时代", "price": 120.0, "prev_close": 120.0})
    monkeypatch.setattr(trading_service.market_service, "get_realtime_quotes", lambda symbols: [{"symbol": s, "price": 120.0} for s in symbols])
    trading_service.get_account(db_session)

    order = trading_service.place_order(
        db_session,
        symbol="300750.SZ",
        side="SELL",
        quantity=100,
        price=120.0,
        name="宁德时代",
    )

    assert order["status"] == "FILLED"
    pos = db_session.query(TradingPositionORM).filter_by(account_id="PAPER", symbol="300750.SZ").one()
    assert pos.quantity == 100
    assert pos.available_quantity == 100
    acct = db_session.query(TradingAccountORM).filter_by(account_id="PAPER").one()
    assert acct.cash == pytest.approx(112000.0)


def test_paper_rejects_invalid_quantity(db_session) -> None:
    order = trading_service.place_order(
        db_session,
        symbol="300750.SZ",
        side="BUY",
        quantity=50,
        price=100.0,
    )

    assert order["status"] == "REJECTED"
    assert "100" in order["error_message"]
    assert db_session.query(TradeFillORM).count() == 0


def test_preview_order_reports_cash_block(db_session) -> None:
    preview = trading_service.preview_order(
        db_session,
        symbol="300750.SZ",
        side="BUY",
        quantity=1000,
        price=1000.0,
    )

    assert preview["allowed"] is False
    assert "insufficient cash" in preview["reason"]


def test_manual_position_does_not_count_as_paper_position(monkeypatch, db_session) -> None:
    db_session.add(PositionORM(symbol="300750.SZ", name="宁德时代", quantity=200, avg_cost=100.0))
    db_session.flush()
    monkeypatch.setattr(trading_service.market_service, "get_single_quote", lambda symbol: {"name": "宁德时代", "price": 120.0, "prev_close": 120.0})
    monkeypatch.setattr(trading_service.market_service, "get_realtime_quotes", lambda symbols: [{"symbol": s, "price": 120.0} for s in symbols])

    account = trading_service.get_account(db_session)
    preview = trading_service.preview_order(
        db_session,
        symbol="300750.SZ",
        side="SELL",
        quantity=100,
        price=120.0,
    )

    assert account["market_value"] == 0.0
    assert preview["allowed"] is False
    assert "insufficient position" in preview["reason"]


def test_sell_odd_lot_allowed_when_available(monkeypatch, db_session) -> None:
    db_session.add(TradingPositionORM(
        account_id="PAPER",
        broker="paper",
        symbol="300750.SZ",
        name="宁德时代",
        quantity=50,
        available_quantity=50,
        avg_cost=100.0,
        market_value=5000.0,
    ))
    db_session.flush()
    monkeypatch.setattr(trading_service.market_service, "get_single_quote", lambda symbol: {"name": "宁德时代", "price": 100.0, "prev_close": 100.0})
    monkeypatch.setattr(trading_service.market_service, "get_realtime_quotes", lambda symbols: [{"symbol": s, "price": 100.0} for s in symbols])

    preview = trading_service.preview_order(db_session, symbol="300750.SZ", side="SELL", quantity=50, price=100.0)

    assert preview["allowed"] is True


def test_buy_above_limit_up_is_blocked(monkeypatch, db_session) -> None:
    monkeypatch.setattr(trading_service.market_service, "get_single_quote", lambda symbol: {"name": "贵州茅台", "price": 111.0, "prev_close": 100.0})

    preview = trading_service.preview_order(db_session, symbol="600519.SH", side="BUY", quantity=100, price=111.0)

    assert preview["allowed"] is False
    assert "涨停价" in preview["reason"]


def test_buy_exceeding_single_stock_weight_is_blocked(monkeypatch, db_session) -> None:
    monkeypatch.setattr(trading_service.market_service, "get_single_quote", lambda symbol: {"name": "贵州茅台", "price": 400.0, "prev_close": 400.0})

    preview = trading_service.preview_order(db_session, symbol="600519.SH", side="BUY", quantity=100, price=400.0)

    assert preview["allowed"] is False
    assert "Target weight" in preview["reason"]


def test_qmt_sync_upserts_account_positions_orders_and_incremental_fills(monkeypatch, db_session) -> None:
    monkeypatch.setenv("QUANT_TRADING_MODE", "qmt")

    def fake_qmt_request(method: str, path: str, json: dict | None = None):
        assert method == "GET"
        if path == "/account":
            return {
                "account_id": "QMT-001",
                "cash": 80000.0,
                "available_cash": 79000.0,
                "market_value": 20000.0,
                "total_asset": 100000.0,
            }
        if path == "/positions":
            return {"items": [{
                "symbol": "300750.SZ",
                "quantity": 100,
                "available_quantity": 100,
                "avg_cost": 200.0,
                "market_value": 20000.0,
            }]}
        if path == "/orders":
            return {"items": [{
                "order_id": "QMT-O-1",
                "client_order_id": "AA-qmt",
                "account_id": "QMT-001",
                "symbol": "300750.SZ",
                "side": "BUY",
                "order_type": "LIMIT",
                "quantity": 100,
                "price": 200.0,
                "status": "FILLED",
                "filled_quantity": 100,
                "avg_fill_price": 200.0,
                "submitted_at": "2024-01-01T09:30:00",
                "updated_at": "2024-01-01T09:31:00",
            }]}
        raise AssertionError(path)

    monkeypatch.setattr(trading_service, "_qmt_request", fake_qmt_request)

    first = trading_service.sync_qmt_state(db_session)
    second = trading_service.sync_qmt_state(db_session)

    assert first["positions_synced"] == 1
    assert first["orders_synced"] == 1
    assert first["fills_created"] == 1
    assert second["fills_created"] == 0
    acct = db_session.query(TradingAccountORM).filter_by(account_id="QMT-001").one()
    assert acct.total_asset == pytest.approx(100000.0)
    pos = db_session.query(TradingPositionORM).filter_by(account_id="QMT-001", symbol="300750.SZ").one()
    assert pos.quantity == 100
    order = db_session.query(TradeOrderORM).filter_by(broker_order_id="QMT-O-1").one()
    assert order.status == "FILLED"
    assert db_session.query(TradeFillORM).filter_by(order_id=order.id).count() == 1


def test_qmt_preview_requires_synced_account(monkeypatch, db_session) -> None:
    monkeypatch.setenv("QUANT_TRADING_MODE", "qmt")
    monkeypatch.setattr(trading_service.market_service, "get_single_quote", lambda symbol: {"name": "宁德时代", "price": 200.0, "prev_close": 200.0})

    preview = trading_service.preview_order(
        db_session,
        symbol="300750.SZ",
        side="BUY",
        quantity=100,
        price=200.0,
    )

    assert preview["allowed"] is False
    assert preview["mode"] == "qmt"
    assert "sync" in preview["reason"]
    assert preview["risk"]["metrics"]["requires_sync"] is True
    assert db_session.query(TradingAccountORM).filter_by(account_id="PAPER").count() == 0


def test_qmt_preview_uses_synced_qmt_cash_not_paper_cash(monkeypatch, db_session) -> None:
    monkeypatch.setenv("QUANT_TRADING_MODE", "qmt")
    monkeypatch.setattr(trading_service.market_service, "get_single_quote", lambda symbol: {"name": "宁德时代", "price": 200.0, "prev_close": 200.0})
    db_session.add(TradingAccountORM(
        account_id="QMT-001",
        broker="qmt",
        cash=50000.0,
        available_cash=5000.0,
        market_value=95000.0,
        total_asset=100000.0,
    ))
    db_session.flush()

    preview = trading_service.preview_order(
        db_session,
        symbol="300750.SZ",
        side="BUY",
        quantity=100,
        price=200.0,
    )

    assert preview["allowed"] is False
    assert "insufficient cash" in preview["reason"]
    assert "available 5000.00" in preview["reason"]
    assert db_session.query(TradingAccountORM).filter_by(account_id="PAPER").count() == 0


def test_qmt_preview_uses_synced_qmt_position_for_sell(monkeypatch, db_session) -> None:
    monkeypatch.setenv("QUANT_TRADING_MODE", "qmt")
    monkeypatch.setattr(trading_service.market_service, "get_single_quote", lambda symbol: {"name": "宁德时代", "price": 200.0, "prev_close": 200.0})
    db_session.add(TradingAccountORM(
        account_id="QMT-001",
        broker="qmt",
        cash=50000.0,
        available_cash=50000.0,
        market_value=20000.0,
        total_asset=70000.0,
    ))
    db_session.add(TradingPositionORM(
        account_id="QMT-001",
        broker="qmt",
        symbol="300750.SZ",
        name="宁德时代",
        quantity=200,
        available_quantity=200,
        avg_cost=180.0,
        market_value=40000.0,
    ))
    db_session.flush()

    preview = trading_service.preview_order(
        db_session,
        symbol="300750.SZ",
        side="SELL",
        quantity=50,
        price=200.0,
    )

    assert preview["allowed"] is True
    assert preview["risk"]["metrics"]["account_id"] == "QMT-001"
    assert preview["risk"]["metrics"]["available_quantity"] == 200
    assert db_session.query(TradingAccountORM).filter_by(account_id="PAPER").count() == 0


def test_qmt_rejected_order_is_not_forwarded_when_unsynced(monkeypatch, db_session) -> None:
    monkeypatch.setenv("QUANT_TRADING_MODE", "qmt")
    monkeypatch.setattr(trading_service.market_service, "get_single_quote", lambda symbol: {"name": "宁德时代", "price": 200.0, "prev_close": 200.0})

    def fail_qmt_request(method: str, path: str, json: dict | None = None):
        raise AssertionError("QMT Gateway should not be called when local account snapshot is missing")

    monkeypatch.setattr(trading_service, "_qmt_request", fail_qmt_request)

    order = trading_service.place_order(
        db_session,
        symbol="300750.SZ",
        side="BUY",
        quantity=100,
        price=200.0,
        name="宁德时代",
    )

    assert order["status"] == "REJECTED"
    assert order["broker"] == "qmt"
    assert "sync" in order["error_message"]
    assert db_session.query(TradeFillORM).count() == 0
