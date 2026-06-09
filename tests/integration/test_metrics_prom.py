"""Smoke tests for current operational status endpoints."""

from fastapi.testclient import TestClient

from apps.api.app.main import app

client = TestClient(app)


def test_cache_status_endpoint_returns_readiness() -> None:
    response = client.get("/api/v1/market/cache-status")
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["total"], int)
    assert isinstance(payload["ready"], bool)
    assert isinstance(payload["provider"], str)
    assert isinstance(payload["mock"], bool)
    assert isinstance(payload["live_trading_safe"], bool)


def test_ws_status_endpoint_returns_counts() -> None:
    response = client.get("/api/v1/ws/status")
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["quotes_clients"], int)
    assert isinstance(payload["alerts_clients"], int)
    assert isinstance(payload["loop_running"], bool)
