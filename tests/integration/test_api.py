from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from apps.api.app.main import app


client = TestClient(app)


def _auth_headers(key: str) -> dict[str, str]:
    return {"X-Api-Key": key}


def test_healthcheck() -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["app"] == "AlphaAgent"
    assert "llm_configured" in payload
    assert "feishu_configured" in payload


def test_readiness_reports_local_and_live_gates() -> None:
    response = client.get("/api/v1/health/readiness")

    assert response.status_code == 200
    payload = response.json()
    assert payload["local_ready"] is True
    assert payload["live_trading_ready"] is False
    assert payload["status"] == "degraded"
    assert isinstance(payload["checks"], list)
    assert {item["id"] for item in payload["checks"]} >= {
        "auth_config",
        "database",
        "market_provider",
        "market_cache",
        "trading_mode",
        "qmt_live_safety",
    }
    assert payload["summary"]["warnings"] >= 1
    assert payload["summary"]["next_action"]


def test_readiness_reports_auth_not_configured(monkeypatch) -> None:
    from apps.api.app.core import config as config_mod

    monkeypatch.setenv("QUANT_AUTH_ENABLED", "true")
    monkeypatch.delenv("QUANT_ADMIN_API_KEY", raising=False)
    monkeypatch.delenv("QUANT_TRADER_API_KEY", raising=False)
    monkeypatch.delenv("QUANT_VIEWER_API_KEY", raising=False)
    config_mod.reset_settings_cache()

    response = client.get("/api/v1/health/readiness")

    assert response.status_code == 200
    payload = response.json()
    assert payload["local_ready"] is False
    auth_check = next(item for item in payload["checks"] if item["id"] == "auth_config")
    assert auth_check["status"] == "fail"
    assert auth_check["blocks_local"] is True
    assert "QUANT_ADMIN_API_KEY" in auth_check["next_action"]


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
    payload = response.json()
    assert {
        "total",
        "ready",
        "provider",
        "mock",
        "min_ready",
        "real_time",
        "live_trading_safe",
    }.issubset(payload)
    assert isinstance(payload["mock"], bool)
    assert payload["live_trading_safe"] is (not payload["mock"])


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
        lambda symbol: {"symbol": symbol, "name": "宁德时代", "price": 100.0},
    )
    monkeypatch.setattr(
        market_service,
        "get_realtime_quotes",
        lambda symbols: [{"symbol": s, "name": "宁德时代", "price": 100.0, "change_pct": 0.0} for s in symbols],
    )

    preview = client.post(
        "/api/v1/trading/preview",
        json={"symbol": "300750.SZ", "side": "BUY", "quantity": 100, "price": 100.0},
    )
    assert preview.status_code == 200
    assert preview.json()["allowed"] is True

    order = client.post(
        "/api/v1/trading/orders",
        json={"symbol": "300750.SZ", "side": "BUY", "quantity": 100, "price": 100.0, "name": "宁德时代"},
    )
    assert order.status_code == 200
    assert order.json()["status"] == "FILLED"

    fills = client.get("/api/v1/trading/fills").json()
    assert any(f["symbol"] == "300750.SZ" and f["quantity"] == 100 for f in fills)

    trading_positions = client.get("/api/v1/trading/positions").json()
    assert any(p["symbol"] == "300750.SZ" and p["quantity"] == 100 for p in trading_positions)

    positions = client.get("/api/v1/positions/").json()
    assert not any(p["symbol"] == "300750.SZ" for p in positions)


def test_trading_rebalance_plan_route(monkeypatch) -> None:
    from apps.api.app.core import config as config_mod
    from apps.api.app.services import market_service, scanner_service

    monkeypatch.setenv("QUANT_TRADING_MODE", "paper")
    monkeypatch.setenv("QUANT_PAPER_INITIAL_CASH", "100000")
    config_mod.reset_settings_cache()

    monkeypatch.setattr(
        scanner_service,
        "scan_potential_stocks",
        lambda **kwargs: {
            "scan_run_id": 11,
            "llm_status": "disabled",
            "results": [
                {
                    "symbol": "300750.SZ",
                    "name": "宁德时代",
                        "price": 100.0,
                    "score": 88,
                        "trade_plan": {"entry_mid": 100.0, "expected_return_pct": 8.0},
                    "ai_analysis": {"action": "BUY"},
                    "evolution": {"probability": 0.72, "expected_return_pct": 8.5},
                    "fundamental": {"info": {"industry": "电池"}},
                    "indicators": {"vol_20d_pct": 2.0},
                },
                {
                    "symbol": "000001.SZ",
                    "name": "平安银行",
                    "price": 10.0,
                    "score": 80,
                    "trade_plan": {"entry_mid": 10.0, "expected_return_pct": 5.0},
                    "ai_analysis": {"action": "BUY"},
                    "evolution": {"probability": 0.62, "expected_return_pct": 5.8},
                    "fundamental": {"info": {"industry": "银行"}},
                    "indicators": {"vol_20d_pct": 1.5},
                },
            ],
        },
    )

    quote_map = {
        "300750.SZ": {"symbol": "300750.SZ", "name": "宁德时代", "price": 100.0, "change_pct": 0.0, "prev_close": 100.0, "industry": "电池"},
        "000001.SZ": {"symbol": "000001.SZ", "name": "平安银行", "price": 10.0, "change_pct": 0.0, "prev_close": 10.0, "industry": "银行"},
    }
    monkeypatch.setattr(market_service, "get_single_quote", lambda symbol: quote_map[symbol])
    monkeypatch.setattr(
        market_service,
        "get_realtime_quotes",
        lambda symbols: [quote_map[s] for s in symbols if s in quote_map],
    )

    response = client.post(
        "/api/v1/trading/rebalance-plan",
        json={
            "top_n": 2,
            "candidate_pool": 5,
            "enable_llm": False,
            "use_cache": False,
            "weighting_scheme": "risk_adjusted",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["scan_run_id"] == 11
    assert payload["scheme"] == "risk_adjusted"
    assert len(payload["actions"]) == 2
    assert all(action["risk"]["allowed"] is True for action in payload["actions"])
    assert len(payload["target_weights"]) == 2


def test_trading_paper_account_initialization_is_concurrency_safe(monkeypatch) -> None:
    from apps.api.app.core import config as config_mod
    from apps.api.app.db.models import TradingAccountORM
    from apps.api.app.db.session import session_scope
    from apps.api.app.services import market_service

    monkeypatch.setenv("QUANT_TRADING_MODE", "paper")
    monkeypatch.setenv("QUANT_PAPER_INITIAL_CASH", "100000")
    config_mod.reset_settings_cache()
    monkeypatch.setattr(market_service, "get_realtime_quotes", lambda symbols: [])

    paths = ["/api/v1/trading/account", "/api/v1/trading/positions"] * 8
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(client.get, paths))

    assert all(response.status_code == 200 for response in responses)
    with session_scope() as session:
        assert session.query(TradingAccountORM).filter_by(account_id="PAPER").count() == 1


def test_trading_paper_concurrent_buy_orders_cannot_overspend_cash(monkeypatch) -> None:
    from apps.api.app.core import config as config_mod
    from apps.api.app.services import market_service

    monkeypatch.setenv("QUANT_TRADING_MODE", "paper")
    monkeypatch.setenv("QUANT_PAPER_INITIAL_CASH", "100000")
    monkeypatch.setenv("QUANT_TRADING_SINGLE_STOCK_MAX_WEIGHT", "1.0")
    monkeypatch.setenv("QUANT_TRADING_DAILY_TURNOVER_LIMIT", "2.0")
    config_mod.reset_settings_cache()
    monkeypatch.setattr(
        market_service,
        "get_single_quote",
        lambda symbol: {"symbol": symbol, "name": "宁德时代", "price": 300.0, "prev_close": 300.0},
    )
    monkeypatch.setattr(
        market_service,
        "get_realtime_quotes",
        lambda symbols: [{"symbol": s, "name": "宁德时代", "price": 300.0, "prev_close": 300.0} for s in symbols],
    )

    body = {"symbol": "300750.SZ", "side": "BUY", "quantity": 100, "price": 300.0, "name": "宁德时代"}
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: client.post("/api/v1/trading/orders", json=body), range(4)))

    assert all(response.status_code == 200 for response in responses)
    statuses = [response.json()["status"] for response in responses]
    assert statuses.count("FILLED") == 3
    assert statuses.count("REJECTED") == 1

    account = client.get("/api/v1/trading/account").json()
    assert account["cash"] >= 0
    assert account["cash"] == 10000.0


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


def test_evolution_auto_scan_route_available(monkeypatch) -> None:
    from apps.api.app.services import evolution_service

    monkeypatch.setattr(
        evolution_service,
        "run_auto_scan_once",
        lambda: {
            "ok": True,
            "scan_run_id": 7,
            "results": 2,
            "predictions_created": 8,
            "llm_status": "disabled",
        },
    )

    response = client.post("/api/v1/evolution/auto-scan")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["scan_run_id"] == 7
    assert payload["predictions_created"] == 8


def test_evolution_backfill_route_passes_request(monkeypatch) -> None:
    from apps.api.app.services import evolution_service

    captured = {}

    def fake_backfill(**kwargs):
        captured.update(kwargs)
        return {
            "ok": True,
            "scan_run_id": 9,
            "symbols": kwargs["symbols"],
            "created_predictions": 2,
            "validated_predictions": 2,
            "diagnostics": {"ready": True, "top_error_types": []},
        }

    monkeypatch.setattr(evolution_service, "backfill_historical_predictions", fake_backfill)

    response = client.post(
        "/api/v1/evolution/backfill",
        json={
            "symbols": ["300750.sz"],
            "symbol_limit": 3,
            "bars_count": 120,
            "samples_per_symbol": 2,
            "horizon_days": 5,
            "min_gap_days": 7,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["created_predictions"] == 2
    assert captured == {
        "symbols": ["300750.sz"],
        "symbol_limit": 3,
        "bars_count": 120,
        "samples_per_symbol": 2,
        "horizon_days": 5,
        "min_gap_days": 7,
    }


def test_evolution_config_runtime_override_applies() -> None:
    response = client.post(
        "/api/v1/evolution/config",
        json={
            "validate_interval_seconds": 0,
            "validate_time": " 9:5 ",
            "failure_alert_enabled": False,
            "failure_alert_cooldown_seconds": 120,
            "auto_scan_enabled": False,
            "auto_scan_top_n": 9,
            "auto_scan_min_score": 61,
            "auto_scan_candidate_pool": 77,
            "auto_scan_enable_llm": False,
            "auto_scan_target_horizon_days": 5,
            "auto_evolve_enabled": False,
            "auto_evolve_min_samples": 12,
            "auto_evolve_min_live_samples": 7,
            "auto_promote_min_success_rate": 0.66,
            "auto_walk_forward_min_samples": 18,
            "auto_walk_forward_min_dates": 21,
            "auto_walk_forward_min_profitable_folds": 0.65,
            "auto_walk_forward_return_tolerance": 0.002,
            "auto_walk_forward_consistency_tolerance": 0.03,
            "auto_walk_forward_drawdown_tolerance": 0.04,
        },
    )

    assert response.status_code == 200
    effective = response.json()["effective"]
    assert effective["validate_interval_seconds"] == 0
    assert effective["validate_time"] == "09:05"
    assert effective["validate_schedule"] == "disabled"
    assert effective["failure_alert_enabled"] is False
    assert effective["failure_alert_cooldown_seconds"] == 120
    assert effective["auto_scan_enabled"] is False
    assert effective["auto_scan_top_n"] == 9
    assert effective["auto_scan_min_score"] == 61
    assert effective["auto_scan_candidate_pool"] == 77
    assert effective["auto_scan_enable_llm"] is False
    assert effective["auto_scan_target_horizon_days"] == 5
    assert effective["auto_evolve_enabled"] is False
    assert effective["auto_evolve_min_samples"] == 12
    assert effective["auto_evolve_min_live_samples"] == 7
    assert effective["auto_promote_min_success_rate"] == 0.66
    assert effective["auto_walk_forward_min_samples"] == 18
    assert effective["auto_walk_forward_min_dates"] == 21
    assert effective["auto_walk_forward_min_profitable_folds"] == 0.65
    assert effective["auto_walk_forward_return_tolerance"] == 0.002
    assert effective["auto_walk_forward_consistency_tolerance"] == 0.03
    assert effective["auto_walk_forward_drawdown_tolerance"] == 0.04

    fetched = client.get("/api/v1/evolution/config").json()
    assert fetched["runtime_override"]["validate_time"] == "09:05"
    assert fetched["runtime_override"]["failure_alert_enabled"] is False
    assert fetched["runtime_override"]["failure_alert_cooldown_seconds"] == 120
    assert fetched["runtime_override"]["auto_evolve_min_live_samples"] == 7
    assert fetched["runtime_override"]["auto_walk_forward_min_samples"] == 18
    assert fetched["runtime_override"]["auto_walk_forward_min_dates"] == 21


def test_evolution_config_rejects_invalid_validate_time() -> None:
    response = client.post(
        "/api/v1/evolution/config",
        json={"validate_time": "25:00"},
    )

    assert response.status_code == 422


def test_rbac_route_boundaries(monkeypatch) -> None:
    from apps.api.app.core import config as config_mod
    from apps.api.app.services import market_service

    monkeypatch.setenv("QUANT_AUTH_ENABLED", "true")
    monkeypatch.setenv("QUANT_ADMIN_API_KEY", "admin-key")
    monkeypatch.setenv("QUANT_TRADER_API_KEY", "trader-key")
    monkeypatch.setenv("QUANT_VIEWER_API_KEY", "viewer-key")
    config_mod.reset_settings_cache()

    monkeypatch.setattr(
        market_service,
        "get_single_quote",
        lambda symbol: {"symbol": symbol, "name": "宁德时代", "price": 100.0},
    )

    assert client.get("/api/v1/market/cache-status").status_code == 401
    assert client.get("/api/v1/market/cache-status", headers=_auth_headers("viewer-key")).status_code == 200

    viewer_write = client.post(
        "/api/v1/alerts/",
        headers=_auth_headers("viewer-key"),
        json={
            "symbol": "300750.SZ",
            "name": "宁德时代",
            "alert_type": "price_above",
            "target_price": 200.0,
        },
    )
    assert viewer_write.status_code == 403
    assert viewer_write.json()["detail"]["code"] == "INSUFFICIENT_ROLE"

    trader_write = client.post(
        "/api/v1/alerts/",
        headers=_auth_headers("trader-key"),
        json={
            "symbol": "300750.SZ",
            "name": "宁德时代",
            "alert_type": "price_above",
            "target_price": 200.0,
        },
    )
    assert trader_write.status_code == 200
    alert_id = trader_write.json()["id"]

    admin_only = client.delete("/api/v1/scanner/cache", headers=_auth_headers("trader-key"))
    assert admin_only.status_code == 403
    assert admin_only.json()["detail"]["code"] == "INSUFFICIENT_ROLE"

    assert client.delete("/api/v1/scanner/cache", headers=_auth_headers("admin-key")).status_code == 200
    assert client.delete(f"/api/v1/alerts/{alert_id}", headers=_auth_headers("trader-key")).status_code == 200
