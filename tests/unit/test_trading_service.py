from __future__ import annotations

import pytest

from apps.api.app.db.models import PositionORM, TradeFillORM, TradeOrderORM, TradingAccountORM, TradingPositionORM
from apps.api.app.services import trading_service


@pytest.fixture(autouse=True)
def _paper_env(monkeypatch):
    monkeypatch.setenv("QUANT_TRADING_MODE", "paper")
    monkeypatch.setenv("QUANT_PAPER_INITIAL_CASH", "100000")
    from apps.api.app.core import config as config_mod
    config_mod.reset_settings_cache()


def test_paper_buy_order_fills_and_updates_position(monkeypatch, db_session) -> None:
    monkeypatch.setattr(trading_service.market_service, "get_single_quote", lambda symbol: {"name": "宁德时代", "price": 100.0, "prev_close": 100.0})
    monkeypatch.setattr(trading_service.market_service, "get_realtime_quotes", lambda symbols: [{"symbol": s, "price": 100.0} for s in symbols])

    order = trading_service.place_order(
        db_session,
        symbol="300750.SZ",
        side="BUY",
        quantity=100,
        price=100.0,
        name="宁德时代",
    )

    assert order["status"] == "FILLED"
    assert order["filled_quantity"] == 100
    assert db_session.query(TradeOrderORM).count() == 1
    assert db_session.query(TradeFillORM).count() == 1
    pos = db_session.query(TradingPositionORM).filter_by(account_id="PAPER", symbol="300750.SZ").one()
    assert pos.quantity == 100
    assert pos.available_quantity == 100
    assert pos.avg_cost == 100.0
    assert db_session.query(PositionORM).filter_by(symbol="300750.SZ").count() == 0
    acct = db_session.query(TradingAccountORM).filter_by(account_id="PAPER").one()
    assert acct.cash == pytest.approx(90000.0)


def _qmt_safe_env(monkeypatch) -> None:
    monkeypatch.setenv("QUANT_TRADING_MODE", "qmt")
    monkeypatch.setenv("QUANT_MARKET_DATA_PROVIDER", "akshare")
    monkeypatch.setenv("QUANT_AUTH_ENABLED", "true")
    monkeypatch.setenv("QUANT_QMT_GATEWAY_API_KEY", "gateway-key")
    from apps.api.app.core import config as config_mod
    config_mod.reset_settings_cache()


def test_paper_sell_order_reduces_position(monkeypatch, db_session) -> None:
    db_session.add(TradingPositionORM(
        account_id="PAPER",
        broker="paper",
        symbol="300750.SZ",
        name="宁德时代",
        quantity=200,
        available_quantity=200,
        avg_cost=100.0,
        market_value=20000.0,
    ))
    db_session.flush()
    monkeypatch.setattr(trading_service.market_service, "get_single_quote", lambda symbol: {"name": "宁德时代", "price": 120.0, "prev_close": 120.0})
    monkeypatch.setattr(trading_service.market_service, "get_realtime_quotes", lambda symbols: [{"symbol": s, "price": 120.0} for s in symbols])
    trading_service.get_account(db_session)

    order = trading_service.place_order(
        db_session,
        symbol="300750.SZ",
        side="SELL",
        quantity=100,
        price=120.0,
        name="宁德时代",
    )

    assert order["status"] == "FILLED"
    pos = db_session.query(TradingPositionORM).filter_by(account_id="PAPER", symbol="300750.SZ").one()
    assert pos.quantity == 100
    assert pos.available_quantity == 100
    acct = db_session.query(TradingAccountORM).filter_by(account_id="PAPER").one()
    assert acct.cash == pytest.approx(112000.0)


def test_paper_rejects_invalid_quantity(db_session) -> None:
    order = trading_service.place_order(
        db_session,
        symbol="300750.SZ",
        side="BUY",
        quantity=50,
        price=100.0,
    )

    assert order["status"] == "REJECTED"
    assert "100" in order["error_message"]
    assert db_session.query(TradeFillORM).count() == 0


def test_preview_order_reports_cash_block(db_session) -> None:
    preview = trading_service.preview_order(
        db_session,
        symbol="300750.SZ",
        side="BUY",
        quantity=1000,
        price=1000.0,
    )

    assert preview["allowed"] is False
    assert "insufficient cash" in preview["reason"]


def test_manual_position_does_not_count_as_paper_position(monkeypatch, db_session) -> None:
    db_session.add(PositionORM(symbol="300750.SZ", name="宁德时代", quantity=200, avg_cost=100.0))
    db_session.flush()
    monkeypatch.setattr(trading_service.market_service, "get_single_quote", lambda symbol: {"name": "宁德时代", "price": 120.0, "prev_close": 120.0})
    monkeypatch.setattr(trading_service.market_service, "get_realtime_quotes", lambda symbols: [{"symbol": s, "price": 120.0} for s in symbols])

    account = trading_service.get_account(db_session)
    preview = trading_service.preview_order(
        db_session,
        symbol="300750.SZ",
        side="SELL",
        quantity=100,
        price=120.0,
    )

    assert account["market_value"] == 0.0
    assert preview["allowed"] is False
    assert "insufficient position" in preview["reason"]


def test_sell_odd_lot_allowed_when_available(monkeypatch, db_session) -> None:
    db_session.add(TradingPositionORM(
        account_id="PAPER",
        broker="paper",
        symbol="300750.SZ",
        name="宁德时代",
        quantity=50,
        available_quantity=50,
        avg_cost=100.0,
        market_value=5000.0,
    ))
    db_session.flush()
    monkeypatch.setattr(trading_service.market_service, "get_single_quote", lambda symbol: {"name": "宁德时代", "price": 100.0, "prev_close": 100.0})
    monkeypatch.setattr(trading_service.market_service, "get_realtime_quotes", lambda symbols: [{"symbol": s, "price": 100.0} for s in symbols])

    preview = trading_service.preview_order(db_session, symbol="300750.SZ", side="SELL", quantity=50, price=100.0)

    assert preview["allowed"] is True


def test_buy_above_limit_up_is_blocked(monkeypatch, db_session) -> None:
    monkeypatch.setattr(trading_service.market_service, "get_single_quote", lambda symbol: {"name": "贵州茅台", "price": 111.0, "prev_close": 100.0})

    preview = trading_service.preview_order(db_session, symbol="600519.SH", side="BUY", quantity=100, price=111.0)

    assert preview["allowed"] is False
    assert "涨停价" in preview["reason"]


def test_buy_exceeding_single_stock_weight_is_blocked(monkeypatch, db_session) -> None:
    monkeypatch.setattr(trading_service.market_service, "get_single_quote", lambda symbol: {"name": "贵州茅台", "price": 400.0, "prev_close": 400.0})

    preview = trading_service.preview_order(db_session, symbol="600519.SH", side="BUY", quantity=100, price=400.0)

    assert preview["allowed"] is False
    assert "Target weight" in preview["reason"]


def test_buy_in_deep_portfolio_drawdown_is_blocked(monkeypatch, db_session) -> None:
    db_session.add(TradingAccountORM(
        account_id="PAPER",
        broker="paper",
        cash=100000.0,
        available_cash=100000.0,
        market_value=0.0,
        total_asset=100000.0,
        raw={"high_water_mark": 130000.0},
    ))
    db_session.flush()
    monkeypatch.setattr(
        trading_service.market_service,
        "get_single_quote",
        lambda symbol: {"symbol": symbol, "name": "宁德时代", "price": 100.0, "prev_close": 100.0},
    )

    preview = trading_service.preview_order(
        db_session,
        symbol="300750.SZ",
        side="BUY",
        quantity=100,
        price=100.0,
    )

    assert preview["allowed"] is False
    assert "Portfolio drawdown" in preview["reason"]
    assert preview["risk"]["metrics"]["portfolio_drawdown"] == pytest.approx(-0.2308, abs=1e-4)


def test_buy_adding_to_losing_position_is_blocked(monkeypatch, db_session) -> None:
    db_session.add(TradingPositionORM(
        account_id="PAPER",
        broker="paper",
        symbol="300750.SZ",
        name="宁德时代",
        quantity=100,
        available_quantity=100,
        avg_cost=100.0,
        market_value=8500.0,
        raw={"industry": "电池"},
    ))
    db_session.flush()
    monkeypatch.setattr(
        trading_service.market_service,
        "get_single_quote",
        lambda symbol: {"symbol": symbol, "name": "宁德时代", "price": 85.0, "prev_close": 85.0, "industry": "电池"},
    )
    monkeypatch.setattr(
        trading_service.market_service,
        "get_realtime_quotes",
        lambda symbols: [{"symbol": s, "name": "宁德时代", "price": 85.0, "change_pct": -1.0} for s in symbols],
    )

    preview = trading_service.preview_order(
        db_session,
        symbol="300750.SZ",
        side="BUY",
        quantity=100,
        price=85.0,
    )

    assert preview["allowed"] is False
    assert "position return" in preview["reason"]
    assert preview["risk"]["metrics"]["position_return"] == pytest.approx(-0.15, abs=1e-4)


def test_buy_limit_price_does_not_drive_existing_position_stop_loss(monkeypatch, db_session) -> None:
    db_session.add(TradingAccountORM(
        account_id="PAPER",
        broker="paper",
        cash=960000.0,
        available_cash=960000.0,
        market_value=39302.0,
        total_asset=999302.0,
        raw={"high_water_mark": 999302.0},
    ))
    db_session.add(TradingPositionORM(
        account_id="PAPER",
        broker="paper",
        symbol="300750.SZ",
        name="宁德时代",
        quantity=100,
        available_quantity=100,
        avg_cost=360.0,
        market_value=39302.0,
        raw={"industry": "电池"},
    ))
    db_session.flush()
    monkeypatch.setattr(
        trading_service.market_service,
        "get_single_quote",
        lambda symbol: {
            "symbol": symbol,
            "name": "宁德时代",
            "price": 393.02,
            "prev_close": 403.0,
            "limit_down": 322.4,
            "industry": "电池",
        },
    )
    monkeypatch.setattr(
        trading_service.market_service,
        "get_realtime_quotes",
        lambda symbols: [{"symbol": s, "name": "宁德时代", "price": 393.02, "industry": "电池"} for s in symbols],
    )

    preview = trading_service.preview_order(
        db_session,
        symbol="300750.SZ",
        side="BUY",
        quantity=100,
        price=323.0,
    )

    assert preview["allowed"] is True
    assert preview["risk"]["metrics"]["market_price"] == pytest.approx(393.02)
    assert preview["risk"]["metrics"]["position_return"] == pytest.approx(0.0917, abs=1e-4)


def test_buy_high_industry_concentration_warns_but_allows(monkeypatch, db_session) -> None:
    db_session.add(TradingAccountORM(
        account_id="PAPER",
        broker="paper",
        cash=65000.0,
        available_cash=65000.0,
        market_value=35000.0,
        total_asset=100000.0,
        raw={"high_water_mark": 100000.0},
    ))
    db_session.add(TradingPositionORM(
        account_id="PAPER",
        broker="paper",
        symbol="000001.SZ",
        name="宁德主题ETF",
        quantity=100,
        available_quantity=100,
        avg_cost=350.0,
        market_value=35000.0,
        raw={"industry": "电池"},
    ))
    db_session.flush()

    def fake_quote(symbol: str):
        if symbol == "600519.SH":
            return {"symbol": symbol, "name": "先导智能", "price": 100.0, "prev_close": 100.0, "industry": "电池"}
        return {"symbol": symbol, "name": "宁德主题ETF", "price": 350.0, "prev_close": 350.0, "industry": "电池"}

    monkeypatch.setattr(trading_service.market_service, "get_single_quote", fake_quote)
    monkeypatch.setattr(
        trading_service.market_service,
        "get_realtime_quotes",
        lambda symbols: [fake_quote(symbol) for symbol in symbols],
    )

    preview = trading_service.preview_order(
        db_session,
        symbol="600519.SH",
        side="BUY",
        quantity=100,
        price=100.0,
    )

    assert preview["allowed"] is True
    assert preview["risk"]["decision"] == "WARN"
    assert "Industry 电池 weight" in preview["reason"]
    assert preview["risk"]["metrics"]["industry_weight"] == pytest.approx(0.45, abs=1e-4)


def test_buy_high_volatility_warns_but_allows(monkeypatch, db_session) -> None:
    monkeypatch.setattr(
        trading_service.market_service,
        "get_single_quote",
        lambda symbol: {
            "symbol": symbol,
            "name": "高波动个股",
            "price": 100.0,
            "prev_close": 100.0,
            "volatility_20d": 0.05,
            "industry": "半导体",
        },
    )

    preview = trading_service.preview_order(
        db_session,
        symbol="688001.SH",
        side="BUY",
        quantity=100,
        price=100.0,
    )

    assert preview["allowed"] is True
    assert preview["risk"]["decision"] == "WARN"
    assert "volatility" in preview["reason"]
    assert preview["risk"]["metrics"]["volatility_20d"] == pytest.approx(0.05, abs=1e-4)


def test_generate_rebalance_plan_returns_actionable_actions(monkeypatch, db_session) -> None:
    from apps.api.app.services import scanner_service

    monkeypatch.setattr(
        scanner_service,
        "scan_potential_stocks",
        lambda **kwargs: {
            "scan_run_id": 9,
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
                    "symbol": "600519.SH",
                    "name": "贵州茅台",
                    "price": 150.0,
                    "score": 82,
                    "trade_plan": {"entry_mid": 150.0, "expected_return_pct": 6.0},
                    "ai_analysis": {"action": "BUY"},
                    "evolution": {"probability": 0.63, "expected_return_pct": 6.2},
                    "fundamental": {"info": {"industry": "白酒"}},
                    "indicators": {"vol_20d_pct": 1.8},
                },
            ],
        },
    )

    quote_map = {
            "300750.SZ": {"symbol": "300750.SZ", "name": "宁德时代", "price": 100.0, "prev_close": 100.0, "industry": "电池"},
        "600519.SH": {"symbol": "600519.SH", "name": "贵州茅台", "price": 150.0, "prev_close": 150.0, "industry": "白酒"},
    }
    monkeypatch.setattr(trading_service.market_service, "get_single_quote", lambda symbol: quote_map[symbol])
    monkeypatch.setattr(
        trading_service.market_service,
        "get_realtime_quotes",
        lambda symbols: [quote_map[symbol] for symbol in symbols if symbol in quote_map],
    )

    plan = trading_service.generate_rebalance_plan(
        db_session,
        top_n=2,
        candidate_pool=5,
        use_cache=False,
        enable_llm=False,
    )

    assert plan["ok"] is True
    assert plan["scan_run_id"] == 9
    assert len(plan["target_weights"]) == 2
    assert len(plan["actions"]) == 2
    assert all(action["action"] == "BUY" for action in plan["actions"])
    assert all(action["risk"]["allowed"] is True for action in plan["actions"])
    assert plan["summary"]["actionable_actions"] == 2


def test_generate_rebalance_plan_with_no_positive_signals_returns_no_actions(monkeypatch, db_session) -> None:
    from apps.api.app.services import scanner_service

    db_session.add(TradingPositionORM(
        account_id="PAPER",
        broker="paper",
        symbol="300750.SZ",
        name="宁德时代",
        quantity=100,
        available_quantity=100,
        avg_cost=200.0,
        market_value=20000.0,
        raw={"industry": "电池"},
    ))
    db_session.flush()

    monkeypatch.setattr(
        scanner_service,
        "scan_potential_stocks",
        lambda **kwargs: {
            "scan_run_id": 12,
            "llm_status": "disabled",
            "results": [
                {
                    "symbol": "300750.SZ",
                    "name": "宁德时代",
                    "price": 200.0,
                    "score": 20,
                    "trade_plan": {"entry_mid": 200.0, "expected_return_pct": 1.0},
                    "ai_analysis": {"action": "SELL"},
                    "evolution": {"probability": 0.40, "expected_return_pct": -1.2},
                    "fundamental": {"info": {"industry": "电池"}},
                    "indicators": {"vol_20d_pct": 2.0},
                },
            ],
        },
    )
    monkeypatch.setattr(
        trading_service.market_service,
        "get_realtime_quotes",
        lambda symbols: [{"symbol": "300750.SZ", "name": "宁德时代", "price": 200.0, "industry": "电池"}],
    )
    monkeypatch.setattr(
        trading_service.market_service,
        "get_single_quote",
        lambda symbol: {"symbol": symbol, "name": "宁德时代", "price": 200.0, "prev_close": 200.0, "industry": "电池"},
    )

    plan = trading_service.generate_rebalance_plan(
        db_session,
        top_n=1,
        candidate_pool=3,
        use_cache=False,
        enable_llm=False,
    )

    assert plan["ok"] is True
    assert plan["signals_considered"] == 0
    assert plan["actions"] == []
    assert plan["target_weights"] == []
    assert "未生成目标持仓" in plan["warnings"][0]


def test_generate_rebalance_plan_blocks_later_buy_when_plan_cash_exceeded(monkeypatch, db_session) -> None:
    from apps.api.app.services import scanner_service

    db_session.add(TradingAccountORM(
        account_id="PAPER",
        broker="paper",
        cash=10000.0,
        available_cash=10000.0,
        market_value=50000.0,
        total_asset=60000.0,
        raw={"high_water_mark": 60000.0},
    ))
    db_session.add(TradingPositionORM(
        account_id="PAPER",
        broker="paper",
        symbol="002001.SZ",
        name="已有仓位",
        quantity=250,
        available_quantity=0,
        avg_cost=200.0,
        market_value=50000.0,
        raw={"industry": "旧行业"},
    ))
    db_session.flush()

    monkeypatch.setattr(
        scanner_service,
        "scan_potential_stocks",
        lambda **kwargs: {
            "scan_run_id": 13,
            "llm_status": "disabled",
            "results": [
                {
                    "symbol": "300750.SZ",
                    "name": "宁德时代",
                    "price": 90.0,
                    "score": 88,
                    "trade_plan": {"entry_mid": 90.0, "expected_return_pct": 8.0},
                    "ai_analysis": {"action": "BUY"},
                    "evolution": {"probability": 0.72, "expected_return_pct": 8.5},
                    "fundamental": {"info": {"industry": "电池"}},
                    "indicators": {"vol_20d_pct": 2.0},
                },
                {
                    "symbol": "600519.SH",
                    "name": "贵州茅台",
                    "price": 90.0,
                    "score": 82,
                    "trade_plan": {"entry_mid": 90.0, "expected_return_pct": 6.0},
                    "ai_analysis": {"action": "BUY"},
                    "evolution": {"probability": 0.63, "expected_return_pct": 6.2},
                    "fundamental": {"info": {"industry": "白酒"}},
                    "indicators": {"vol_20d_pct": 1.8},
                },
            ],
        },
    )

    quote_map = {
        "002001.SZ": {"symbol": "002001.SZ", "name": "已有仓位", "price": 200.0, "prev_close": 200.0, "industry": "旧行业"},
        "300750.SZ": {"symbol": "300750.SZ", "name": "宁德时代", "price": 90.0, "prev_close": 90.0, "industry": "电池"},
        "600519.SH": {"symbol": "600519.SH", "name": "贵州茅台", "price": 90.0, "prev_close": 90.0, "industry": "白酒"},
    }
    monkeypatch.setattr(trading_service.market_service, "get_single_quote", lambda symbol: quote_map[symbol])
    monkeypatch.setattr(
        trading_service.market_service,
        "get_realtime_quotes",
        lambda symbols: [quote_map[symbol] for symbol in symbols if symbol in quote_map],
    )

    plan = trading_service.generate_rebalance_plan(
        db_session,
        top_n=2,
        candidate_pool=5,
        use_cache=False,
        enable_llm=False,
    )

    buy_actions = [action for action in plan["actions"] if action["action"] == "BUY"]
    assert len(buy_actions) == 2
    assert buy_actions[0]["risk"]["allowed"] is True
    assert buy_actions[1]["risk"]["allowed"] is False
    assert "plan cash budget exceeded" in buy_actions[1]["risk"]["reason"]
    assert plan["summary"]["actionable_actions"] == 1
    assert plan["summary"]["blocked_actions"] >= 1


def test_qmt_sync_upserts_account_positions_orders_and_incremental_fills(monkeypatch, db_session) -> None:
    _qmt_safe_env(monkeypatch)

    def fake_qmt_request(method: str, path: str, json: dict | None = None):
        assert method == "GET"
        if path == "/health":
            return {"status": "ok", "backend": "xtquant"}
        if path == "/account":
            return {
                "account_id": "QMT-001",
                "cash": 80000.0,
                "available_cash": 79000.0,
                "market_value": 20000.0,
                "total_asset": 100000.0,
            }
        if path == "/positions":
            return {"items": [{
                "symbol": "300750.SZ",
                "quantity": 100,
                "available_quantity": 100,
                "avg_cost": 200.0,
                "market_value": 20000.0,
            }]}
        if path == "/orders":
            return {"items": [{
                "order_id": "QMT-O-1",
                "client_order_id": "AA-qmt",
                "account_id": "QMT-001",
                "symbol": "300750.SZ",
                "side": "BUY",
                "order_type": "LIMIT",
                "quantity": 100,
                "price": 200.0,
                "status": "FILLED",
                "filled_quantity": 100,
                "avg_fill_price": 200.0,
                "submitted_at": "2024-01-01T09:30:00",
                "updated_at": "2024-01-01T09:31:00",
            }]}
        raise AssertionError(path)

    monkeypatch.setattr(trading_service, "_qmt_request", fake_qmt_request)

    first = trading_service.sync_qmt_state(db_session)
    second = trading_service.sync_qmt_state(db_session)

    assert first["positions_synced"] == 1
    assert first["orders_synced"] == 1
    assert first["fills_created"] == 1
    assert second["fills_created"] == 0
    acct = db_session.query(TradingAccountORM).filter_by(account_id="QMT-001").one()
    assert acct.total_asset == pytest.approx(100000.0)
    pos = db_session.query(TradingPositionORM).filter_by(account_id="QMT-001", symbol="300750.SZ").one()
    assert pos.quantity == 100
    order = db_session.query(TradeOrderORM).filter_by(broker_order_id="QMT-O-1").one()
    assert order.status == "FILLED"
    assert db_session.query(TradeFillORM).filter_by(order_id=order.id).count() == 1


def test_qmt_sync_invalid_positions_payload_does_not_clear_local_positions(monkeypatch, db_session) -> None:
    _qmt_safe_env(monkeypatch)
    db_session.add(TradingAccountORM(
        account_id="QMT-001",
        broker="qmt",
        cash=100000.0,
        available_cash=100000.0,
        market_value=20000.0,
        total_asset=120000.0,
        raw={},
    ))
    db_session.add(TradingPositionORM(
        account_id="QMT-001",
        broker="qmt",
        symbol="300750.SZ",
        name="宁德时代",
        quantity=100,
        available_quantity=100,
        avg_cost=200.0,
        market_value=20000.0,
        raw={},
    ))
    db_session.flush()

    def fake_qmt_request(method: str, path: str, json: dict | None = None):
        if path == "/health":
            return {"status": "ok", "backend": "xtquant"}
        if path == "/account":
            return {
                "account_id": "QMT-001",
                "cash": 100000.0,
                "available_cash": 100000.0,
                "market_value": 20000.0,
                "total_asset": 120000.0,
            }
        if path == "/positions":
            return {"error": "gateway degraded"}
        raise AssertionError(path)

    monkeypatch.setattr(trading_service, "_qmt_request", fake_qmt_request)

    with pytest.raises(RuntimeError, match="positions returned invalid payload"):
        trading_service.sync_qmt_state(db_session)

    pos = db_session.query(TradingPositionORM).filter_by(account_id="QMT-001", symbol="300750.SZ").one()
    assert pos.quantity == 100


def test_qmt_preview_requires_synced_account(monkeypatch, db_session) -> None:
    _qmt_safe_env(monkeypatch)
    monkeypatch.setattr(trading_service.market_service, "get_single_quote", lambda symbol: {"name": "宁德时代", "price": 200.0, "prev_close": 200.0})
    monkeypatch.setattr(
        trading_service,
        "_qmt_request",
        lambda method, path, json=None: {"status": "ok", "backend": "xtquant"} if path == "/health" else pytest.fail(path),
    )

    preview = trading_service.preview_order(
        db_session,
        symbol="300750.SZ",
        side="BUY",
        quantity=100,
        price=200.0,
    )

    assert preview["allowed"] is False
    assert preview["mode"] == "qmt"
    assert "sync" in preview["reason"]
    assert preview["risk"]["metrics"]["requires_sync"] is True
    assert db_session.query(TradingAccountORM).filter_by(account_id="PAPER").count() == 0


def test_qmt_preview_blocks_mock_market_data(monkeypatch, db_session) -> None:
    _qmt_safe_env(monkeypatch)
    monkeypatch.setenv("QUANT_MARKET_DATA_PROVIDER", "mock")
    from apps.api.app.core import config as config_mod
    config_mod.reset_settings_cache()
    monkeypatch.setattr(trading_service.market_service, "get_single_quote", lambda symbol: {"name": "宁德时代", "price": 200.0, "prev_close": 200.0})

    preview = trading_service.preview_order(
        db_session,
        symbol="300750.SZ",
        side="BUY",
        quantity=100,
        price=200.0,
    )

    assert preview["allowed"] is False
    assert "mock market data" in preview["reason"]
    assert preview["risk"]["checks"][0]["rule"] == "qmt_live_safety"


def test_qmt_account_reports_blocked_when_live_config_unsafe(monkeypatch, db_session) -> None:
    _qmt_safe_env(monkeypatch)
    monkeypatch.setenv("QUANT_MARKET_DATA_PROVIDER", "mock")
    from apps.api.app.core import config as config_mod
    config_mod.reset_settings_cache()

    account = trading_service.get_account(db_session)
    positions = trading_service.list_positions(db_session)

    assert account["mode"] == "qmt"
    assert account["ok"] is False
    assert account["status"] == "blocked"
    assert account["requires_live_config"] is True
    assert "mock market data" in account["reason"]
    assert positions == []


def test_qmt_order_blocks_when_auth_disabled(monkeypatch, db_session) -> None:
    _qmt_safe_env(monkeypatch)
    monkeypatch.setenv("QUANT_AUTH_ENABLED", "false")
    from apps.api.app.core import config as config_mod
    config_mod.reset_settings_cache()
    monkeypatch.setattr(trading_service.market_service, "get_single_quote", lambda symbol: {"name": "宁德时代", "price": 200.0, "prev_close": 200.0})

    order = trading_service.place_order(
        db_session,
        symbol="300750.SZ",
        side="BUY",
        quantity=100,
        price=200.0,
        name="宁德时代",
    )

    assert order["status"] == "REJECTED"
    assert order["broker"] == "qmt"
    assert "requires API authentication" in order["error_message"]
    assert db_session.query(TradeFillORM).count() == 0


def test_qmt_rebalance_plan_blocks_mock_gateway(monkeypatch, db_session) -> None:
    _qmt_safe_env(monkeypatch)
    db_session.add(TradingAccountORM(
        account_id="QMT-001",
        broker="qmt",
        cash=100000.0,
        available_cash=100000.0,
        market_value=0.0,
        total_asset=100000.0,
    ))
    db_session.flush()
    monkeypatch.setattr(
        trading_service,
        "_qmt_request",
        lambda method, path, json=None: {"status": "ok", "backend": "mock"} if path == "/health" else pytest.fail(path),
    )

    plan = trading_service.generate_rebalance_plan(db_session, enable_llm=False)

    assert plan["ok"] is False
    assert plan["requires_live_config"] is True
    assert "mock backend" in plan["reason"]
    assert plan["actions"] == []


def test_qmt_preview_uses_synced_qmt_cash_not_paper_cash(monkeypatch, db_session) -> None:
    _qmt_safe_env(monkeypatch)
    monkeypatch.setattr(trading_service.market_service, "get_single_quote", lambda symbol: {"name": "宁德时代", "price": 200.0, "prev_close": 200.0})
    monkeypatch.setattr(
        trading_service,
        "_qmt_request",
        lambda method, path, json=None: {"status": "ok", "backend": "xtquant"} if path == "/health" else pytest.fail(path),
    )
    db_session.add(TradingAccountORM(
        account_id="QMT-001",
        broker="qmt",
        cash=50000.0,
        available_cash=5000.0,
        market_value=95000.0,
        total_asset=100000.0,
    ))
    db_session.flush()

    preview = trading_service.preview_order(
        db_session,
        symbol="300750.SZ",
        side="BUY",
        quantity=100,
        price=200.0,
    )

    assert preview["allowed"] is False
    assert "insufficient cash" in preview["reason"]
    assert "available 5000.00" in preview["reason"]
    assert db_session.query(TradingAccountORM).filter_by(account_id="PAPER").count() == 0


def test_qmt_preview_uses_synced_qmt_position_for_sell(monkeypatch, db_session) -> None:
    _qmt_safe_env(monkeypatch)
    monkeypatch.setattr(trading_service.market_service, "get_single_quote", lambda symbol: {"name": "宁德时代", "price": 200.0, "prev_close": 200.0})
    monkeypatch.setattr(
        trading_service,
        "_qmt_request",
        lambda method, path, json=None: {"status": "ok", "backend": "xtquant"} if path == "/health" else pytest.fail(path),
    )
    db_session.add(TradingAccountORM(
        account_id="QMT-001",
        broker="qmt",
        cash=50000.0,
        available_cash=50000.0,
        market_value=20000.0,
        total_asset=70000.0,
    ))
    db_session.add(TradingPositionORM(
        account_id="QMT-001",
        broker="qmt",
        symbol="300750.SZ",
        name="宁德时代",
        quantity=200,
        available_quantity=200,
        avg_cost=180.0,
        market_value=40000.0,
    ))
    db_session.flush()

    preview = trading_service.preview_order(
        db_session,
        symbol="300750.SZ",
        side="SELL",
        quantity=50,
        price=200.0,
    )

    assert preview["allowed"] is True
    assert preview["risk"]["metrics"]["account_id"] == "QMT-001"
    assert preview["risk"]["metrics"]["available_quantity"] == 200
    assert db_session.query(TradingAccountORM).filter_by(account_id="PAPER").count() == 0


def test_qmt_rejected_order_is_not_forwarded_when_unsynced(monkeypatch, db_session) -> None:
    _qmt_safe_env(monkeypatch)
    monkeypatch.setattr(trading_service.market_service, "get_single_quote", lambda symbol: {"name": "宁德时代", "price": 200.0, "prev_close": 200.0})

    def fail_qmt_request(method: str, path: str, json: dict | None = None):
        if path == "/health":
            return {"status": "ok", "backend": "xtquant"}
        raise AssertionError("QMT Gateway should not be called when local account snapshot is missing")

    monkeypatch.setattr(trading_service, "_qmt_request", fail_qmt_request)

    order = trading_service.place_order(
        db_session,
        symbol="300750.SZ",
        side="BUY",
        quantity=100,
        price=200.0,
        name="宁德时代",
    )

    assert order["status"] == "REJECTED"
    assert order["broker"] == "qmt"
    assert "sync" in order["error_message"]
    assert db_session.query(TradeFillORM).count() == 0
