"""Test the Prometheus exposition endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.app.main import app

client = TestClient(app)


def test_prom_endpoint_returns_text():
    r = client.get("/api/v1/metrics/prom")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")


def test_prom_format_has_help_and_type_lines():
    body = client.get("/api/v1/metrics/prom").text
    # Each metric should have HELP, TYPE, and a value line.
    assert "# HELP quant_orders_total" in body
    assert "# TYPE quant_orders_total gauge" in body
    # Value line: "quant_orders_total <number>"
    lines = [ln for ln in body.splitlines() if ln.startswith("quant_orders_total")]
    assert len(lines) >= 1
    parts = lines[0].split()
    assert parts[0] == "quant_orders_total"
    int(parts[1])  # parses as int


def test_prom_includes_websocket_metrics():
    body = client.get("/api/v1/metrics/prom").text
    assert "quant_ws_subscribers_quotes" in body
    assert "quant_ws_subscribers_alerts" in body


def test_prom_kv_cache_present():
    body = client.get("/api/v1/metrics/prom").text
    # Memory cache backend always exposes hits/misses
    assert "quant_kv_cache_hits_total" in body
    assert "quant_kv_cache_hit_rate" in body
