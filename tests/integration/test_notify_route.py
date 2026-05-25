"""Test /api/v1/notify routes."""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.app.main import app

client = TestClient(app)


def test_status_returns_channel_summary():
    r = client.get("/api/v1/notify/status")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"feishu_configured", "llm_configured"}
    assert "webhook_url" not in body


def test_test_endpoint_with_no_channels_returns_empty():
    r = client.post("/api/v1/notify/test", json={"title": "t", "content": "b"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "发送失败" in body["message"]


def test_test_endpoint_dispatches_to_feishu_service(monkeypatch):
    from apps.api.app.api.routes import notify

    calls = {}

    def _fake_send(title, content, color="blue"):
        calls["payload"] = (title, content, color)
        return True

    monkeypatch.setattr(notify.feishu_service, "send_feishu", _fake_send)

    r = client.post("/api/v1/notify/test", json={"title": "x", "content": "y"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert calls["payload"] == ("x", "y", "blue")
