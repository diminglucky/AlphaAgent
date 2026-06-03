from fastapi.testclient import TestClient

from apps.api.app.main import app


client = TestClient(app)


def test_healthcheck() -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["app"] == "AlphaAgent"
    assert "llm_configured" in payload
    assert "feishu_configured" in payload


def test_watchlist_add_list_and_delete(monkeypatch) -> None:
    from apps.api.app.services import market_service

    monkeypatch.setattr(
        market_service,
        "get_single_quote",
        lambda symbol: {"symbol": symbol, "name": "宁德时代", "price": 100.0},
    )

    created = client.post("/api/v1/watchlist/", json={"symbol": "300750.sz"}).json()
    assert created["symbol"] == "300750.SZ"
    assert created["name"] == "宁德时代"

    listed = client.get("/api/v1/watchlist/").json()
    assert any(item["symbol"] == "300750.SZ" for item in listed)

    response = client.delete("/api/v1/watchlist/300750.sz")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_positions_normalize_prefixed_symbols(monkeypatch) -> None:
    from apps.api.app.services import market_service

    monkeypatch.setattr(
        market_service,
        "get_single_quote",
        lambda symbol: {"symbol": symbol, "name": "平安银行", "price": 11.0},
    )
    monkeypatch.setattr(
        market_service,
        "get_realtime_quotes",
        lambda symbols: [{"symbol": s, "name": "平安银行", "price": 11.0, "change_pct": 1.0} for s in symbols],
    )

    response = client.post(
        "/api/v1/positions/",
        json={"symbol": "sz000001", "quantity": 1000, "avg_cost": 10.0},
    )
    assert response.status_code == 200
    assert response.json()["symbol"] == "000001.SZ"

    positions = client.get("/api/v1/positions/").json()
    pos = next(item for item in positions if item["symbol"] == "000001.SZ")
    assert pos["current_price"] == 11.0
    assert pos["pnl_pct"] == 10.0

    assert client.delete("/api/v1/positions/000001.SZ").status_code == 200


def test_alert_create_list_delete() -> None:
    response = client.post(
        "/api/v1/alerts/",
        json={
            "symbol": "300750.SZ",
            "name": "宁德时代",
            "alert_type": "price_above",
            "target_price": 200.0,
        },
    )
    assert response.status_code == 200
    alert_id = response.json()["id"]

    alerts = client.get("/api/v1/alerts/", params={"triggered": False}).json()
    assert any(a["id"] == alert_id for a in alerts)

    assert client.delete(f"/api/v1/alerts/{alert_id}").status_code == 200


def test_market_cache_status_shape() -> None:
    response = client.get("/api/v1/market/cache-status")
    assert response.status_code == 200
    assert set(response.json()) == {"total", "ready"}


def test_llm_config_available_without_auth() -> None:
    response = client.get("/api/v1/llm/config")
    assert response.status_code == 200
    payload = response.json()
    assert "effective" in payload
    assert "providers" in payload


def test_notify_status_shape() -> None:
    response = client.get("/api/v1/notify/status")
    assert response.status_code == 200
    assert set(response.json()) == {"feishu_configured", "llm_configured"}


def test_scanner_metadata_routes() -> None:
    strategies = client.get("/api/v1/scanner/strategies")
    assert strategies.status_code == 200
    assert isinstance(strategies.json(), list)

    status = client.get("/api/v1/scanner/status")
    assert status.status_code == 200
    assert "cached" in status.json()


def test_trading_paper_order_flow(monkeypatch) -> None:
    from apps.api.app.core import config as config_mod
    from apps.api.app.services import market_service

    monkeypatch.setenv("QUANT_TRADING_MODE", "paper")
    monkeypatch.setenv("QUANT_PAPER_INITIAL_CASH", "100000")
    config_mod.reset_settings_cache()
    monkeypatch.setattr(
        market_service,
        "get_single_quote",
        lambda symbol: {"symbol": symbol, "name": "宁德时代", "price": 200.0},
    )
    monkeypatch.setattr(
        market_service,
        "get_realtime_quotes",
        lambda symbols: [{"symbol": s, "name": "宁德时代", "price": 200.0, "change_pct": 0.0} for s in symbols],
    )

    preview = client.post(
        "/api/v1/trading/preview",
        json={"symbol": "300750.SZ", "side": "BUY", "quantity": 100, "price": 200.0},
    )
    assert preview.status_code == 200
    assert preview.json()["allowed"] is True

    order = client.post(
        "/api/v1/trading/orders",
        json={"symbol": "300750.SZ", "side": "BUY", "quantity": 100, "price": 200.0, "name": "宁德时代"},
    )
    assert order.status_code == 200
    assert order.json()["status"] == "FILLED"

    fills = client.get("/api/v1/trading/fills").json()
    assert any(f["symbol"] == "300750.SZ" and f["quantity"] == 100 for f in fills)

    trading_positions = client.get("/api/v1/trading/positions").json()
    assert any(p["symbol"] == "300750.SZ" and p["quantity"] == 100 for p in trading_positions)

    positions = client.get("/api/v1/positions/").json()
    assert not any(p["symbol"] == "300750.SZ" for p in positions)


def test_evolution_auto_cycle_route_available() -> None:
    response = client.post("/api/v1/evolution/auto-cycle")

    assert response.status_code == 200
    assert response.json()["status"] in {
        "disabled",
        "insufficient_data",
        "auto_blocked",
        "auto_promoted",
        "auto_rolled_back",
    }
