"""QMT gateway wiring tests for the current standalone gateway."""

import os

from fastapi.testclient import TestClient

os.environ["QMT_BACKEND"] = "mock"
os.environ.pop("QMT_GATEWAY_API_KEY", None)

from apps.qmt_gateway import main as gw_main  # noqa: E402


def setup_function(_):
    gw_main._backend = None


def test_gateway_order_lifecycle_roundtrip() -> None:
    client = TestClient(gw_main.app)

    order = client.post(
        "/orders",
        json={
            "symbol": "300750.SZ",
            "side": "BUY",
            "quantity": 100,
            "order_type": "LIMIT",
            "price": 200.0,
        },
    )
    assert order.status_code == 201
    order_id = order.json()["order_id"]

    fetched = client.get(f"/orders/{order_id}")
    assert fetched.status_code == 200
    assert fetched.json()["order_id"] == order_id

    filled = client.post(f"/orders/{order_id}/simulate_fill", json={"fill_price": 200.0})
    assert filled.status_code == 200
    assert filled.json()["status"] == "FILLED"

    positions = client.get("/positions").json()
    assert any(p["symbol"] == "300750.SZ" for p in positions)
