"""Integration tests for current AlphaAgent position and alert flows."""

from fastapi.testclient import TestClient

from apps.api.app.main import app

client = TestClient(app)


def test_position_upsert_update_and_delete(monkeypatch) -> None:
    from apps.api.app.services import market_service

    monkeypatch.setattr(
        market_service,
        "get_single_quote",
        lambda symbol: {"symbol": symbol, "name": "宁德时代", "price": 210.0},
    )
    monkeypatch.setattr(
        market_service,
        "get_realtime_quotes",
        lambda symbols: [{"symbol": s, "name": "宁德时代", "price": 210.0, "change_pct": 2.0} for s in symbols],
    )

    create = client.post(
        "/api/v1/positions/",
        json={"symbol": "300750.SZ", "quantity": 100, "avg_cost": 200.0},
    )
    assert create.status_code == 200
    assert create.json()["symbol"] == "300750.SZ"

    update = client.post(
        "/api/v1/positions/",
        json={"symbol": "300750.SZ", "quantity": 200, "avg_cost": 205.0},
    )
    assert update.status_code == 200

    positions = client.get("/api/v1/positions/").json()
    pos = next(p for p in positions if p["symbol"] == "300750.SZ")
    assert pos["quantity"] == 200
    assert pos["current_price"] == 210.0

    assert client.delete("/api/v1/positions/300750.SZ").status_code == 200


def test_invalid_alert_type_rejected() -> None:
    response = client.post(
        "/api/v1/alerts/",
        json={
            "symbol": "300750.SZ",
            "alert_type": "bad_type",
            "target_price": 100.0,
        },
    )
    assert response.status_code == 400


def test_ws_status_endpoint() -> None:
    response = client.get("/api/v1/ws/status")
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"quotes_clients", "alerts_clients", "loop_running"}
