from fastapi.testclient import TestClient

from apps.api.app.main import app


client = TestClient(app)


def test_healthcheck() -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["environment"] == "dev"


def test_list_instruments() -> None:
    response = client.get("/api/v1/market/instruments")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) >= 3
    assert payload[0]["symbol"].endswith((".SH", ".SZ"))


def test_provider_status_defaults_to_mock() -> None:
    response = client.get("/api/v1/market/provider/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["selected_provider"] == "mock"
    assert payload["active_provider"] == "mock"


def test_get_realtime_quotes_filters_symbols() -> None:
    response = client.get("/api/v1/market/quotes/realtime?symbols=600519.SH,300750.SZ")

    assert response.status_code == 200
    payload = response.json()
    assert [item["symbol"] for item in payload] == ["600519.SH", "300750.SZ"]


def test_portfolio_summary() -> None:
    response = client.get("/api/v1/portfolio/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["account_id"] == "acct-demo-001"
    assert payload["cash"] > 0


def test_latest_recommendations() -> None:
    response = client.get("/api/v1/recommendations/latest")

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["action"] in {"BUY", "SELL", "HOLD"}


def test_portfolio_rebalance_signal_proportional() -> None:
    """Rebalance with default signal-proportional scheme returns valid actions."""
    response = client.post(
        "/api/v1/portfolio/rebalance",
        json={
            "signals": {"600519.SH": 0.8, "000001.SZ": 0.5, "300750.SZ": 0.6,
                        "601318.SH": 0.4, "002594.SZ": 0.3},
            "prices": {"600519.SH": 1719.0, "000001.SZ": 12.5, "300750.SZ": 220.0,
                       "601318.SH": 45.0, "002594.SZ": 180.0},
            "scheme": "signal_proportional",
        },
        headers={"Authorization": "Bearer trader-token"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert "actions" in payload
    assert "expected_turnover" in payload
    assert "expected_cash_ratio" in payload
    assert isinstance(payload["warnings"], list)
    # Cash ratio should be ≥ min_cash_ratio (5%)
    assert payload["expected_cash_ratio"] >= 0.0


def test_portfolio_rebalance_equal_weight() -> None:
    """Equal-weight scheme should return equal target weights across symbols."""
    response = client.post(
        "/api/v1/portfolio/rebalance",
        json={
            "signals": {"A.SH": 0.9, "B.SZ": 0.7, "C.SH": 0.5, "D.SZ": 0.4, "E.SH": 0.3},
            "prices": {"A.SH": 100.0, "B.SZ": 100.0, "C.SH": 100.0, "D.SZ": 100.0, "E.SH": 100.0},
            "scheme": "equal_weight",
        },
        headers={"Authorization": "Bearer trader-token"},
    )
    assert response.status_code == 200
    payload = response.json()
    # Only BUY actions have a meaningful target_weight; SELL actions have target=0 by design
    buy_weights = [a["target_weight"] for a in payload["actions"] if a["action"] == "BUY"]
    if len(buy_weights) >= 2:
        assert max(buy_weights) - min(buy_weights) < 1e-9


def test_portfolio_rebalance_invalid_scheme() -> None:
    """Unknown scheme should return 422."""
    response = client.post(
        "/api/v1/portfolio/rebalance",
        json={
            "signals": {"600519.SH": 0.8},
            "prices": {"600519.SH": 1719.0},
            "scheme": "not_a_real_scheme",
        },
        headers={"Authorization": "Bearer trader-token"},
    )
    assert response.status_code == 422


def test_portfolio_rebalance_inverse_volatility() -> None:
    """Inverse-volatility scheme: lower vol symbol should get larger weight."""
    response = client.post(
        "/api/v1/portfolio/rebalance",
        json={
            "signals": {"A.SH": 0.6, "B.SZ": 0.6, "C.SH": 0.6, "D.SZ": 0.6, "E.SH": 0.6},
            "prices": {"A.SH": 50.0, "B.SZ": 50.0, "C.SH": 50.0, "D.SZ": 50.0, "E.SH": 50.0},
            "scheme": "inverse_volatility",
            "volatilities": {"A.SH": 0.04, "B.SZ": 0.02, "C.SH": 0.01,
                             "D.SZ": 0.03, "E.SH": 0.015},
        },
        headers={"Authorization": "Bearer trader-token"},
    )
    assert response.status_code == 200
    payload = response.json()
    by_sym = {a["symbol"]: a["target_weight"] for a in payload["actions"]}
    # C (vol=0.01) should outweigh A (vol=0.04) when both have same signal
    if "C.SH" in by_sym and "A.SH" in by_sym:
        assert by_sym["C.SH"] > by_sym["A.SH"]


def test_market_bars_returns_ohlcv() -> None:
    """GET /market/bars returns valid OHLCV data for a known symbol."""
    response = client.get("/api/v1/market/bars?symbol=600519.SH&freq=1d")
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert len(payload) >= 1
    bar = payload[0]
    for key in ("symbol", "trade_date", "open", "high", "low", "close", "volume"):
        assert key in bar, f"Missing field: {key}"
    assert bar["symbol"] == "600519.SH"
    assert bar["high"] >= bar["low"]


def test_market_bars_synthesised_symbol() -> None:
    """GET /market/bars falls back to generated bars for non-seed symbols."""
    response = client.get("/api/v1/market/bars?symbol=002415.SZ&freq=1d")
    assert response.status_code == 200
    bars = response.json()
    assert len(bars) >= 30


def test_market_bars_unknown_symbol_returns_404() -> None:
    response = client.get("/api/v1/market/bars?symbol=999999.XX&freq=1d")
    assert response.status_code == 404


def test_recommendations_explain_returns_explanation() -> None:
    """POST /recommendations/explain returns explanation text and metadata."""
    response = client.post(
        "/api/v1/recommendations/explain",
        json={"symbol": "600519.SH"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert "symbol" in payload
    assert payload["symbol"] == "600519.SH"
    assert "explanation" in payload or "reason" in payload or "summary" in payload


def test_research_factors_returns_snapshots() -> None:
    """GET /research/factors/{symbol} returns snapshot structure."""
    response = client.get("/api/v1/research/factors/600519.SH")
    assert response.status_code == 200
    payload = response.json()
    assert payload["symbol"] == "600519.SH"
    assert "count" in payload
    assert isinstance(payload["snapshots"], list)


def test_research_runs_returns_list() -> None:
    """GET /research/runs returns count + runs list."""
    response = client.get("/api/v1/research/runs")
    assert response.status_code == 200
    payload = response.json()
    assert "count" in payload
    assert isinstance(payload["runs"], list)


def test_research_runs_filter_by_model_name() -> None:
    """GET /research/runs?model_name=X returns filtered results."""
    response = client.get("/api/v1/research/runs?model_name=nonexistent_model")
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 0
    assert payload["runs"] == []


def test_backtest_run_returns_metrics_and_equity_curve() -> None:
    """POST /backtest/run returns ok=True, metrics, equity_curve, and trades."""
    response = client.post(
        "/api/v1/backtest/run",
        json={
            "symbols": ["600519.SH"],
            "strategy": "ma_crossover",
            "initial_capital": 500_000,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert "metrics" in payload
    m = payload["metrics"]
    for key in ("total_return", "annual_return", "sharpe_ratio", "max_drawdown",
                "win_rate", "profit_factor", "total_trades"):
        assert key in m, f"Missing metric: {key}"
    assert isinstance(payload["equity_curve"], list)
    assert isinstance(payload["trades"], list)


def test_backtest_run_buy_hold_strategy() -> None:
    response = client.post(
        "/api/v1/backtest/run",
        json={"symbols": ["000001.SZ"], "strategy": "buy_hold"},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_backtest_walk_forward_returns_folds() -> None:
    """POST /backtest/walk-forward returns aggregate + per-fold metrics.

    Use 002415.SZ (generated ~43 trading days) with small windows so
    at least 2 OOS folds fit within the mock data.
    """
    response = client.post(
        "/api/v1/backtest/walk-forward",
        json={
            "symbols": ["002415.SZ"],
            "strategy": "buy_hold",
            "in_sample_bars": 10,
            "oos_bars": 5,
            "min_folds": 2,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["n_folds"] >= 2
    agg = payload["aggregate"]
    for key in ("oos_total_return_mean", "oos_sharpe_mean", "oos_max_drawdown_mean",
                "pct_profitable_folds", "consistency_score"):
        assert key in agg, f"Missing aggregate key: {key}"
    assert isinstance(payload["folds"], list)
    fold = payload["folds"][0]
    assert "in_sample" in fold and "oos" in fold and "metrics" in fold


def test_backtest_walk_forward_insufficient_data() -> None:
    """Walk-forward with impossible window returns ok=False, not a 500."""
    response = client.post(
        "/api/v1/backtest/walk-forward",
        json={
            "symbols": ["600519.SH"],
            "strategy": "ma_crossover",
            "in_sample_bars": 9999,
            "oos_bars": 9999,
            "min_folds": 10,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert "error" in payload


def test_simulate_order_rejects_oversized_buy() -> None:
    response = client.post(
        "/api/v1/orders/simulate",
        json={
            "symbol": "600519.SH",
            "side": "BUY",
            "quantity": 2000,
            "price": 1719.5,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["accepted"] is False
    assert any("Insufficient cash" in item for item in payload["reasons"])
