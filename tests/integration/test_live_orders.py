"""Integration tests for live order, risk, news, signals, and admin endpoints."""

import uuid

import pytest
from fastapi.testclient import TestClient

from apps.api.app.main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# Live Orders
# ---------------------------------------------------------------------------

def test_place_order_returns_201() -> None:
    response = client.post(
        "/api/v1/orders/live",
        json={"symbol": "300750.SZ", "side": "BUY", "order_type": "LIMIT",
              "quantity": 100, "price": 240.0, "source": "MANUAL"},
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "PENDING"
    assert payload["symbol"] == "300750.SZ"


def test_place_order_unknown_symbol_returns_400() -> None:
    response = client.post(
        "/api/v1/orders/live",
        json={"symbol": "UNKNOWN.XX", "side": "BUY", "order_type": "LIMIT",
              "quantity": 100, "price": 10.0, "source": "MANUAL"},
    )
    assert response.status_code == 400


def test_list_orders_returns_list() -> None:
    response = client.get("/api/v1/orders/live")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_get_order_roundtrip() -> None:
    place = client.post(
        "/api/v1/orders/live",
        json={"symbol": "300750.SZ", "side": "BUY", "order_type": "LIMIT",
              "quantity": 200, "price": 250.0, "source": "SIGNAL"},
    )
    assert place.status_code == 201
    order_id = place.json()["order_id"]

    get = client.get(f"/api/v1/orders/live/{order_id}")
    assert get.status_code == 200
    assert get.json()["order_id"] == order_id


def test_cancel_order() -> None:
    place = client.post(
        "/api/v1/orders/live",
        json={"symbol": "300750.SZ", "side": "BUY", "order_type": "LIMIT",
              "quantity": 100, "price": 240.0, "source": "MANUAL"},
    )
    order_id = place.json()["order_id"]

    cancel = client.delete(f"/api/v1/orders/live/{order_id}")
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "CANCELLED"


def test_cancel_already_cancelled_returns_400() -> None:
    place = client.post(
        "/api/v1/orders/live",
        json={"symbol": "300750.SZ", "side": "BUY", "order_type": "LIMIT",
              "quantity": 100, "price": 240.0, "source": "MANUAL"},
    )
    order_id = place.json()["order_id"]
    client.delete(f"/api/v1/orders/live/{order_id}")
    second = client.delete(f"/api/v1/orders/live/{order_id}")
    assert second.status_code == 400


def test_simulate_fill_updates_status() -> None:
    place = client.post(
        "/api/v1/orders/live",
        json={"symbol": "300750.SZ", "side": "BUY", "order_type": "LIMIT",
              "quantity": 200, "price": 240.0, "source": "MANUAL"},
    )
    order_id = place.json()["order_id"]

    fill = client.post(
        f"/api/v1/orders/live/{order_id}/fills",
        json={"fill_price": 240.0, "fill_quantity": 200},
    )
    assert fill.status_code == 201
    assert fill.json()["fill_quantity"] == 200

    order = client.get(f"/api/v1/orders/live/{order_id}").json()
    assert order["status"] == "FILLED"
    assert order["filled_quantity"] == 200


def test_get_fills_for_order() -> None:
    place = client.post(
        "/api/v1/orders/live",
        json={"symbol": "300750.SZ", "side": "BUY", "order_type": "LIMIT",
              "quantity": 300, "price": 240.0, "source": "MANUAL"},
    )
    order_id = place.json()["order_id"]
    client.post(f"/api/v1/orders/live/{order_id}/fills",
                json={"fill_price": 240.0, "fill_quantity": 100})
    client.post(f"/api/v1/orders/live/{order_id}/fills",
                json={"fill_price": 245.0, "fill_quantity": 200})

    fills = client.get(f"/api/v1/orders/live/{order_id}/fills").json()
    assert len(fills) == 2


# ---------------------------------------------------------------------------
# Risk rules
# ---------------------------------------------------------------------------

def test_list_risk_rules_nonempty() -> None:
    response = client.get("/api/v1/risk/rules")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) >= 1
    assert "rule_id" in payload[0]


def test_create_and_delete_risk_rule() -> None:
    create = client.post(
        "/api/v1/risk/rules",
        json={"rule_type": "custom_test", "scope": "portfolio",
              "threshold": 0.10, "action_on_breach": "WARN",
              "description": "test rule"},
    )
    assert create.status_code == 201
    rule_id = create.json()["rule_id"]

    get = client.get(f"/api/v1/risk/rules/{rule_id}")
    assert get.status_code == 200

    delete = client.delete(f"/api/v1/risk/rules/{rule_id}")
    assert delete.status_code == 204

    get_after = client.get(f"/api/v1/risk/rules/{rule_id}")
    assert get_after.status_code == 404


def test_update_risk_rule() -> None:
    create = client.post(
        "/api/v1/risk/rules",
        json={"rule_type": "update_test", "scope": "symbol",
              "threshold": 0.20, "action_on_breach": "BLOCK",
              "description": "before"},
    )
    rule_id = create.json()["rule_id"]

    patch = client.patch(
        f"/api/v1/risk/rules/{rule_id}",
        json={"threshold": 0.35, "enabled": False},
    )
    assert patch.status_code == 200
    assert patch.json()["threshold"] == 0.35
    assert patch.json()["enabled"] is False


def test_list_risk_events_empty() -> None:
    response = client.get("/api/v1/risk/events")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


# ---------------------------------------------------------------------------
# News
# ---------------------------------------------------------------------------

def test_ingest_and_list_article() -> None:
    uid = uuid.uuid4().hex
    ingest = client.post(
        "/api/v1/news/articles",
        json={
            "source": "test_source",
            "title": "茅台Q1营收超预期",
            "raw_text": f"贵州茅台2026年一季度营收同比增长15%。uid={uid}" + "x" * 50,
            "published_at": "2026-04-25T08:00:00",
            "symbols": ["600519.SH"],
        },
    )
    assert ingest.status_code == 201
    article_id = ingest.json()["article_id"]

    articles = client.get("/api/v1/news/articles?symbol=600519.SH").json()
    assert any(a["article_id"] == article_id for a in articles)


def test_duplicate_article_returns_409() -> None:
    uid = uuid.uuid4().hex
    body = {
        "source": "dup_source",
        "title": "duplicate test",
        "raw_text": f"same content abc uid={uid}" * 5,
        "published_at": "2026-04-26T08:00:00",
        "symbols": [],
    }
    r1 = client.post("/api/v1/news/articles", json=body)
    assert r1.status_code == 201
    r2 = client.post("/api/v1/news/articles", json=body)
    assert r2.status_code == 409


def test_add_news_event() -> None:
    uid = uuid.uuid4().hex
    ingest = client.post(
        "/api/v1/news/articles",
        json={
            "source": "event_src",
            "title": "宁德时代获大单",
            "raw_text": f"宁德时代签署百亿合同。uid={uid}" + "y" * 50,
            "published_at": "2026-04-27T09:00:00",
            "symbols": ["300750.SZ"],
        },
    )
    article_id = ingest.json()["article_id"]

    add = client.post(
        f"/api/v1/news/articles/{article_id}/events",
        json={
            "event_type": "EARNINGS_BEAT",
            "sentiment_score": 0.8,
            "urgency_score": 0.6,
            "relevance_score": 0.9,
            "summary": "positive earnings signal",
        },
    )
    assert add.status_code == 201
    assert add.json()["event_type"] == "EARNINGS_BEAT"

    events = client.get("/api/v1/news/symbols/300750.SZ/events").json()
    assert len(events) >= 1


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------

def test_save_and_list_signal() -> None:
    save = client.post(
        "/api/v1/signals",
        json={
            "symbol": "600519.SH",
            "signal_type": "TECHNICAL",
            "raw_score": 0.65,
            "confidence": 0.78,
            "components": {"momentum": 0.7, "trend": 0.6},
            "expected_horizon": "swing_5d",
        },
    )
    assert save.status_code == 201
    assert save.json()["symbol"] == "600519.SH"

    latest = client.get("/api/v1/signals").json()
    assert any(s["symbol"] == "600519.SH" for s in latest)


# ---------------------------------------------------------------------------
# Admin / Audit logs
# ---------------------------------------------------------------------------

def test_audit_logs_populated_after_order() -> None:
    # Use a fresh symbol to avoid concentration limit from prior tests
    place = client.post(
        "/api/v1/orders/live",
        json={"symbol": "300750.SZ", "side": "BUY", "order_type": "LIMIT",
              "quantity": 100, "price": 250.0, "source": "MANUAL"},
    )
    assert place.status_code == 201, place.text
    # Filter by action so the entry isn't squeezed out by SIGNAL_GENERATED logs.
    logs = client.get("/api/v1/admin/audit-logs?action=ORDER_SUBMITTED").json()
    assert len(logs) >= 1
    assert all(log["action"] == "ORDER_SUBMITTED" for log in logs)


def test_audit_logs_filter_by_action() -> None:
    logs = client.get("/api/v1/admin/audit-logs?action=ORDER_SUBMITTED").json()
    assert all(log["action"] == "ORDER_SUBMITTED" for log in logs)
