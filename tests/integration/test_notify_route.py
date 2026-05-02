"""Test /api/v1/notify routes."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from apps.api.app.main import app

client = TestClient(app)


def test_status_returns_channel_summary():
    r = client.get("/api/v1/notify/status")
    assert r.status_code == 200
    body = r.json()
    assert "webhook" in body
    assert "email" in body
    # No secrets exposed
    assert "password" not in str(body).lower() or "password_set" in str(body).lower()


def test_test_endpoint_with_no_channels_returns_empty():
    # In test env nothing is configured so no channel is attempted.
    r = client.post("/api/v1/notify/test", json={"title": "t", "body": "b"})
    assert r.status_code == 200
    body = r.json()
    assert body["n_channels_attempted"] == 0
    assert body["n_succeeded"] == 0


def test_test_endpoint_dispatches_to_configured_webhook(monkeypatch):
    monkeypatch.setenv("QUANT_NOTIFY_WEBHOOK_URL", "https://example.test/hook")
    # Reset singleton so it picks up env
    import apps.api.app.services.notify_service as ns
    ns._singleton = None

    with patch("httpx.post") as mp:
        mp.return_value = MagicMock(raise_for_status=MagicMock())
        r = client.post("/api/v1/notify/test", json={"title": "x", "body": "y"})
    assert r.status_code == 200
    body = r.json()
    assert body["n_channels_attempted"] == 1
    assert body["results"]["webhook"] is True
