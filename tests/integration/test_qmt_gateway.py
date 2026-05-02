"""Integration tests for the QMT Gateway HTTP service (mock backend)."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

# Force mock backend regardless of platform
os.environ["QMT_BACKEND"] = "mock"
os.environ.pop("QMT_GATEWAY_API_KEY", None)

from apps.qmt_gateway import main as gw_main  # noqa: E402

# Reset backend (test isolation)
gw_main._backend = None
gw_client = TestClient(gw_main.app)


def setup_function(_):
    # Reset backend each test for isolation
    gw_main._backend = None


def test_health_returns_mock_backend():
    r = gw_client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["backend"] == "mock"


def test_place_limit_order_buy_then_simulate_fill():
    place = gw_client.post("/orders", json={
        "symbol": "600519.SH", "side": "BUY", "quantity": 100,
        "order_type": "LIMIT", "price": 100.0,
    })
    assert place.status_code == 201, place.text
    order = place.json()
    assert order["status"] == "ACCEPTED"
    assert order["filled_quantity"] == 0
    oid = order["order_id"]

    # Simulate fill
    fill = gw_client.post(f"/orders/{oid}/simulate_fill", json={"fill_price": 100.0})
    assert fill.status_code == 200
    body = fill.json()
    assert body["status"] == "FILLED"
    assert body["filled_quantity"] == 100
    assert body["avg_fill_price"] == 100.0

    # Position created
    positions = gw_client.get("/positions").json()
    assert any(p["symbol"] == "600519.SH" and p["quantity"] == 100 for p in positions)

    # Account cash decreased
    acct = gw_client.get("/account").json()
    assert acct["cash"] == pytest.approx(1_000_000 - 100 * 100, abs=0.01)
    assert acct["market_value"] == pytest.approx(100 * 100, abs=0.01)


def test_invalid_quantity_rejected():
    r = gw_client.post("/orders", json={
        "symbol": "600519.SH", "side": "BUY", "quantity": 50,  # not multiple of 100
        "order_type": "LIMIT", "price": 100.0,
    })
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "REJECTED"
    assert "100" in body["error_message"]


def test_insufficient_cash_rejected():
    r = gw_client.post("/orders", json={
        "symbol": "600519.SH", "side": "BUY", "quantity": 1_000_000,
        "order_type": "LIMIT", "price": 100.0,
    })
    body = r.json()
    assert body["status"] == "REJECTED"
    assert "Insufficient cash" in body["error_message"]


def test_cancel_pending_order():
    place = gw_client.post("/orders", json={
        "symbol": "600519.SH", "side": "BUY", "quantity": 100,
        "order_type": "LIMIT", "price": 100.0,
    }).json()
    cancel = gw_client.post(f"/orders/{place['order_id']}/cancel")
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "CANCELLED"


def test_cancel_unknown_order_404():
    r = gw_client.post("/orders/UNKNOWN/cancel")
    assert r.status_code == 404


def test_sell_without_position_rejected():
    r = gw_client.post("/orders", json={
        "symbol": "600519.SH", "side": "SELL", "quantity": 100,
        "order_type": "LIMIT", "price": 100.0,
    }).json()
    assert r["status"] == "REJECTED"
    assert "Insufficient available position" in r["error_message"]


def test_market_order_auto_fills():
    # Seed a position first so MARKET sell has something to use
    gw_client.post("/orders", json={
        "symbol": "600519.SH", "side": "BUY", "quantity": 100,
        "order_type": "LIMIT", "price": 100.0,
    })
    # Force fill the LIMIT to seed position
    placed = gw_client.get("/orders").json()
    pending = next(o for o in placed if o["status"] == "ACCEPTED")
    gw_client.post(f"/orders/{pending['order_id']}/simulate_fill", json={"fill_price": 100.0})

    # MARKET sell — should auto-fill
    r = gw_client.post("/orders", json={
        "symbol": "600519.SH", "side": "SELL", "quantity": 100,
        "order_type": "MARKET",
    }).json()
    assert r["status"] == "FILLED"


def test_mock_backend_state_persists_across_reinit(tmp_path):
    """Place order → kill backend → re-init from same state file → verify
    cash / positions / orders all restored."""
    from apps.qmt_gateway.backends import MockBackend, PlaceOrder

    state_file = str(tmp_path / "qmt_state.json")

    # Session 1: place LIMIT order + simulate fill, plus a rejected order
    b1 = MockBackend(initial_cash=500_000.0, state_file=state_file)
    buy = b1.place_order(PlaceOrder(
        symbol="600519.SH", side="BUY", quantity=100,
        order_type="LIMIT", price=1700.0,
    ))
    b1.simulate_fill(buy.order_id, fill_price=1700.0)
    b1.place_order(PlaceOrder(          # invalid qty → rejected & persisted
        symbol="000001.SZ", side="BUY", quantity=50,
        order_type="LIMIT", price=10.0,
    ))
    assert len(b1.list_orders()) == 2
    acct1 = b1.get_account()
    pos1 = b1.list_positions()
    assert pos1[0].symbol == "600519.SH"
    assert pos1[0].quantity == 100
    assert pos1[0].avg_cost == 1700.0
    assert acct1.cash < 500_000.0  # cash drawn down

    # Session 2: fresh backend from same file — state must match
    b2 = MockBackend(initial_cash=999_999.0, state_file=state_file)
    assert b2.get_account().cash == acct1.cash          # not 999_999
    assert b2.get_account().account_id == "MOCK_001"
    assert len(b2.list_orders()) == 2
    pos2 = b2.list_positions()
    assert len(pos2) == 1
    assert pos2[0].symbol == "600519.SH"
    assert pos2[0].quantity == 100
    assert pos2[0].avg_cost == 1700.0

    # Session 2 can also place more orders on top of session-1 state
    sell = b2.place_order(PlaceOrder(
        symbol="600519.SH", side="SELL", quantity=100,
        order_type="LIMIT", price=1750.0,
    ))
    b2.simulate_fill(sell.order_id, fill_price=1750.0)
    assert len(b2.list_positions()) == 0  # all sold
    assert b2.get_account().cash > acct1.cash  # gained from sell at higher price


def test_mock_backend_no_state_file_works_in_memory(tmp_path):
    """Without state_file → pure in-memory behaviour (legacy)."""
    from apps.qmt_gateway.backends import MockBackend

    b = MockBackend(initial_cash=100_000.0)   # no state_file
    assert b.get_account().cash == 100_000.0
    # No state file in tmp_path
    assert list(tmp_path.iterdir()) == []


def test_mock_backend_corrupt_state_file_falls_back(tmp_path):
    """A corrupted state file must not crash the gateway — start fresh."""
    from apps.qmt_gateway.backends import MockBackend

    sf = tmp_path / "corrupt.json"
    sf.write_text("{not valid json", encoding="utf-8")
    b = MockBackend(initial_cash=123_456.0, state_file=str(sf))
    # Falls back to initial_cash
    assert b.get_account().cash == 123_456.0


def test_api_key_required_when_set(monkeypatch):
    monkeypatch.setenv("QMT_GATEWAY_API_KEY", "secret-key")
    # No header
    r = gw_client.get("/health")
    assert r.status_code == 401
    # With wrong header
    r = gw_client.get("/health", headers={"X-API-Key": "wrong"})
    assert r.status_code == 401
    # With correct header
    r = gw_client.get("/health", headers={"X-API-Key": "secret-key"})
    assert r.status_code == 200
