"""Test the platform-side QMTClient against an in-process Mock Gateway.

We spin up the gateway TestClient, then use httpx.MockTransport to forward
QMTClient calls to it without binding a real socket.
"""

from __future__ import annotations

import os

import httpx
import pytest

os.environ["QMT_BACKEND"] = "mock"
os.environ.pop("QMT_GATEWAY_API_KEY", None)

from apps.api.app.services.qmt_client import (
    QMTClient,
    QMTClientError,
    QMTClientUnavailable,
    QMTConfig,
)
from apps.qmt_gateway import main as gw_main


@pytest.fixture
def gateway_client():
    """A QMTClient whose httpx requests are routed in-process to the gateway app."""
    gw_main._backend = None  # reset gateway state
    gw_app = gw_main.app

    def _handler(request: httpx.Request) -> httpx.Response:
        # Forward request to the FastAPI app via TestClient
        from fastapi.testclient import TestClient
        tc = TestClient(gw_app)
        method = request.method
        url = str(request.url).replace("http://gw.test", "")
        kw: dict = {}
        if request.content:
            kw["content"] = request.content
            kw["headers"] = {k: v for k, v in request.headers.items()}
        else:
            kw["headers"] = {k: v for k, v in request.headers.items()}
        resp = tc.request(method, url, **kw)
        return httpx.Response(resp.status_code,
                              content=resp.content,
                              headers=dict(resp.headers))

    transport = httpx.MockTransport(_handler)

    # Patch httpx.request used by QMTClient
    import apps.api.app.services.qmt_client as qc_mod
    real_request = httpx.request

    def _patched(method, url, **kw):
        client = httpx.Client(transport=transport)
        try:
            return client.request(method, url, **kw)
        finally:
            client.close()

    qc_mod.httpx.request = _patched
    yield QMTClient(QMTConfig(url="http://gw.test", enabled=True))
    qc_mod.httpx.request = real_request


def test_client_health(gateway_client):
    h = gateway_client.health()
    assert h["status"] == "ok"
    assert h["backend"] == "mock"


def test_client_place_and_cancel(gateway_client):
    order = gateway_client.place_order(
        symbol="600519.SH", side="BUY", quantity=100,
        order_type="LIMIT", price=100.0,
    )
    assert order["status"] == "ACCEPTED"
    cancelled = gateway_client.cancel_order(order["order_id"])
    assert cancelled["status"] == "CANCELLED"


def test_client_get_account(gateway_client):
    acct = gateway_client.get_account()
    assert acct["account_id"] == "MOCK_001"
    assert acct["cash"] == 1_000_000.0


def test_client_unavailable_when_no_url():
    cli = QMTClient(QMTConfig(url="", enabled=True))
    with pytest.raises(QMTClientUnavailable):
        cli.health()


def test_client_error_on_bad_request(gateway_client):
    # Cancel a non-existent order → gateway returns 404 → client raises QMTClientError
    with pytest.raises(QMTClientError):
        gateway_client.cancel_order("DOES_NOT_EXIST")


def test_is_configured():
    assert QMTClient(QMTConfig(url="http://x", enabled=True)).is_configured() is True
    assert QMTClient(QMTConfig(url="http://x", enabled=False)).is_configured() is False
    assert QMTClient(QMTConfig(url="", enabled=True)).is_configured() is False
