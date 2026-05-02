"""Test that live order placement forwards to the QMT gateway when configured.

Strategy: monkey-patch `apps.api.app.services.qmt_client.QMTClient` at the
service level to a fake stub so we can verify the contract without a real
HTTP gateway.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from apps.api.app.main import app
from apps.api.app.services import qmt_client as qmt_mod

client = TestClient(app)


class _StubClient:
    """Stand-in QMTClient with controllable behaviour."""

    def __init__(self, behaviour: str = "ok") -> None:
        self.behaviour = behaviour
        self.calls: list[dict] = []

    def is_configured(self) -> bool:
        return True

    def place_order(self, **kw):
        self.calls.append({"op": "place", **kw})
        if self.behaviour == "unavailable":
            raise qmt_mod.QMTClientUnavailable("gateway down")
        if self.behaviour == "rejected":
            return {
                "order_id": "BROKER-REJ", "status": "REJECTED",
                "filled_quantity": 0, "error_message": "Insufficient cash",
            }
        return {
            "order_id": f"BROKER-{kw['client_order_id'][:6]}",
            "status": "ACCEPTED",
            "filled_quantity": 0,
            "error_message": None,
        }

    def cancel_order(self, broker_order_id: str):
        self.calls.append({"op": "cancel", "broker_order_id": broker_order_id})
        return {"order_id": broker_order_id, "status": "CANCELLED"}


def _place(symbol="300750.SZ", qty=100, price=250.0):
    return client.post("/api/v1/orders/live", json={
        "symbol": symbol, "side": "BUY", "order_type": "LIMIT",
        "quantity": qty, "price": price, "source": "MANUAL",
    })


def test_no_gateway_when_unconfigured():
    """Default test env has no gateway; placing should still succeed."""
    r = _place()
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "PENDING"
    assert body["broker_order_id"] is None


def test_gateway_forwarded_and_broker_id_recorded():
    stub = _StubClient(behaviour="ok")
    with patch.object(qmt_mod, "QMTClient", return_value=stub):
        r = _place()
    assert r.status_code == 201
    body = r.json()
    assert body["broker_order_id"] is not None
    assert body["broker_order_id"].startswith("BROKER-")
    # Audit log contains the gateway forward record
    logs = client.get("/api/v1/admin/audit-logs?action=ORDER_FORWARDED_TO_GATEWAY").json()
    assert len(logs) >= 1


def test_gateway_unavailable_keeps_order_pending():
    stub = _StubClient(behaviour="unavailable")
    with patch.object(qmt_mod, "QMTClient", return_value=stub):
        r = _place()
    assert r.status_code == 201
    body = r.json()
    # Gateway down → local order remains PENDING with no broker_id
    assert body["status"] == "PENDING"
    assert body["broker_order_id"] is None
    # Audit log records the failure
    logs = client.get("/api/v1/admin/audit-logs?action=ORDER_GATEWAY_FAILED").json()
    assert len(logs) >= 1


def test_gateway_rejection_marks_order_rejected():
    stub = _StubClient(behaviour="rejected")
    with patch.object(qmt_mod, "QMTClient", return_value=stub):
        r = _place()
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "REJECTED"
    assert body["broker_order_id"] == "BROKER-REJ"
    assert body["reject_reason"] == "Insufficient cash"


def test_cancel_forwards_to_gateway_when_broker_id_set():
    stub = _StubClient(behaviour="ok")
    with patch.object(qmt_mod, "QMTClient", return_value=stub):
        place = _place().json()
        order_id = place["order_id"]
        cancel = client.delete(f"/api/v1/orders/live/{order_id}")
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "CANCELLED"
    cancel_calls = [c for c in stub.calls if c["op"] == "cancel"]
    assert len(cancel_calls) == 1
    assert cancel_calls[0]["broker_order_id"].startswith("BROKER-")
