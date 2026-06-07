from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from apps.api.app.db.models import (
    EvolutionRunORM,
    ModelVersionORM,
    PredictionOutcomeORM,
    StockPredictionORM,
    TradeFillORM,
    TradeOrderORM,
)
from apps.api.app.services import evolution_service


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    from apps.api.app.core import config as config_mod
    config_mod.reset_settings_cache()
    yield
    config_mod.reset_settings_cache()


def _stock(symbol: str, name: str, score: int = 82) -> dict:
    return {
        "symbol": symbol,
        "name": name,
        "price": 100.0,
        "change_pct": 2.5,
        "score": score,
        "dim_scores": {"volume": 16, "momentum": 10},
        "indicators": {"ret_5d": 4.2, "ret_20d": 8.5, "vol_ratio": 2.0},
        "strategies": [{"name": "突破平台"}],
        "fundamental": {
            "quality": 18,
            "flow_score": 16,
            "industry_score": 12,
            "northbound_score": 10,
            "research_score": 9,
            "insider_reduction_score": 3,
        },
        "ai_analysis": {"action": "BUY", "confidence": 72, "risk_level": "中"},
        "trade_plan": {
            "entry_low": 99.0,
            "entry_mid": 100.0,
            "stop_loss": 94.0,
            "expected_return_pct": 5.0,
        },
    }


def _scan_output(stocks: list[dict] | None = None) -> dict:
    return {
        "scanned": 5000,
        "candidates": 120,
        "analyzed": 80,
        "tier1_count": 30,
        "tier2_count": 18,
        "tier3_count": 8,
        "llm_status": "disabled",
        "elapsed_ms": 1234,
        "params": {"top_n": 1},
        "market_status": {"sentiment": "偏强"},
        "hot_industries": [{"name": "半导体", "change_pct": 2.1}],
        "results": stocks or [_stock("300750.SZ", "宁德时代")],
    }


def _seed_validated_model_samples(
    db_session,
    model: ModelVersionORM,
    *,
    successes: int,
    failures: int,
    success_probability: float = 0.75,
    failure_probability: float = 0.25,
    success_return: float = 3.0,
    failure_return: float = -1.0,
) -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    total = successes + failures
    for i in range(total):
        success = i < successes
        pred = StockPredictionORM(
            scan_run_id=None,
            model_version_id=model.id,
            symbol=f"30{i:04d}.SZ",
            name=f"样本{i}",
            rank=i + 1,
            action="BUY",
            horizon_days=5,
            target_return_pct=3.0,
            stop_loss_pct=8.0,
            probability=success_probability if success else failure_probability,
            expected_return_pct=1.0,
            confidence=70,
            score=80,
            price_at_prediction=100.0,
            features={
                "technical": 0.8 if success else 0.3,
                "fundamental": 0.7 if success else 0.4,
                "flow": 0.7 if success else 0.2,
                "reduction_risk": 0.1 if success else 0.8,
                "ai": 0.7 if success else 0.3,
            },
            trade_plan={},
            raw_result={},
            status="validated",
            predicted_at=now,
            due_at=now,
            validated_at=now,
        )
        db_session.add(pred)
        db_session.flush()
        ret = success_return if success else failure_return
        db_session.add(PredictionOutcomeORM(
            prediction_id=pred.id,
            model_version_id=model.id,
            symbol=pred.symbol,
            horizon_days=pred.horizon_days,
            start_price=100.0,
            end_price=100.0 + ret,
            max_price=103.0 if success else 101.0,
            min_price=99.0 if success else 94.0,
            close_return_pct=ret,
            max_return_pct=3.0 if success else 1.0,
            max_drawdown_pct=-1.0 if success else -6.0,
            success=success,
            hit_target=success,
            hit_stop=not success,
            bars_checked=5,
            details={},
            validated_at=now,
        ))
    db_session.flush()


def _walk_forward_features(success: bool) -> dict:
    positive = 0.9 if success else 0.05
    reduction_risk = 0.05 if success else 0.95
    return {
        "technical": positive,
        "fundamental": positive,
        "flow": positive,
        "industry": positive,
        "northbound": positive,
        "research": positive,
        "reduction_risk": reduction_risk,
        "ai": positive,
        "strategy": positive,
        "volume": positive,
        "momentum": positive,
        "risk": positive,
        "ret_5d": 3.0 if success else -3.0,
        "ret_20d": 6.0 if success else -6.0,
        "vol_ratio": 2.0 if success else 5.5,
        "change_pct": 1.5 if success else -1.5,
        "strategy_count": 2 if success else 0,
    }


def _seed_walk_forward_samples(
    db_session,
    model: ModelVersionORM,
    *,
    total: int = 32,
) -> None:
    start = datetime(2024, 1, 1)
    for i in range(total):
        success = i % 2 == 0
        predicted_at = start + timedelta(days=i)
        ret = 5.0 if success else -4.0
        pred = StockPredictionORM(
            scan_run_id=None,
            model_version_id=model.id,
            symbol=f"WF{i:04d}.SZ",
            name=f"回放样本{i}",
            rank=i + 1,
            action="BUY",
            horizon_days=3,
            target_return_pct=3.0,
            stop_loss_pct=8.0,
            probability=0.78 if success else 0.22,
            expected_return_pct=2.0 if success else -1.0,
            confidence=70,
            score=80,
            price_at_prediction=100.0,
            features=_walk_forward_features(success),
            trade_plan={"expected_return_pct": 6.0 if success else 0.0},
            raw_result={},
            status="validated",
            predicted_at=predicted_at,
            due_at=predicted_at + timedelta(days=3),
            validated_at=predicted_at + timedelta(days=3),
        )
        db_session.add(pred)
        db_session.flush()
        db_session.add(PredictionOutcomeORM(
            prediction_id=pred.id,
            model_version_id=model.id,
            symbol=pred.symbol,
            horizon_days=pred.horizon_days,
            start_price=100.0,
            end_price=100.0 + ret,
            max_price=106.0 if success else 101.0,
            min_price=99.0 if success else 95.0,
            close_return_pct=ret,
            max_return_pct=6.0 if success else 1.0,
            max_drawdown_pct=-1.0 if success else -5.0,
            success=success,
            hit_target=success,
            hit_stop=not success,
            bars_checked=3,
            details={},
            validated_at=predicted_at + timedelta(days=3),
        ))
    db_session.flush()


def test_walk_forward_runtime_params_clamp_operator_tolerances() -> None:
    settings = SimpleNamespace(
        evolution_auto_walk_forward_min_samples=0,
        evolution_auto_walk_forward_min_dates=-5,
        evolution_auto_walk_forward_min_profitable_folds=1.5,
        evolution_auto_walk_forward_return_tolerance=2.0,
        evolution_auto_walk_forward_consistency_tolerance=-0.25,
        evolution_auto_walk_forward_drawdown_tolerance=9.0,
    )

    params = evolution_service._walk_forward_runtime_params(settings)

    assert params["min_samples"] == 1
    assert params["min_dates"] == 1
    assert params["min_profitable_folds"] == 1.0
    assert params["return_tolerance"] == 1.0
    assert params["consistency_tolerance"] == 0.0
    assert params["drawdown_tolerance"] == 1.0


def test_record_scan_result_creates_model_run_and_predictions(db_session) -> None:
    meta = evolution_service.record_scan_result(_scan_output(), db=db_session)

    assert meta["recorded"] is True
    assert meta["predictions_created"] == 4
    assert db_session.query(ModelVersionORM).count() == 1
    preds = db_session.query(StockPredictionORM).all()
    assert {p.horizon_days for p in preds} == {3, 5, 10, 20}
    assert all(p.symbol == "300750.SZ" for p in preds)
    assert all(0 < p.probability < 1 for p in preds)
    assert all("industry" in p.features for p in preds)
    assert all("northbound" in p.features for p in preds)
    assert all("research" in p.features for p in preds)
    assert all("reduction_risk" in p.features for p in preds)


def test_enrich_scan_results_can_target_specific_horizon(db_session) -> None:
    result = evolution_service.enrich_scan_results_with_model(
        [_stock("300750.SZ", "宁德时代")],
        db=db_session,
        target_horizon_days=5,
    )

    evo = result["results"][0]["evolution"]
    assert evo["ranking_mode"] == "requested_horizon"
    assert evo["requested_horizon_days"] == 5
    assert evo["best_horizon_days"] == 5
    assert {row["horizon_days"] for row in evo["probabilities_by_horizon"]} == {3, 5, 10, 20}


def test_validate_predictions_marks_success(monkeypatch, db_session) -> None:
    evolution_service.record_scan_result(_scan_output(), db=db_session)
    pred = db_session.query(StockPredictionORM).filter(StockPredictionORM.horizon_days == 3).first()
    pred.predicted_at = datetime(2024, 1, 1)
    pred.due_at = datetime(2024, 1, 4)
    db_session.flush()

    def fake_kline(symbol: str, period: str = "daily", count: int = 120):
        assert symbol == "300750.SZ"
        return [
            {"date": "2024-01-02", "open": 100, "high": 101, "low": 99, "close": 100.5},
            {"date": "2024-01-03", "open": 101, "high": 103.5, "low": 100, "close": 102.0},
            {"date": "2024-01-04", "open": 102, "high": 104, "low": 101, "close": 103.0},
        ]

    monkeypatch.setattr(evolution_service.market_service, "get_kline", fake_kline)

    result = evolution_service.validate_predictions(horizon_days=3, force=True, db=db_session)

    assert result["validated"] == 1
    db_session.refresh(pred)
    outcome = db_session.query(PredictionOutcomeORM).filter_by(prediction_id=pred.id).one()
    assert pred.status == "validated"
    assert outcome.success is True
    assert outcome.hit_target is True
    assert outcome.close_return_pct > 0


def test_evolve_model_can_promote_candidate(db_session) -> None:
    evolution_service.record_scan_result(_scan_output(), db=db_session)
    preds = db_session.query(StockPredictionORM).all()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for i, pred in enumerate(preds):
        pred.status = "validated"
        pred.validated_at = now
        db_session.add(PredictionOutcomeORM(
            prediction_id=pred.id,
            model_version_id=pred.model_version_id,
            symbol=pred.symbol,
            horizon_days=pred.horizon_days,
            start_price=100,
            end_price=104 if i % 2 == 0 else 98,
            max_price=105 if i % 2 == 0 else 101,
            min_price=99 if i % 2 == 0 else 92,
            close_return_pct=4 if i % 2 == 0 else -2,
            max_return_pct=5 if i % 2 == 0 else 1,
            max_drawdown_pct=-1 if i % 2 == 0 else -8,
            success=i % 2 == 0,
            hit_target=i % 2 == 0,
            hit_stop=i % 2 == 1,
            bars_checked=pred.horizon_days,
            details={},
            validated_at=now,
        ))
    db_session.flush()

    result = evolution_service.evolve_model(min_samples=2, promote=True, db=db_session)

    assert result["status"] == "completed"
    assert result["promoted"] is True
    assert result["candidate_model"]["status"] == "active"
    active = db_session.query(ModelVersionORM).filter(ModelVersionORM.status == "active").one()
    assert active.version == result["candidate_model"]["version"]
    assert active.config["weights"]["reduction_risk"] < 0
    assert result["holdout_passed"] is True
    assert result["walk_forward_passed"] is True
    assert result["walk_forward_validation"]["ready"] is False


def test_evolve_model_does_not_promote_when_holdout_gate_fails(monkeypatch, db_session) -> None:
    evolution_service.record_scan_result(_scan_output(), db=db_session)
    preds = db_session.query(StockPredictionORM).order_by(StockPredictionORM.id.asc()).all()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for i, pred in enumerate(preds):
        pred.status = "validated"
        pred.validated_at = now
        success = i < 3
        db_session.add(PredictionOutcomeORM(
            prediction_id=pred.id,
            model_version_id=pred.model_version_id,
            symbol=pred.symbol,
            horizon_days=pred.horizon_days,
            start_price=100,
            end_price=104 if success else 97,
            max_price=105 if success else 101,
            min_price=99 if success else 94,
            close_return_pct=4 if success else -3,
            max_return_pct=5 if success else 1,
            max_drawdown_pct=-1 if success else -8,
            success=success,
            hit_target=success,
            hit_stop=not success,
            bars_checked=pred.horizon_days,
            details={},
            validated_at=now,
        ))
    db_session.flush()

    bad_config = {
        **evolution_service.DEFAULT_MODEL_CONFIG,
        "weights": {**evolution_service.DEFAULT_MODEL_CONFIG["weights"], "technical": 1.0, "reduction_risk": -0.02},
        "horizon_bias": {"3": 0.12, "5": 0.12, "10": 0.12, "20": 0.12},
    }
    monkeypatch.setattr(evolution_service, "_adjust_weights", lambda config, pairs: bad_config)

    result = evolution_service.evolve_model(min_samples=2, promote=True, db=db_session)

    assert result["promoted"] is False
    assert result["holdout_passed"] is False
    assert result["candidate_model"]["status"] == "candidate"
    active = db_session.query(ModelVersionORM).filter(ModelVersionORM.status == "active").one()
    assert active.id == result["active_model"]["id"]
    assert active.parent_id is None
    assert result["holdout_reasons"]


def test_compare_scan_runs_detects_new_overlap_and_dropped(db_session) -> None:
    first = evolution_service.record_scan_result(
        _scan_output([
            _stock("300750.SZ", "宁德时代"),
            _stock("000001.SZ", "平安银行"),
        ]),
        db=db_session,
    )
    second = evolution_service.record_scan_result(
        _scan_output([
            _stock("300750.SZ", "宁德时代"),
            _stock("600519.SH", "贵州茅台"),
        ]),
        db=db_session,
    )

    comparison = evolution_service.compare_scan_runs(
        base_run_id=second["scan_run_id"],
        compare_run_id=first["scan_run_id"],
        db=db_session,
    )

    assert comparison["ready"] is True
    assert comparison["counts"] == {"base": 2, "compare": 2, "overlap": 1, "new": 1, "dropped": 1}
    assert [item["symbol"] for item in comparison["overlap"]] == ["300750.SZ"]
    assert [item["symbol"] for item in comparison["new"]] == ["600519.SH"]
    assert [item["symbol"] for item in comparison["dropped"]] == ["000001.SZ"]


def test_record_trade_fills_creates_execution_predictions_once(db_session) -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    order = TradeOrderORM(
        client_order_id="AA-fill",
        broker_order_id="AA-fill",
        account_id="PAPER",
        broker="paper",
        symbol="300750.SZ",
        name="宁德时代",
        side="BUY",
        order_type="LIMIT",
        quantity=100,
        price=200.0,
        status="FILLED",
        filled_quantity=100,
        avg_fill_price=200.0,
        source="test",
        strategy="scanner",
        reason="execution-aware evolution",
        raw={},
        submitted_at=now,
        updated_at=now,
    )
    db_session.add(order)
    db_session.flush()
    fill = TradeFillORM(
        order_id=order.id,
        broker_order_id=order.broker_order_id,
        symbol=order.symbol,
        side="BUY",
        quantity=100,
        price=200.0,
        amount=20000.0,
        fee=0.0,
        filled_at=now,
        raw={},
    )
    db_session.add(fill)
    db_session.flush()

    first = evolution_service.record_trade_fills(db=db_session)
    second = evolution_service.record_trade_fills(db=db_session)

    assert first["checked"] == 1
    assert first["predictions_created"] == 3
    assert first["exits_recorded"] == 0
    assert second["checked"] == 0
    preds = [p for p in db_session.query(StockPredictionORM).all() if (p.raw_result or {}).get("source") == "trade_fill"]
    assert {p.horizon_days for p in preds} == {5, 10, 20}
    assert all(p.price_at_prediction == 200.0 for p in preds)
    db_session.refresh(fill)
    assert fill.evolution_recorded_at is not None


def test_record_trade_fills_validates_execution_predictions_on_sell(db_session) -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    buy_order = TradeOrderORM(
        client_order_id="AA-buy",
        broker_order_id="AA-buy",
        account_id="PAPER",
        broker="paper",
        symbol="300750.SZ",
        name="宁德时代",
        side="BUY",
        order_type="LIMIT",
        quantity=100,
        price=200.0,
        status="FILLED",
        filled_quantity=100,
        avg_fill_price=200.0,
        source="test",
        strategy="scanner",
        reason="buy",
        raw={},
        submitted_at=now,
        updated_at=now,
    )
    db_session.add(buy_order)
    db_session.flush()
    buy_fill = TradeFillORM(
        order_id=buy_order.id,
        broker_order_id=buy_order.broker_order_id,
        symbol=buy_order.symbol,
        side="BUY",
        quantity=100,
        price=200.0,
        amount=20000.0,
        fee=0.0,
        filled_at=now,
        raw={},
    )
    db_session.add(buy_fill)
    db_session.flush()

    first = evolution_service.record_trade_fills(db=db_session)
    assert first["predictions_created"] == 3
    preds = db_session.query(StockPredictionORM).filter(StockPredictionORM.symbol == "300750.SZ").all()
    assert len(preds) == 3
    assert all(p.status == "pending" for p in preds)

    sell_time = now + timedelta(days=2)
    sell_order = TradeOrderORM(
        client_order_id="AA-sell",
        broker_order_id="AA-sell",
        account_id="PAPER",
        broker="paper",
        symbol="300750.SZ",
        name="宁德时代",
        side="SELL",
        order_type="LIMIT",
        quantity=100,
        price=220.0,
        status="FILLED",
        filled_quantity=100,
        avg_fill_price=220.0,
        source="test",
        strategy="scanner",
        reason="take profit",
        raw={},
        submitted_at=sell_time,
        updated_at=sell_time,
    )
    db_session.add(sell_order)
    db_session.flush()
    sell_fill = TradeFillORM(
        order_id=sell_order.id,
        broker_order_id=sell_order.broker_order_id,
        symbol=sell_order.symbol,
        side="SELL",
        quantity=100,
        price=220.0,
        amount=22000.0,
        fee=0.0,
        filled_at=sell_time,
        raw={},
    )
    db_session.add(sell_fill)
    db_session.flush()

    second = evolution_service.record_trade_fills(db=db_session)
    third = evolution_service.record_trade_fills(db=db_session)

    assert second["checked"] == 1
    assert second["predictions_created"] == 0
    assert second["exits_recorded"] == 3
    assert third["checked"] == 0
    outcomes = db_session.query(PredictionOutcomeORM).all()
    assert len(outcomes) == 3
    assert all(o.success is True for o in outcomes)
    assert all(o.close_return_pct == 10.0 for o in outcomes)
    assert all((o.details or {}).get("source") == "trade_exit" for o in outcomes)
    assert all((o.details or {}).get("sell_fill_id") == sell_fill.id for o in outcomes)
    assert all(p.status == "validated" for p in preds)
    db_session.refresh(sell_fill)
    assert sell_fill.evolution_recorded_at is not None


def test_record_trade_fills_settles_execution_predictions_fifo_by_buy_fill_group(db_session) -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    buy1 = TradeOrderORM(
        client_order_id="AA-buy-1",
        broker_order_id="AA-buy-1",
        account_id="PAPER",
        broker="paper",
        symbol="300750.SZ",
        name="宁德时代",
        side="BUY",
        order_type="LIMIT",
        quantity=200,
        price=200.0,
        status="FILLED",
        filled_quantity=200,
        avg_fill_price=200.0,
        source="test",
        strategy="scanner",
        reason="first entry",
        raw={},
        submitted_at=now,
        updated_at=now,
    )
    buy2 = TradeOrderORM(
        client_order_id="AA-buy-2",
        broker_order_id="AA-buy-2",
        account_id="PAPER",
        broker="paper",
        symbol="300750.SZ",
        name="宁德时代",
        side="BUY",
        order_type="LIMIT",
        quantity=100,
        price=210.0,
        status="FILLED",
        filled_quantity=100,
        avg_fill_price=210.0,
        source="test",
        strategy="scanner",
        reason="second entry",
        raw={},
        submitted_at=now + timedelta(minutes=5),
        updated_at=now + timedelta(minutes=5),
    )
    db_session.add_all([buy1, buy2])
    db_session.flush()

    buy_fill1 = TradeFillORM(
        order_id=buy1.id,
        broker_order_id=buy1.broker_order_id,
        symbol=buy1.symbol,
        side="BUY",
        quantity=200,
        price=200.0,
        amount=40000.0,
        fee=0.0,
        filled_at=now,
        raw={},
    )
    buy_fill2 = TradeFillORM(
        order_id=buy2.id,
        broker_order_id=buy2.broker_order_id,
        symbol=buy2.symbol,
        side="BUY",
        quantity=100,
        price=210.0,
        amount=21000.0,
        fee=0.0,
        filled_at=now + timedelta(minutes=5),
        raw={},
    )
    db_session.add_all([buy_fill1, buy_fill2])
    db_session.flush()

    first = evolution_service.record_trade_fills(db=db_session)
    assert first["predictions_created"] == 6

    sell1_time = now + timedelta(days=2)
    sell1 = TradeOrderORM(
        client_order_id="AA-sell-1",
        broker_order_id="AA-sell-1",
        account_id="PAPER",
        broker="paper",
        symbol="300750.SZ",
        name="宁德时代",
        side="SELL",
        order_type="LIMIT",
        quantity=100,
        price=220.0,
        status="FILLED",
        filled_quantity=100,
        avg_fill_price=220.0,
        source="test",
        strategy="scanner",
        reason="partial take profit",
        raw={},
        submitted_at=sell1_time,
        updated_at=sell1_time,
    )
    db_session.add(sell1)
    db_session.flush()
    sell_fill1 = TradeFillORM(
        order_id=sell1.id,
        broker_order_id=sell1.broker_order_id,
        symbol=sell1.symbol,
        side="SELL",
        quantity=100,
        price=220.0,
        amount=22000.0,
        fee=0.0,
        filled_at=sell1_time,
        raw={},
    )
    db_session.add(sell_fill1)
    db_session.flush()

    second = evolution_service.record_trade_fills(db=db_session)

    assert second["exits_recorded"] == 3
    outcomes = db_session.query(PredictionOutcomeORM).all()
    assert len(outcomes) == 3
    assert {int((o.details or {}).get("buy_fill_id")) for o in outcomes} == {buy_fill1.id}
    assert all((o.details or {}).get("matched_quantity") == 100 for o in outcomes)
    assert all((o.details or {}).get("remaining_before") == 200 for o in outcomes)
    assert all((o.details or {}).get("remaining_after") == 100 for o in outcomes)
    pending = db_session.query(StockPredictionORM).filter(StockPredictionORM.status == "pending").all()
    assert len(pending) == 3
    assert {(p.raw_result or {}).get("fill_id") for p in pending} == {buy_fill2.id}

    sell2_time = now + timedelta(days=3)
    sell2 = TradeOrderORM(
        client_order_id="AA-sell-2",
        broker_order_id="AA-sell-2",
        account_id="PAPER",
        broker="paper",
        symbol="300750.SZ",
        name="宁德时代",
        side="SELL",
        order_type="LIMIT",
        quantity=100,
        price=230.0,
        status="FILLED",
        filled_quantity=100,
        avg_fill_price=230.0,
        source="test",
        strategy="scanner",
        reason="second take profit",
        raw={},
        submitted_at=sell2_time,
        updated_at=sell2_time,
    )
    db_session.add(sell2)
    db_session.flush()
    sell_fill2 = TradeFillORM(
        order_id=sell2.id,
        broker_order_id=sell2.broker_order_id,
        symbol=sell2.symbol,
        side="SELL",
        quantity=100,
        price=230.0,
        amount=23000.0,
        fee=0.0,
        filled_at=sell2_time,
        raw={},
    )
    db_session.add(sell_fill2)
    db_session.flush()

    third = evolution_service.record_trade_fills(db=db_session)

    assert third["exits_recorded"] == 3
    outcomes = db_session.query(PredictionOutcomeORM).order_by(PredictionOutcomeORM.id.asc()).all()
    assert len(outcomes) == 6
    latest = outcomes[3:]
    assert {int((o.details or {}).get("buy_fill_id")) for o in latest} == {buy_fill2.id}
    assert all((o.details or {}).get("matched_quantity") == 100 for o in latest)
    assert db_session.query(StockPredictionORM).filter(StockPredictionORM.status == "pending").count() == 0


def test_auto_evolve_cycle_blocks_when_quality_gate_fails(monkeypatch, db_session) -> None:
    monkeypatch.setenv("QUANT_EVOLUTION_AUTO_EVOLVE_MIN_SAMPLES", "4")
    monkeypatch.setenv("QUANT_EVOLUTION_AUTO_PROMOTE_MIN_SUCCESS_RATE", "0.80")
    monkeypatch.setenv("QUANT_EVOLUTION_AUTO_PROMOTE_MIN_AVG_RETURN_PCT", "0")
    monkeypatch.setenv("QUANT_EVOLUTION_AUTO_PROMOTE_MAX_BRIER_SCORE", "0.30")
    monkeypatch.setenv("QUANT_EVOLUTION_AUTO_PROMOTE_MAX_CALIBRATION_ERROR", "0.30")
    from apps.api.app.core import config as config_mod
    config_mod.reset_settings_cache()
    model = evolution_service.ensure_active_model(db_session)
    _seed_validated_model_samples(db_session, model, successes=2, failures=2)

    result = evolution_service.auto_evolve_cycle(db=db_session)

    assert result["status"] == "auto_blocked"
    assert any("success_rate" in reason for reason in result["reasons"])
    db_session.refresh(model)
    assert model.status == "active"
    run = db_session.query(EvolutionRunORM).order_by(EvolutionRunORM.id.desc()).first()
    assert run.status == "auto_blocked"
    assert run.promoted is False


def test_auto_evolve_cycle_promotes_when_quality_gate_passes(monkeypatch, db_session) -> None:
    monkeypatch.setenv("QUANT_EVOLUTION_AUTO_EVOLVE_MIN_SAMPLES", "4")
    monkeypatch.setenv("QUANT_EVOLUTION_AUTO_PROMOTE_MIN_SUCCESS_RATE", "0.70")
    monkeypatch.setenv("QUANT_EVOLUTION_AUTO_PROMOTE_MIN_AVG_RETURN_PCT", "0")
    monkeypatch.setenv("QUANT_EVOLUTION_AUTO_PROMOTE_MAX_BRIER_SCORE", "0.20")
    monkeypatch.setenv("QUANT_EVOLUTION_AUTO_PROMOTE_MAX_CALIBRATION_ERROR", "0.20")
    from apps.api.app.core import config as config_mod
    config_mod.reset_settings_cache()
    model = evolution_service.ensure_active_model(db_session)
    _seed_validated_model_samples(db_session, model, successes=4, failures=1)

    result = evolution_service.auto_evolve_cycle(db=db_session)

    assert result["status"] == "auto_promoted"
    assert result["previous_model"]["status"] == "retired"
    assert result["active_model"]["status"] == "active"
    active = db_session.query(ModelVersionORM).filter(ModelVersionORM.status == "active").one()
    assert active.parent_id == model.id
    assert active.version == result["active_model"]["version"]
    assert active.config["weights"]["reduction_risk"] < 0
    assert result["candidate_holdout_metrics"]["sample_count"] >= 1


def test_auto_evolve_cycle_rolls_back_degraded_child(monkeypatch, db_session) -> None:
    monkeypatch.setenv("QUANT_EVOLUTION_AUTO_EVOLVE_MIN_SAMPLES", "100")
    monkeypatch.setenv("QUANT_EVOLUTION_AUTO_ROLLBACK_MIN_SAMPLES", "3")
    monkeypatch.setenv("QUANT_EVOLUTION_AUTO_ROLLBACK_MIN_SUCCESS_RATE", "0.50")
    monkeypatch.setenv("QUANT_EVOLUTION_AUTO_ROLLBACK_MIN_AVG_RETURN_PCT", "0")
    monkeypatch.setenv("QUANT_EVOLUTION_AUTO_ROLLBACK_MAX_BRIER_SCORE", "0.50")
    from apps.api.app.core import config as config_mod
    config_mod.reset_settings_cache()
    parent = evolution_service.ensure_active_model(db_session)
    parent.status = "retired"
    child = ModelVersionORM(
        name=parent.name,
        version="rule-v2",
        status="active",
        parent_id=parent.id,
        config=parent.config,
        metrics={},
        note="degraded child",
        activated_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db_session.add(child)
    db_session.flush()
    _seed_validated_model_samples(
        db_session,
        child,
        successes=0,
        failures=3,
        success_probability=0.8,
        failure_probability=0.8,
        failure_return=-4.0,
    )

    result = evolution_service.auto_evolve_cycle(db=db_session)

    assert result["status"] == "auto_rolled_back"
    db_session.refresh(parent)
    db_session.refresh(child)
    assert parent.status == "active"
    assert child.status == "rolled_back"
    assert result["active_model"]["version"] == parent.version


def test_auto_evolve_cycle_blocks_when_candidate_fails_holdout(monkeypatch, db_session) -> None:
    monkeypatch.setenv("QUANT_EVOLUTION_AUTO_EVOLVE_MIN_SAMPLES", "4")
    monkeypatch.setenv("QUANT_EVOLUTION_AUTO_PROMOTE_MIN_SUCCESS_RATE", "0.70")
    monkeypatch.setenv("QUANT_EVOLUTION_AUTO_PROMOTE_MIN_AVG_RETURN_PCT", "0")
    monkeypatch.setenv("QUANT_EVOLUTION_AUTO_PROMOTE_MAX_BRIER_SCORE", "0.20")
    monkeypatch.setenv("QUANT_EVOLUTION_AUTO_PROMOTE_MAX_CALIBRATION_ERROR", "0.20")
    from apps.api.app.core import config as config_mod
    config_mod.reset_settings_cache()
    model = evolution_service.ensure_active_model(db_session)
    _seed_validated_model_samples(db_session, model, successes=4, failures=1)

    bad_config = {
        **evolution_service.DEFAULT_MODEL_CONFIG,
        "weights": {**evolution_service.DEFAULT_MODEL_CONFIG["weights"], "technical": 1.0, "reduction_risk": -0.02},
        "horizon_bias": {"3": 0.15, "5": 0.15, "10": 0.15, "20": 0.15},
    }
    monkeypatch.setattr(evolution_service, "_adjust_weights", lambda config, pairs: bad_config)

    result = evolution_service.auto_evolve_cycle(db=db_session)

    assert result["status"] == "auto_blocked"
    assert any("candidate holdout" in reason for reason in result["reasons"])
    db_session.refresh(model)
    assert model.status == "active"
    assert db_session.query(ModelVersionORM).filter(ModelVersionORM.status == "candidate").count() == 0


def test_auto_evolve_cycle_blocks_when_candidate_fails_walk_forward(monkeypatch, db_session) -> None:
    monkeypatch.setenv("QUANT_EVOLUTION_AUTO_EVOLVE_MIN_SAMPLES", "20")
    monkeypatch.setenv("QUANT_EVOLUTION_AUTO_PROMOTE_MIN_SUCCESS_RATE", "0.45")
    monkeypatch.setenv("QUANT_EVOLUTION_AUTO_PROMOTE_MIN_AVG_RETURN_PCT", "0")
    monkeypatch.setenv("QUANT_EVOLUTION_AUTO_PROMOTE_MAX_BRIER_SCORE", "0.20")
    monkeypatch.setenv("QUANT_EVOLUTION_AUTO_PROMOTE_MAX_CALIBRATION_ERROR", "0.30")
    from apps.api.app.core import config as config_mod
    config_mod.reset_settings_cache()
    model = evolution_service.ensure_active_model(db_session)
    _seed_walk_forward_samples(db_session, model, total=32)

    bad_weights = {key: 0.02 for key in evolution_service.DEFAULT_MODEL_CONFIG["weights"]}
    bad_weights["reduction_risk"] = 1.0
    bad_config = {
        **evolution_service.DEFAULT_MODEL_CONFIG,
        "weights": bad_weights,
    }
    monkeypatch.setattr(evolution_service, "_adjust_weights", lambda config, pairs: bad_config)
    monkeypatch.setattr(evolution_service, "_candidate_holdout_gate", lambda candidate, baseline: (True, []))
    monkeypatch.setattr(evolution_service, "_candidate_signal_quality_gate", lambda candidate, baseline: (True, []))

    result = evolution_service.auto_evolve_cycle(db=db_session)

    assert result["status"] == "auto_blocked"
    assert result["walk_forward_validation"]["ready"] is True
    assert any("walk-forward" in reason for reason in result["reasons"])
    assert (
        result["walk_forward_validation"]["candidate"]["oos_total_return_mean"]
        < result["walk_forward_validation"]["baseline"]["oos_total_return_mean"]
    )
    db_session.refresh(model)
    assert model.status == "active"


def test_evolve_model_does_not_promote_when_signal_quality_fails(monkeypatch, db_session) -> None:
    evolution_service.record_scan_result(_scan_output(), db=db_session)
    preds = db_session.query(StockPredictionORM).order_by(StockPredictionORM.id.asc()).all()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for i, pred in enumerate(preds):
        pred.status = "validated"
        pred.validated_at = now
        success = i % 2 == 0
        realized = 4 if success else -3
        db_session.add(PredictionOutcomeORM(
            prediction_id=pred.id,
            model_version_id=pred.model_version_id,
            symbol=pred.symbol,
            horizon_days=pred.horizon_days,
            start_price=100,
            end_price=100 + realized,
            max_price=105 if success else 101,
            min_price=99 if success else 94,
            close_return_pct=realized,
            max_return_pct=5 if success else 1,
            max_drawdown_pct=-1 if success else -8,
            success=success,
            hit_target=success,
            hit_stop=not success,
            bars_checked=pred.horizon_days,
            details={},
            validated_at=now,
        ))
    db_session.flush()

    monkeypatch.setattr(
        evolution_service,
        "_compute_signal_quality_for_pairs",
        lambda pairs, config: {
            "sample_count": len(pairs),
            "ready": True,
            "mean_ic": 0.0 if config is not evolution_service.DEFAULT_MODEL_CONFIG else 0.08,
            "mean_win_rate": 0.5 if config is not evolution_service.DEFAULT_MODEL_CONFIG else 0.66,
            "useful_horizon_count": 0 if config is not evolution_service.DEFAULT_MODEL_CONFIG else 1,
            "by_horizon": [],
        },
    )

    result = evolution_service.evolve_model(min_samples=2, promote=True, db=db_session)

    assert result["promoted"] is False
    assert result["signal_quality_passed"] is False
    assert any("candidate signal" in reason for reason in result["signal_quality_reasons"])
    active = db_session.query(ModelVersionORM).filter(ModelVersionORM.status == "active").one()
    assert active.id == result["active_model"]["id"]


def test_auto_scan_params_from_settings_maps_scanner_args() -> None:
    settings = SimpleNamespace(
        evolution_auto_scan_top_n=15,
        evolution_auto_scan_min_score=55,
        evolution_auto_scan_candidate_pool=120,
        evolution_auto_scan_enable_fundamental=True,
        evolution_auto_scan_enable_llm=False,
        evolution_auto_scan_llm_top_n=6,
        evolution_auto_scan_target_horizon_days=0,
    )

    params = evolution_service._auto_scan_params_from_settings(settings)

    assert params == {
        "top_n": 15,
        "min_score": 55,
        "candidate_pool": 120,
        "use_cache": False,
        "enable_fundamental": True,
        "enable_llm": False,
        "llm_top_n": 6,
        "target_horizon_days": None,
    }


def test_run_auto_scan_once_records_last_run(monkeypatch) -> None:
    from apps.api.app.core import config as config_mod
    from apps.api.app.services import scanner_service

    settings = SimpleNamespace(
        evolution_auto_scan_top_n=2,
        evolution_auto_scan_min_score=60,
        evolution_auto_scan_candidate_pool=10,
        evolution_auto_scan_enable_fundamental=False,
        evolution_auto_scan_enable_llm=False,
        evolution_auto_scan_llm_top_n=1,
        evolution_auto_scan_target_horizon_days=5,
    )
    captured = {}

    def fake_scan(**kwargs):
        captured.update(kwargs)
        return {
            "scan_run_id": 42,
            "results": [_stock("300750.SZ", "宁德时代"), _stock("000001.SZ", "平安银行")],
            "evolution": {"predictions_created": 8},
            "llm_status": "disabled",
        }

    monkeypatch.setattr(config_mod, "get_evolution_settings", lambda: settings)
    monkeypatch.setattr(scanner_service, "scan_potential_stocks", fake_scan)
    monkeypatch.setattr(evolution_service, "_auto_scan_last_run", None)

    result = evolution_service.run_auto_scan_once()

    assert captured["top_n"] == 2
    assert captured["use_cache"] is False
    assert captured["enable_llm"] is False
    assert captured["target_horizon_days"] == 5
    assert result["ok"] is True
    assert result["scan_run_id"] == 42
    assert result["results"] == 2
    assert result["predictions_created"] == 8
    assert evolution_service._auto_scan_last_run == result


def test_run_validation_cycle_once_records_compact_status(monkeypatch) -> None:
    monkeypatch.setattr(
        evolution_service,
        "record_trade_fills",
        lambda limit: {"checked": limit, "predictions_created": 2, "exits_recorded": 1},
    )
    monkeypatch.setattr(
        evolution_service,
        "validate_predictions",
        lambda limit: {"checked": limit, "validated": 3, "skipped": 4, "errors": 0},
    )
    monkeypatch.setattr(
        evolution_service,
        "auto_evolve_cycle",
        lambda: {
            "status": "auto_blocked",
            "evaluated_predictions": 42,
            "reasons": ["success_rate 0.4 < 0.52"],
            "active_model": {"version": "rule-v1"},
            "metrics": {"large_payload": True},
        },
    )
    monkeypatch.setattr(evolution_service, "_validation_last_run", None)

    result = evolution_service.run_validation_cycle_once(limit=17)

    assert result["ok"] is True
    assert result["trade_result"]["checked"] == 17
    assert result["validation_result"]["validated"] == 3
    assert result["auto_cycle_result"] == {
        "status": "auto_blocked",
        "evaluated_predictions": 42,
        "reasons": ["success_rate 0.4 < 0.52"],
        "active_model_version": "rule-v1",
    }
    assert evolution_service.validation_loop_status()["validation_last_run"] == result


def test_notify_evolution_failure_sends_and_rate_limits(monkeypatch) -> None:
    from apps.api.app.services import feishu_service

    sent_messages = []
    settings = SimpleNamespace(
        evolution_failure_alert_enabled=True,
        evolution_failure_alert_cooldown_seconds=60,
    )
    started_at = datetime(2026, 1, 1, 9, 0, 0)

    def fake_send(title, content, color="blue"):
        sent_messages.append({"title": title, "content": content, "color": color})
        return True

    monkeypatch.setattr(feishu_service, "send_feishu", fake_send)
    monkeypatch.setattr(evolution_service, "_failure_alert_last_sent_at", {})
    monkeypatch.setattr(evolution_service, "_failure_alert_last_event", None)

    first = evolution_service._notify_evolution_failure(
        "auto_scan",
        RuntimeError("provider timeout"),
        context={"results": 0, "secret": "hidden"},
        settings=settings,
        now=started_at,
    )
    second = evolution_service._notify_evolution_failure(
        "auto_scan",
        RuntimeError("provider timeout again"),
        settings=settings,
        now=started_at + timedelta(seconds=30),
    )

    assert first["alert_status"] == "sent"
    assert first["context"] == {"results": 0}
    assert len(sent_messages) == 1
    assert sent_messages[0]["title"] == "AlphaAgent 自动采样失败"
    assert sent_messages[0]["color"] == "red"
    assert "provider timeout" in sent_messages[0]["content"]
    assert second["alert_status"] == "suppressed"
    assert second["last_sent_at"] == started_at.isoformat()
    assert evolution_service.validation_loop_status()["failure_alert_last_event"] == second


def test_notify_evolution_failure_can_be_disabled(monkeypatch) -> None:
    from apps.api.app.services import feishu_service

    settings = SimpleNamespace(
        evolution_failure_alert_enabled=False,
        evolution_failure_alert_cooldown_seconds=60,
    )

    monkeypatch.setattr(feishu_service, "send_feishu", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not send")))
    monkeypatch.setattr(evolution_service, "_failure_alert_last_event", None)

    event = evolution_service._notify_evolution_failure(
        "validation_cycle",
        "database locked",
        settings=settings,
    )

    assert event["alert_status"] == "disabled"
    assert evolution_service.validation_loop_status()["failure_alert_last_event"] == event


def test_daily_validate_time_helpers_normalize_and_schedule() -> None:
    now = datetime(2026, 6, 7, 14, 15, 30)

    assert evolution_service._normalize_validate_time("9:5") == "09:05"
    assert evolution_service._normalize_validate_time("25:00") == ""
    assert evolution_service._seconds_until_daily_time("14:20", now=now) == 270
    assert evolution_service._seconds_until_daily_time("14:10", now=now) == 86070
