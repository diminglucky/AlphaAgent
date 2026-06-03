"""推荐结果验证与模型进化服务。

第一版采用可解释的规则权重校准：先把每次扫描结果变成预测样本，
再用到期后的真实表现反向调整概率模型。后续可以在同一接口下替换为 ML。
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import math
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Any

from sqlalchemy.orm import Session

from apps.api.app.db.models import (
    EvolutionRunORM,
    ModelMetricORM,
    ModelVersionORM,
    PredictionOutcomeORM,
    ScanRunORM,
    StockPredictionORM,
    TradeFillORM,
    TradeOrderORM,
)
from apps.api.app.db.session import session_scope
from apps.api.app.services import market_service

log = logging.getLogger("quant.evolution")
_validation_task: asyncio.Task | None = None

DEFAULT_MODEL_NAME = "scanner-evolution"
DEFAULT_MODEL_VERSION = "rule-v1"
DEFAULT_MODEL_CONFIG: dict[str, Any] = {
    "horizons": [3, 5, 10, 20],
    "targets": {"3": 2.0, "5": 3.0, "10": 5.0, "20": 8.0},
    "stop_loss_pct": 8.0,
    "weights": {
        "technical": 0.34,
        "fundamental": 0.12,
        "flow": 0.11,
        "industry": 0.06,
        "northbound": 0.06,
        "research": 0.04,
        "reduction_risk": -0.06,
        "ai": 0.18,
        "strategy": 0.07,
        "volume": 0.05,
        "momentum": 0.04,
        "risk": 0.03,
    },
    "horizon_bias": {"3": 0.0, "5": 0.0, "10": 0.0, "20": 0.0},
    "min_samples_to_evolve": 30,
}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _ctx(db: Session | None):
    return nullcontext(db) if db is not None else session_scope()


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _f(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        n = float(v)
        if math.isnan(n) or math.isinf(n):
            return default
        return n
    except Exception:
        return default


def _jsonable(value: Any) -> Any:
    """Make nested scanner payloads safe for SQLAlchemy JSON on SQLite."""
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def ensure_active_model(db: Session) -> ModelVersionORM:
    """Return the active model, creating the default rule model if needed."""
    model = (
        db.query(ModelVersionORM)
        .filter(ModelVersionORM.status == "active")
        .order_by(ModelVersionORM.id.desc())
        .first()
    )
    if model:
        if not model.config:
            model.config = copy.deepcopy(DEFAULT_MODEL_CONFIG)
        return model

    model = ModelVersionORM(
        name=DEFAULT_MODEL_NAME,
        version=DEFAULT_MODEL_VERSION,
        status="active",
        config=copy.deepcopy(DEFAULT_MODEL_CONFIG),
        metrics={},
        note="默认可解释规则模型",
        activated_at=_now(),
    )
    db.add(model)
    db.flush()
    return model


def _extract_features(stock: dict) -> dict:
    fund = stock.get("fundamental") or {}
    ai = stock.get("ai_analysis") or {}
    indicators = stock.get("indicators") or {}
    dim_scores = stock.get("dim_scores") or {}
    trade_plan = stock.get("trade_plan") or {}

    technical = _clamp(_f(stock.get("score")) / 100.0, 0.0, 1.0)
    fundamental = _clamp(_f(fund.get("quality")) / 25.0, 0.0, 1.0)
    flow = _clamp(_f(fund.get("flow_score")) / 25.0, 0.0, 1.0)
    industry = _clamp(_f(fund.get("industry_score")) / 15.0, 0.0, 1.0)
    northbound = _clamp(_f(fund.get("northbound_score")) / 15.0, 0.0, 1.0)
    research = _clamp(_f(fund.get("research_score")) / 15.0, 0.0, 1.0)
    reduction_risk = _clamp(_f(fund.get("insider_reduction_score")) / 15.0, 0.0, 1.0)
    ai_conf = _clamp(_f(ai.get("confidence")) / 100.0, 0.0, 1.0)
    strategy = _clamp(len(stock.get("strategies") or []) / 5.0, 0.0, 1.0)
    volume = _clamp(_f(dim_scores.get("volume")) / 20.0, 0.0, 1.0)
    momentum = _clamp(_f(dim_scores.get("momentum")) / 15.0, 0.0, 1.0)
    risk_level = str(ai.get("risk_level") or trade_plan.get("risk_level") or "").lower()
    warnings = trade_plan.get("warnings") or []
    risk = 1.0
    if "高" in risk_level or risk_level == "high":
        risk = 0.35
    elif "中" in risk_level or risk_level == "medium":
        risk = 0.65
    if len(warnings) >= 3:
        risk = min(risk, 0.55)

    ret_5d = _f(indicators.get("ret_5d"))
    ret_20d = _f(indicators.get("ret_20d"))
    vol_ratio = _f(indicators.get("vol_ratio"))

    return {
        "technical": round(technical, 4),
        "fundamental": round(fundamental, 4),
        "flow": round(flow, 4),
        "industry": round(industry, 4),
        "northbound": round(northbound, 4),
        "research": round(research, 4),
        "reduction_risk": round(reduction_risk, 4),
        "ai": round(ai_conf, 4),
        "strategy": round(strategy, 4),
        "volume": round(volume, 4),
        "momentum": round(momentum, 4),
        "risk": round(risk, 4),
        "ret_5d": round(ret_5d, 4),
        "ret_20d": round(ret_20d, 4),
        "vol_ratio": round(vol_ratio, 4),
        "change_pct": round(_f(stock.get("change_pct")), 4),
        "strategy_count": len(stock.get("strategies") or []),
    }


def _stop_loss_pct(stock: dict, config: dict) -> float:
    plan = stock.get("trade_plan") or {}
    entry = _f(plan.get("entry_mid")) or _f(plan.get("entry_low")) or _f(stock.get("price"))
    stop = _f(plan.get("stop_loss"))
    if entry > 0 and stop > 0 and stop < entry:
        return round(_clamp((entry - stop) / entry * 100.0, 2.0, 15.0), 2)
    return round(_f(config.get("stop_loss_pct"), 8.0), 2)


def estimate_predictions(stock: dict, config: dict | None = None) -> list[dict]:
    """Estimate per-horizon probabilities for one scanner result."""
    cfg = config or DEFAULT_MODEL_CONFIG
    features = _extract_features(stock)
    weights = cfg.get("weights") or DEFAULT_MODEL_CONFIG["weights"]
    weight_total = sum(abs(_f(v)) for v in weights.values()) or 1.0
    weighted = sum(features.get(k, 0.0) * _f(v) for k, v in weights.items()) / weight_total

    ai = stock.get("ai_analysis") or {}
    action = str(ai.get("action") or "BUY").upper()
    action_adj = 0.06 if action == "BUY" else (0.02 if action == "HOLD" else -0.08)
    trend_adj = _clamp(features["ret_5d"] / 100.0, -0.04, 0.05)
    volume_adj = 0.02 if 1.2 <= features["vol_ratio"] <= 3.5 else (-0.03 if features["vol_ratio"] > 5 else 0.0)
    base_prob = _clamp(0.26 + weighted * 0.58 + action_adj + trend_adj + volume_adj, 0.08, 0.92)

    horizons = [int(h) for h in (cfg.get("horizons") or DEFAULT_MODEL_CONFIG["horizons"])]
    targets = cfg.get("targets") or DEFAULT_MODEL_CONFIG["targets"]
    horizon_bias = cfg.get("horizon_bias") or {}
    stop_loss = _stop_loss_pct(stock, cfg)
    plan_expected = _f((stock.get("trade_plan") or {}).get("expected_return_pct"))

    estimates: list[dict] = []
    for h in horizons:
        h_key = str(h)
        target = _f(targets.get(h_key), 3.0)
        # 短周期更依赖动量，长周期更依赖基本面和趋势延续。
        if h <= 3:
            horizon_adj = features["momentum"] * 0.04 + features["volume"] * 0.02 - 0.03
        elif h <= 10:
            horizon_adj = features["technical"] * 0.03 + features["strategy"] * 0.02
        else:
            horizon_adj = (
                features["fundamental"] * 0.03
                + features["flow"] * 0.015
                + features["industry"] * 0.02
                + features["northbound"] * 0.02
                + features["research"] * 0.015
                - features["reduction_risk"] * 0.04
                - 0.01
            )
        probability = _clamp(base_prob + horizon_adj + _f(horizon_bias.get(h_key)), 0.05, 0.95)
        expected_return = probability * target - (1.0 - probability) * stop_loss
        if plan_expected > 0:
            expected_return = expected_return * 0.7 + plan_expected * min(h / 10.0, 1.0) * 0.3
        estimates.append({
            "horizon_days": h,
            "target_return_pct": round(target, 2),
            "stop_loss_pct": round(stop_loss, 2),
            "probability": round(probability, 4),
            "expected_return_pct": round(expected_return, 4),
            "features": features,
        })

    return estimates


def enrich_scan_results_with_model(results: list[dict], db: Session | None = None) -> dict:
    """Attach active model probabilities to scanner results."""
    with _ctx(db) as session:
        model = ensure_active_model(session)
        cfg = model.config or DEFAULT_MODEL_CONFIG
        enriched: list[dict] = []
        for stock in results or []:
            item = dict(stock)
            estimates = estimate_predictions(item, cfg)
            best = max(estimates, key=lambda x: (x["expected_return_pct"], x["probability"]), default=None)
            if best:
                item["evolution"] = {
                    "model_version_id": model.id,
                    "model_version": model.version,
                    "best_horizon_days": best["horizon_days"],
                    "target_return_pct": best["target_return_pct"],
                    "stop_loss_pct": best["stop_loss_pct"],
                    "probability": best["probability"],
                    "probability_pct": round(best["probability"] * 100, 1),
                    "expected_return_pct": best["expected_return_pct"],
                    "probabilities_by_horizon": [
                        {
                            "horizon_days": e["horizon_days"],
                            "target_return_pct": e["target_return_pct"],
                            "probability": e["probability"],
                            "probability_pct": round(e["probability"] * 100, 1),
                            "expected_return_pct": e["expected_return_pct"],
                        }
                        for e in estimates
                    ],
                }
            enriched.append(item)

        return {
            "model_version_id": model.id,
            "model_version": model.version,
            "results": enriched,
        }


def record_scan_result(scan_output: dict, db: Session | None = None, source: str = "scanner") -> dict:
    """Persist one scanner output and create pending prediction samples."""
    if not scan_output or scan_output.get("error") or scan_output.get("cached"):
        return {"recorded": False, "reason": "empty_or_cached"}

    results = scan_output.get("results") or []
    if not results:
        return {"recorded": False, "reason": "no_results"}

    with _ctx(db) as session:
        model = ensure_active_model(session)
        cfg = model.config or DEFAULT_MODEL_CONFIG
        now = _now()
        run = ScanRunORM(
            model_version_id=model.id,
            source=source,
            params=_jsonable(scan_output.get("params") or {}),
            market_status=_jsonable(scan_output.get("market_status") or {}),
            hot_industries=_jsonable(scan_output.get("hot_industries") or []),
            scanned=int(scan_output.get("scanned") or 0),
            candidates=int(scan_output.get("candidates") or 0),
            analyzed=int(scan_output.get("analyzed") or 0),
            tier1_count=int(scan_output.get("tier1_count") or 0),
            tier2_count=scan_output.get("tier2_count"),
            tier3_count=scan_output.get("tier3_count"),
            result_count=len(results),
            rejected_count=len(scan_output.get("rejected_results") or []),
            llm_status=str(scan_output.get("llm_status") or "disabled"),
            elapsed_ms=_f(scan_output.get("elapsed_ms")),
            created_at=now,
        )
        session.add(run)
        session.flush()

        created = 0
        for rank, stock in enumerate(results, start=1):
            estimates = estimate_predictions(stock, cfg)
            ai = stock.get("ai_analysis") or {}
            action = str(ai.get("action") or "BUY").upper()
            confidence = int(_f(ai.get("confidence")) or _f(stock.get("confidence")))
            price = _f(stock.get("price"))
            if price <= 0:
                continue
            for estimate in estimates:
                horizon = int(estimate["horizon_days"])
                pred = StockPredictionORM(
                    scan_run_id=run.id,
                    model_version_id=model.id,
                    symbol=str(stock.get("symbol") or ""),
                    name=str(stock.get("name") or stock.get("symbol") or ""),
                    rank=rank,
                    action=action,
                    horizon_days=horizon,
                    target_return_pct=estimate["target_return_pct"],
                    stop_loss_pct=estimate["stop_loss_pct"],
                    probability=estimate["probability"],
                    expected_return_pct=estimate["expected_return_pct"],
                    confidence=confidence,
                    score=int(_f(stock.get("score"))),
                    price_at_prediction=price,
                    features=_jsonable(estimate["features"]),
                    trade_plan=_jsonable(stock.get("trade_plan") or {}),
                    raw_result=_jsonable(stock),
                    status="pending",
                    predicted_at=now,
                    due_at=now + timedelta(days=horizon),
                )
                session.add(pred)
                created += 1

        session.flush()
        return {
            "recorded": True,
            "scan_run_id": run.id,
            "model_version_id": model.id,
            "model_version": model.version,
            "predictions_created": created,
        }


def record_trade_fills(
    *,
    limit: int = 200,
    db: Session | None = None,
) -> dict:
    """Create execution prediction samples and close them from real exits."""
    with _ctx(db) as session:
        model = ensure_active_model(session)
        cfg = model.config or DEFAULT_MODEL_CONFIG
        fills = (
            session.query(TradeFillORM)
            .filter(TradeFillORM.side.in_(("BUY", "SELL")), TradeFillORM.evolution_recorded_at.is_(None))
            .order_by(TradeFillORM.filled_at.asc(), TradeFillORM.id.asc())
            .limit(max(1, min(limit, 1000)))
            .all()
        )
        created = 0
        exits_recorded = 0
        for fill in fills:
            order = session.get(TradeOrderORM, fill.order_id)
            side = (fill.side or "").upper()
            if side == "BUY":
                created += _record_buy_fill_predictions(session, model, cfg, fill, order)
            elif side == "SELL":
                exits_recorded += _record_sell_fill_outcomes(session, fill, order)
            fill.evolution_recorded_at = _now()
        session.flush()
        return {"checked": len(fills), "predictions_created": created, "exits_recorded": exits_recorded}


def _record_buy_fill_predictions(
    session: Session,
    model: ModelVersionORM,
    config: dict,
    fill: TradeFillORM,
    order: TradeOrderORM | None,
) -> int:
    raw = {
        "source": "trade_fill",
        "fill_id": fill.id,
        "order_id": fill.order_id,
        "broker_order_id": fill.broker_order_id,
        "account_id": order.account_id if order else "",
        "broker": order.broker if order else "",
        "side": fill.side,
        "quantity": fill.quantity,
        "price": fill.price,
        "amount": fill.amount,
        "order_source": order.source if order else "",
        "strategy": order.strategy if order else "",
        "reason": order.reason if order else "",
    }
    created = 0
    estimates = _estimates_for_trade_fill(fill, config)
    for rank, estimate in enumerate(estimates, start=1):
        session.add(StockPredictionORM(
            scan_run_id=None,
            model_version_id=model.id,
            symbol=fill.symbol,
            name=order.name if order and order.name else fill.symbol,
            rank=rank,
            action="BUY",
            horizon_days=int(estimate["horizon_days"]),
            target_return_pct=estimate["target_return_pct"],
            stop_loss_pct=estimate["stop_loss_pct"],
            probability=estimate["probability"],
            expected_return_pct=estimate["expected_return_pct"],
            confidence=0,
            score=0,
            price_at_prediction=fill.price,
            features=_jsonable(estimate["features"]),
            trade_plan=_jsonable({
                "source": "trade_fill",
                "fill_id": fill.id,
                "entry_mid": fill.price,
                "stop_loss": round(fill.price * (1 - estimate["stop_loss_pct"] / 100.0), 4),
            }),
            raw_result=_jsonable(raw),
            status="pending",
            predicted_at=fill.filled_at,
            due_at=fill.filled_at + timedelta(days=int(estimate["horizon_days"])),
        ))
        created += 1
    return created


def _record_sell_fill_outcomes(
    session: Session,
    fill: TradeFillORM,
    order: TradeOrderORM | None,
) -> int:
    if fill.price <= 0:
        return 0
    account_id = order.account_id if order else ""
    broker = order.broker if order else ""
    candidates = (
        session.query(StockPredictionORM)
        .filter(
            StockPredictionORM.symbol == fill.symbol,
            StockPredictionORM.action == "BUY",
            StockPredictionORM.status == "pending",
            StockPredictionORM.predicted_at <= fill.filled_at,
        )
        .order_by(StockPredictionORM.predicted_at.asc(), StockPredictionORM.horizon_days.asc())
        .all()
    )
    recorded = 0
    for pred in candidates:
        raw = pred.raw_result or {}
        if raw.get("source") != "trade_fill":
            continue
        if account_id and raw.get("account_id") and raw.get("account_id") != account_id:
            continue
        if broker and raw.get("broker") and raw.get("broker") != broker:
            continue
        start = _f(pred.price_at_prediction)
        if start <= 0:
            continue
        close_return = (fill.price - start) / start * 100.0
        hit_target = close_return >= pred.target_return_pct
        hit_stop = close_return <= -abs(pred.stop_loss_pct)
        holding_days = max(1, (fill.filled_at.date() - pred.predicted_at.date()).days)
        existing = (
            session.query(PredictionOutcomeORM)
            .filter(PredictionOutcomeORM.prediction_id == pred.id)
            .first()
        )
        outcome = existing or PredictionOutcomeORM(prediction_id=pred.id)
        outcome.model_version_id = pred.model_version_id
        outcome.symbol = pred.symbol
        outcome.horizon_days = pred.horizon_days
        outcome.start_price = round(start, 4)
        outcome.end_price = round(fill.price, 4)
        outcome.max_price = round(max(start, fill.price), 4)
        outcome.min_price = round(min(start, fill.price), 4)
        outcome.close_return_pct = round(close_return, 4)
        outcome.max_return_pct = round(max(close_return, 0.0), 4)
        outcome.max_drawdown_pct = round(min(close_return, 0.0), 4)
        outcome.success = close_return > 0
        outcome.hit_target = hit_target
        outcome.hit_stop = hit_stop
        outcome.bars_checked = holding_days
        outcome.details = {
            "source": "trade_exit",
            "buy_fill_id": raw.get("fill_id"),
            "sell_fill_id": fill.id,
            "sell_order_id": fill.order_id,
            "sell_price": round(fill.price, 4),
            "holding_days": holding_days,
            "target_return_pct": pred.target_return_pct,
            "stop_loss_pct": pred.stop_loss_pct,
        }
        outcome.validated_at = _now()
        if existing is None:
            session.add(outcome)
        pred.status = "validated"
        pred.validated_at = outcome.validated_at
        recorded += 1
    return recorded


def _estimates_for_trade_fill(fill: TradeFillORM, config: dict) -> list[dict]:
    horizons = [int(h) for h in (config.get("horizons") or DEFAULT_MODEL_CONFIG["horizons"]) if int(h) >= 5]
    if not horizons:
        horizons = [5, 10, 20]
    targets = config.get("targets") or DEFAULT_MODEL_CONFIG["targets"]
    stop_loss = _f(config.get("stop_loss_pct"), 8.0)
    probability = _clamp(0.50 + min(fill.quantity / 10000.0, 0.06), 0.35, 0.72)
    features = {
        "technical": 0.5,
        "fundamental": 0.5,
        "flow": 0.5,
        "industry": 0.5,
        "northbound": 0.5,
        "research": 0.5,
        "reduction_risk": 0.0,
        "ai": 0.0,
        "strategy": 0.0,
        "volume": 0.0,
        "momentum": 0.0,
        "risk": 0.7,
        "ret_5d": 0.0,
        "ret_20d": 0.0,
        "vol_ratio": 0.0,
        "change_pct": 0.0,
        "strategy_count": 0,
        "execution_amount": round(fill.amount, 2),
    }
    rows = []
    for horizon in horizons:
        target = _f(targets.get(str(horizon)), 3.0)
        rows.append({
            "horizon_days": horizon,
            "target_return_pct": round(target, 2),
            "stop_loss_pct": round(stop_loss, 2),
            "probability": round(probability, 4),
            "expected_return_pct": round(probability * target - (1 - probability) * stop_loss, 4),
            "features": features,
        })
    return rows


def _bar_date(bar: dict) -> datetime | None:
    raw = str(bar.get("date") or bar.get("datetime") or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw[:10])
    except Exception:
        return None


def _future_bars_for_prediction(pred: StockPredictionORM, bars: list[dict], force: bool) -> list[dict]:
    dated = [(dt, b) for b in bars if (dt := _bar_date(b)) is not None]
    dated.sort(key=lambda x: x[0])
    pred_day = pred.predicted_at.date()
    future = [b for dt, b in dated if dt.date() > pred_day]
    if len(future) < pred.horizon_days and not force:
        return []
    if future:
        return future[: pred.horizon_days]
    if force and bars:
        return bars[-pred.horizon_days :]
    return []


def _validate_one_prediction(
    session: Session,
    pred: StockPredictionORM,
    *,
    force: bool = False,
) -> PredictionOutcomeORM | None:
    count = max(80, pred.horizon_days + 40)
    bars = market_service.get_kline(pred.symbol, period="daily", count=count) or []
    future = _future_bars_for_prediction(pred, bars, force)
    if not future:
        return None

    start = pred.price_at_prediction
    if start <= 0:
        start = _f(future[0].get("open")) or _f(future[0].get("close"))
    if start <= 0:
        return None

    closes = [_f(b.get("close")) for b in future if _f(b.get("close")) > 0]
    highs = [_f(b.get("high")) or _f(b.get("close")) for b in future]
    lows = [_f(b.get("low")) or _f(b.get("close")) for b in future]
    if not closes or not highs or not lows:
        return None

    target_price = start * (1 + pred.target_return_pct / 100.0)
    stop_price = start * (1 - abs(pred.stop_loss_pct) / 100.0)
    hit_target_idx = None
    hit_stop_idx = None
    for i, bar in enumerate(future):
        high = _f(bar.get("high")) or _f(bar.get("close"))
        low = _f(bar.get("low")) or _f(bar.get("close"))
        if hit_target_idx is None and high >= target_price:
            hit_target_idx = i
        if hit_stop_idx is None and low <= stop_price:
            hit_stop_idx = i

    end = closes[-1]
    max_price = max(highs)
    min_price = min(lows)
    close_return = (end - start) / start * 100.0
    max_return = (max_price - start) / start * 100.0
    max_drawdown = (min_price - start) / start * 100.0
    hit_target = hit_target_idx is not None
    hit_stop = hit_stop_idx is not None
    success = bool(hit_target and (hit_stop_idx is None or hit_target_idx <= hit_stop_idx))

    existing = (
        session.query(PredictionOutcomeORM)
        .filter(PredictionOutcomeORM.prediction_id == pred.id)
        .first()
    )
    outcome = existing or PredictionOutcomeORM(prediction_id=pred.id)
    outcome.model_version_id = pred.model_version_id
    outcome.symbol = pred.symbol
    outcome.horizon_days = pred.horizon_days
    outcome.start_price = round(start, 4)
    outcome.end_price = round(end, 4)
    outcome.max_price = round(max_price, 4)
    outcome.min_price = round(min_price, 4)
    outcome.close_return_pct = round(close_return, 4)
    outcome.max_return_pct = round(max_return, 4)
    outcome.max_drawdown_pct = round(max_drawdown, 4)
    outcome.success = success
    outcome.hit_target = hit_target
    outcome.hit_stop = hit_stop
    outcome.bars_checked = len(future)
    outcome.details = {
        "target_price": round(target_price, 4),
        "stop_price": round(stop_price, 4),
        "hit_target_day": None if hit_target_idx is None else hit_target_idx + 1,
        "hit_stop_day": None if hit_stop_idx is None else hit_stop_idx + 1,
    }
    outcome.validated_at = _now()
    if existing is None:
        session.add(outcome)

    pred.status = "validated"
    pred.validated_at = outcome.validated_at
    return outcome


def validate_predictions(
    *,
    horizon_days: int | None = None,
    limit: int = 200,
    force: bool = False,
    db: Session | None = None,
) -> dict:
    """Validate pending predictions whose horizon has elapsed."""
    with _ctx(db) as session:
        now = _now()
        q = session.query(StockPredictionORM).filter(StockPredictionORM.status == "pending")
        if horizon_days:
            q = q.filter(StockPredictionORM.horizon_days == horizon_days)
        if not force:
            q = q.filter(StockPredictionORM.due_at <= now)
        preds = q.order_by(StockPredictionORM.due_at.asc()).limit(max(1, min(limit, 1000))).all()

        validated = 0
        skipped = 0
        errors = 0
        for pred in preds:
            try:
                outcome = _validate_one_prediction(session, pred, force=force)
                if outcome:
                    validated += 1
                else:
                    skipped += 1
            except Exception as e:
                errors += 1
                log.warning("validate prediction %s %s failed: %s", pred.id, pred.symbol, e)

        session.flush()
        return {
            "checked": len(preds),
            "validated": validated,
            "skipped": skipped,
            "errors": errors,
        }


async def _validation_loop(
    *,
    interval_seconds: int,
    initial_delay_seconds: int,
    limit: int,
) -> None:
    if initial_delay_seconds > 0:
        await asyncio.sleep(initial_delay_seconds)
    while True:
        try:
            trade_result = await asyncio.to_thread(record_trade_fills, limit=limit)
            if trade_result.get("predictions_created"):
                log.info("evolution trade fill record: %s", trade_result)
            result = await asyncio.to_thread(validate_predictions, limit=limit)
            if result.get("checked"):
                log.info("evolution auto validation: %s", result)
            cycle_result = await asyncio.to_thread(auto_evolve_cycle)
            if cycle_result.get("status") not in {"disabled", "insufficient_data"}:
                log.info("evolution auto cycle: %s", cycle_result)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("evolution auto validation failed: %s", e, exc_info=True)
        await asyncio.sleep(interval_seconds)


def ensure_validation_loop_running(
    *,
    interval_seconds: int | None = None,
    initial_delay_seconds: int | None = None,
    limit: int | None = None,
) -> bool:
    """Start the background due-prediction validation loop."""
    global _validation_task
    if _validation_task and not _validation_task.done():
        return True

    from apps.api.app.core.config import get_settings
    settings = get_settings()
    interval = int(interval_seconds if interval_seconds is not None else settings.evolution_validate_interval_seconds)
    if interval <= 0:
        log.info("evolution auto validation disabled")
        return False
    initial_delay = int(
        initial_delay_seconds
        if initial_delay_seconds is not None
        else settings.evolution_validate_initial_delay_seconds
    )
    run_limit = int(limit if limit is not None else settings.evolution_validate_limit)
    _validation_task = asyncio.create_task(
        _validation_loop(
            interval_seconds=interval,
            initial_delay_seconds=max(0, initial_delay),
            limit=max(1, run_limit),
        )
    )
    return True


async def stop_validation_loop() -> None:
    global _validation_task
    if not _validation_task:
        return
    _validation_task.cancel()
    try:
        await _validation_task
    except asyncio.CancelledError:
        pass
    finally:
        _validation_task = None


def _metric_pairs(session: Session, model_version_id: int | None = None) -> list[tuple[StockPredictionORM, PredictionOutcomeORM]]:
    q = session.query(PredictionOutcomeORM)
    if model_version_id is not None:
        q = q.filter(PredictionOutcomeORM.model_version_id == model_version_id)
    outcomes = q.order_by(PredictionOutcomeORM.validated_at.desc()).all()
    pairs: list[tuple[StockPredictionORM, PredictionOutcomeORM]] = []
    for out in outcomes:
        pred = session.get(StockPredictionORM, out.prediction_id)
        if pred:
            pairs.append((pred, out))
    return pairs


def _compute_metrics_from_pairs(pairs: list[tuple[StockPredictionORM, PredictionOutcomeORM]]) -> dict:
    if not pairs:
        return {
            "sample_count": 0,
            "success_rate": 0.0,
            "avg_return_pct": 0.0,
            "avg_max_return_pct": 0.0,
            "brier_score": 0.0,
            "calibration_error": 0.0,
            "by_horizon": [],
        }

    actual = [1.0 if out.success else 0.0 for pred, out in pairs]
    probs = [_clamp(pred.probability, 0.0, 1.0) for pred, out in pairs]
    returns = [out.close_return_pct for pred, out in pairs]
    max_returns = [out.max_return_pct for pred, out in pairs]
    success_rate = mean(actual)
    brier = mean([(p - a) ** 2 for p, a in zip(probs, actual)])
    cal = abs(mean(probs) - success_rate)

    by_horizon = []
    for horizon in sorted({pred.horizon_days for pred, out in pairs}):
        h_pairs = [(pred, out) for pred, out in pairs if pred.horizon_days == horizon]
        h_actual = [1.0 if out.success else 0.0 for pred, out in h_pairs]
        h_probs = [_clamp(pred.probability, 0.0, 1.0) for pred, out in h_pairs]
        by_horizon.append({
            "horizon_days": horizon,
            "sample_count": len(h_pairs),
            "success_rate": round(mean(h_actual), 4),
            "avg_return_pct": round(mean([out.close_return_pct for pred, out in h_pairs]), 4),
            "avg_max_return_pct": round(mean([out.max_return_pct for pred, out in h_pairs]), 4),
            "brier_score": round(mean([(p - a) ** 2 for p, a in zip(h_probs, h_actual)]), 4),
            "calibration_error": round(abs(mean(h_probs) - mean(h_actual)), 4),
        })

    return {
        "sample_count": len(pairs),
        "success_rate": round(success_rate, 4),
        "avg_return_pct": round(mean(returns), 4),
        "avg_max_return_pct": round(mean(max_returns), 4),
        "brier_score": round(brier, 4),
        "calibration_error": round(cal, 4),
        "by_horizon": by_horizon,
    }


def compute_metrics(db: Session | None = None, model_version_id: int | None = None) -> dict:
    with _ctx(db) as session:
        return _compute_metrics_from_pairs(_metric_pairs(session, model_version_id))


def _promotion_gate(metrics: dict, thresholds: dict) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if _f(metrics.get("success_rate")) < _f(thresholds.get("min_success_rate")):
        reasons.append(
            f"success_rate {_f(metrics.get('success_rate')):.4f} < "
            f"{_f(thresholds.get('min_success_rate')):.4f}"
        )
    if _f(metrics.get("avg_return_pct")) < _f(thresholds.get("min_avg_return_pct")):
        reasons.append(
            f"avg_return_pct {_f(metrics.get('avg_return_pct')):.4f} < "
            f"{_f(thresholds.get('min_avg_return_pct')):.4f}"
        )
    if _f(metrics.get("brier_score"), 1.0) > _f(thresholds.get("max_brier_score")):
        reasons.append(
            f"brier_score {_f(metrics.get('brier_score'), 1.0):.4f} > "
            f"{_f(thresholds.get('max_brier_score')):.4f}"
        )
    if _f(metrics.get("calibration_error"), 1.0) > _f(thresholds.get("max_calibration_error")):
        reasons.append(
            f"calibration_error {_f(metrics.get('calibration_error'), 1.0):.4f} > "
            f"{_f(thresholds.get('max_calibration_error')):.4f}"
        )
    return not reasons, reasons


def _rollback_gate(metrics: dict, thresholds: dict) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if _f(metrics.get("success_rate")) < _f(thresholds.get("min_success_rate")):
        reasons.append(
            f"success_rate {_f(metrics.get('success_rate')):.4f} < "
            f"{_f(thresholds.get('min_success_rate')):.4f}"
        )
    if _f(metrics.get("avg_return_pct")) < _f(thresholds.get("min_avg_return_pct")):
        reasons.append(
            f"avg_return_pct {_f(metrics.get('avg_return_pct')):.4f} < "
            f"{_f(thresholds.get('min_avg_return_pct')):.4f}"
        )
    if _f(metrics.get("brier_score"), 0.0) > _f(thresholds.get("max_brier_score")):
        reasons.append(
            f"brier_score {_f(metrics.get('brier_score'), 0.0):.4f} > "
            f"{_f(thresholds.get('max_brier_score')):.4f}"
        )
    return bool(reasons), reasons


def _promote_candidate(
    session: Session,
    *,
    active: ModelVersionORM,
    candidate: ModelVersionORM,
    metrics: dict,
    thresholds: dict,
    reasons: list[str],
    source: str,
) -> None:
    active.status = "retired"
    active.metrics = metrics
    candidate.status = "active"
    candidate.metrics = metrics
    candidate.activated_at = _now()
    candidate.note = f"{candidate.note}；{source} 自动晋升"
    session.add(EvolutionRunORM(
        model_version_id=active.id,
        candidate_model_version_id=candidate.id,
        status="auto_promoted",
        evaluated_predictions=int(metrics.get("sample_count") or 0),
        success_rate=_f(metrics.get("success_rate")),
        avg_return_pct=_f(metrics.get("avg_return_pct")),
        brier_score=_f(metrics.get("brier_score")),
        calibration_error=_f(metrics.get("calibration_error")),
        promoted=True,
        summary={
            "source": source,
            "metrics": metrics,
            "thresholds": thresholds,
            "reasons": reasons,
            "candidate_version": candidate.version,
        },
    ))


def _rollback_active_model(
    session: Session,
    *,
    active: ModelVersionORM,
    parent: ModelVersionORM,
    metrics: dict,
    thresholds: dict,
    reasons: list[str],
) -> dict:
    active.status = "rolled_back"
    active.metrics = metrics
    parent.status = "active"
    parent.activated_at = _now()
    session.add(EvolutionRunORM(
        model_version_id=active.id,
        candidate_model_version_id=parent.id,
        status="auto_rolled_back",
        evaluated_predictions=int(metrics.get("sample_count") or 0),
        success_rate=_f(metrics.get("success_rate")),
        avg_return_pct=_f(metrics.get("avg_return_pct")),
        brier_score=_f(metrics.get("brier_score")),
        calibration_error=_f(metrics.get("calibration_error")),
        promoted=True,
        summary={
            "source": "auto_rollback",
            "metrics": metrics,
            "thresholds": thresholds,
            "reasons": reasons,
            "rolled_back_model": active.version,
            "restored_model": parent.version,
        },
    ))
    session.flush()
    return {
        "status": "auto_rolled_back",
        "rolled_back_model": _model_to_dict(active),
        "active_model": _model_to_dict(parent),
        "metrics": metrics,
        "reasons": reasons,
    }


def auto_evolve_cycle(db: Session | None = None) -> dict:
    """Run the safe automatic evolution cycle: rollback, then promote/generate."""
    from apps.api.app.core.config import get_settings

    settings = get_settings()
    if not settings.evolution_auto_evolve_enabled:
        return {"status": "disabled"}

    with _ctx(db) as session:
        active = ensure_active_model(session)
        pairs = _metric_pairs(session, active.id)
        active_metrics = _compute_metrics_from_pairs(pairs)

        if (
            settings.evolution_auto_rollback_enabled
            and active.parent_id
            and len(pairs) >= settings.evolution_auto_rollback_min_samples
        ):
            rollback_thresholds = {
                "min_success_rate": settings.evolution_auto_rollback_min_success_rate,
                "min_avg_return_pct": settings.evolution_auto_rollback_min_avg_return_pct,
                "max_brier_score": settings.evolution_auto_rollback_max_brier_score,
            }
            should_rollback, rollback_reasons = _rollback_gate(active_metrics, rollback_thresholds)
            parent = session.get(ModelVersionORM, active.parent_id)
            if should_rollback and parent:
                return _rollback_active_model(
                    session,
                    active=active,
                    parent=parent,
                    metrics=active_metrics,
                    thresholds=rollback_thresholds,
                    reasons=rollback_reasons,
                )

        min_samples = int(settings.evolution_auto_evolve_min_samples)
        if len(pairs) < min_samples:
            return {
                "status": "insufficient_data",
                "min_samples": min_samples,
                "evaluated_predictions": len(pairs),
                "metrics": active_metrics,
            }

        thresholds = {
            "min_success_rate": settings.evolution_auto_promote_min_success_rate,
            "min_avg_return_pct": settings.evolution_auto_promote_min_avg_return_pct,
            "max_brier_score": settings.evolution_auto_promote_max_brier_score,
            "max_calibration_error": settings.evolution_auto_promote_max_calibration_error,
        }
        allowed, reasons = _promotion_gate(active_metrics, thresholds)
        if not allowed:
            session.add(EvolutionRunORM(
                model_version_id=active.id,
                status="auto_blocked",
                evaluated_predictions=len(pairs),
                success_rate=active_metrics["success_rate"],
                avg_return_pct=active_metrics["avg_return_pct"],
                brier_score=active_metrics["brier_score"],
                calibration_error=active_metrics["calibration_error"],
                promoted=False,
                summary={
                    "source": "auto_evolve",
                    "metrics": active_metrics,
                    "thresholds": thresholds,
                    "reasons": reasons,
                },
            ))
            session.flush()
            return {
                "status": "auto_blocked",
                "evaluated_predictions": len(pairs),
                "metrics": active_metrics,
                "thresholds": thresholds,
                "reasons": reasons,
            }

        candidate = (
            session.query(ModelVersionORM)
            .filter(ModelVersionORM.parent_id == active.id, ModelVersionORM.status == "candidate")
            .order_by(ModelVersionORM.id.desc())
            .first()
        )
        if candidate is None:
            candidate_config = _adjust_weights(active.config or DEFAULT_MODEL_CONFIG, pairs)
            candidate = ModelVersionORM(
                name=active.name,
                version=_next_version(active.version),
                status="candidate",
                parent_id=active.id,
                config=candidate_config,
                metrics=active_metrics,
                note="由自动进化周期生成的候选模型",
            )
            session.add(candidate)
            session.flush()

        _promote_candidate(
            session,
            active=active,
            candidate=candidate,
            metrics=active_metrics,
            thresholds=thresholds,
            reasons=[],
            source="auto_evolve",
        )
        session.flush()
        return {
            "status": "auto_promoted",
            "evaluated_predictions": len(pairs),
            "active_model": _model_to_dict(candidate),
            "previous_model": _model_to_dict(active),
            "metrics": active_metrics,
            "thresholds": thresholds,
        }


def _persist_model_metrics(session: Session, model_version_id: int | None, metrics: dict) -> None:
    for row in metrics.get("by_horizon") or []:
        session.add(ModelMetricORM(
            model_version_id=model_version_id,
            horizon_days=int(row["horizon_days"]),
            sample_count=int(row["sample_count"]),
            success_rate=float(row["success_rate"]),
            avg_return_pct=float(row["avg_return_pct"]),
            avg_max_return_pct=float(row["avg_max_return_pct"]),
            brier_score=float(row["brier_score"]),
            calibration_error=float(row["calibration_error"]),
            computed_at=_now(),
        ))


def get_summary(db: Session | None = None) -> dict:
    with _ctx(db) as session:
        model = ensure_active_model(session)
        metrics = _compute_metrics_from_pairs(_metric_pairs(session, model.id))
        now = _now()
        pending = session.query(StockPredictionORM).filter(StockPredictionORM.status == "pending").count()
        due = (
            session.query(StockPredictionORM)
            .filter(StockPredictionORM.status == "pending", StockPredictionORM.due_at <= now)
            .count()
        )
        validated = session.query(StockPredictionORM).filter(StockPredictionORM.status == "validated").count()
        total = session.query(StockPredictionORM).count()
        latest_runs = (
            session.query(ScanRunORM)
            .order_by(ScanRunORM.created_at.desc())
            .limit(5)
            .all()
        )
        latest_evolution = (
            session.query(EvolutionRunORM)
            .order_by(EvolutionRunORM.created_at.desc())
            .limit(5)
            .all()
        )
        return {
            "active_model": _model_to_dict(model),
            "metrics": metrics,
            "counts": {
                "total_predictions": total,
                "pending": pending,
                "due": due,
                "validated": validated,
            },
            "latest_scan_runs": [_scan_run_to_dict(r) for r in latest_runs],
            "latest_evolution_runs": [_evolution_run_to_dict(r) for r in latest_evolution],
        }


def list_predictions(
    *,
    status: str | None = None,
    horizon_days: int | None = None,
    limit: int = 100,
    db: Session | None = None,
) -> list[dict]:
    with _ctx(db) as session:
        q = session.query(StockPredictionORM)
        if status:
            q = q.filter(StockPredictionORM.status == status)
        if horizon_days:
            q = q.filter(StockPredictionORM.horizon_days == horizon_days)
        preds = (
            q.order_by(StockPredictionORM.predicted_at.desc(), StockPredictionORM.id.desc())
            .limit(max(1, min(limit, 500)))
            .all()
        )
        rows = []
        for pred in preds:
            outcome = (
                session.query(PredictionOutcomeORM)
                .filter(PredictionOutcomeORM.prediction_id == pred.id)
                .first()
            )
            rows.append(_prediction_to_dict(pred, outcome))
        return rows


def list_models(db: Session | None = None) -> list[dict]:
    with _ctx(db) as session:
        models = session.query(ModelVersionORM).order_by(ModelVersionORM.id.desc()).all()
        return [_model_to_dict(m) for m in models]


def list_scan_runs(*, limit: int = 20, db: Session | None = None) -> list[dict]:
    with _ctx(db) as session:
        runs = (
            session.query(ScanRunORM)
            .order_by(ScanRunORM.created_at.desc())
            .limit(max(1, min(limit, 100)))
            .all()
        )
        rows = []
        for run in runs:
            row = _scan_run_to_dict(run)
            row["symbols"] = _symbols_for_run(session, run.id)
            rows.append(row)
        return rows


def compare_scan_runs(
    *,
    base_run_id: int | None = None,
    compare_run_id: int | None = None,
    db: Session | None = None,
) -> dict:
    """Compare two scan runs. Defaults to latest vs previous."""
    with _ctx(db) as session:
        if base_run_id is None or compare_run_id is None:
            latest = (
                session.query(ScanRunORM)
                .order_by(ScanRunORM.created_at.desc())
                .limit(2)
                .all()
            )
            if len(latest) < 2:
                return {"ready": False, "reason": "need_at_least_two_scan_runs"}
            base = latest[0]
            compare = latest[1]
        else:
            base = session.get(ScanRunORM, base_run_id)
            compare = session.get(ScanRunORM, compare_run_id)
            if not base or not compare:
                return {"ready": False, "reason": "scan_run_not_found"}

        base_symbols = _symbol_map_for_run(session, base.id)
        compare_symbols = _symbol_map_for_run(session, compare.id)
        base_set = set(base_symbols)
        compare_set = set(compare_symbols)
        overlap = sorted(base_set & compare_set)
        only_base = sorted(base_set - compare_set)
        only_compare = sorted(compare_set - base_set)

        return {
            "ready": True,
            "base_run": _scan_run_to_dict(base),
            "compare_run": _scan_run_to_dict(compare),
            "counts": {
                "base": len(base_set),
                "compare": len(compare_set),
                "overlap": len(overlap),
                "new": len(only_base),
                "dropped": len(only_compare),
            },
            "overlap": [base_symbols[s] for s in overlap],
            "new": [base_symbols[s] for s in only_base],
            "dropped": [compare_symbols[s] for s in only_compare],
        }


def _next_version(current: str) -> str:
    prefix = "rule-v"
    if current.startswith(prefix):
        try:
            return f"{prefix}{int(current[len(prefix):]) + 1}"
        except Exception:
            pass
    return f"{prefix}{int(_now().timestamp())}"


def _adjust_weights(config: dict, pairs: list[tuple[StockPredictionORM, PredictionOutcomeORM]]) -> dict:
    cfg = copy.deepcopy(config or DEFAULT_MODEL_CONFIG)
    weights = copy.deepcopy(cfg.get("weights") or DEFAULT_MODEL_CONFIG["weights"])
    keys = list(weights)
    successes = [(pred, out) for pred, out in pairs if out.success]
    failures = [(pred, out) for pred, out in pairs if not out.success]
    if not successes or not failures:
        return cfg

    for key in keys:
        succ_avg = mean([_f(pred.features.get(key)) for pred, out in successes])
        fail_avg = mean([_f(pred.features.get(key)) for pred, out in failures])
        old_weight = _f(weights[key])
        if old_weight < 0:
            # Negative factors should become stronger when failures show more of that factor.
            delta = _clamp((fail_avg - succ_avg) * 0.18, -0.12, 0.12)
            weights[key] = -max(0.02, abs(old_weight) * (1.0 + delta))
        else:
            delta = _clamp((succ_avg - fail_avg) * 0.18, -0.12, 0.12)
            weights[key] = max(0.02, old_weight * (1.0 + delta))

    total = sum(abs(v) for v in weights.values()) or 1.0
    cfg["weights"] = {k: round(v / total, 4) for k, v in weights.items()}

    metrics = _compute_metrics_from_pairs(pairs)
    overall = _f(metrics.get("success_rate"))
    bias = copy.deepcopy(cfg.get("horizon_bias") or {})
    for row in metrics.get("by_horizon") or []:
        key = str(row["horizon_days"])
        prev = _f(bias.get(key))
        bias[key] = round(_clamp(prev + (_f(row["success_rate"]) - overall) * 0.08, -0.12, 0.12), 4)
    cfg["horizon_bias"] = bias
    cfg["last_adjusted_at"] = _now().isoformat()
    return cfg


def evolve_model(
    *,
    min_samples: int | None = None,
    promote: bool = False,
    db: Session | None = None,
) -> dict:
    """Create a calibrated candidate model from validated prediction outcomes."""
    with _ctx(db) as session:
        active = ensure_active_model(session)
        pairs = _metric_pairs(session, active.id)
        metrics = _compute_metrics_from_pairs(pairs)
        threshold = int(min_samples or (active.config or DEFAULT_MODEL_CONFIG).get("min_samples_to_evolve", 30))

        if len(pairs) < threshold:
            run = EvolutionRunORM(
                model_version_id=active.id,
                status="insufficient_data",
                evaluated_predictions=len(pairs),
                success_rate=metrics["success_rate"],
                avg_return_pct=metrics["avg_return_pct"],
                brier_score=metrics["brier_score"],
                calibration_error=metrics["calibration_error"],
                promoted=False,
                summary={"reason": f"validated samples {len(pairs)} < min_samples {threshold}", "metrics": metrics},
            )
            session.add(run)
            session.flush()
            return {
                "status": "insufficient_data",
                "min_samples": threshold,
                "evaluated_predictions": len(pairs),
                "metrics": metrics,
                "evolution_run_id": run.id,
            }

        candidate_config = _adjust_weights(active.config or DEFAULT_MODEL_CONFIG, pairs)
        version = _next_version(active.version)
        candidate = ModelVersionORM(
            name=active.name,
            version=version,
            status="active" if promote else "candidate",
            parent_id=active.id,
            config=candidate_config,
            metrics=metrics,
            note="由历史预测验证结果自动校准生成",
            activated_at=_now() if promote else None,
        )
        if promote:
            active.status = "retired"
        active.metrics = metrics
        session.add(candidate)
        session.flush()
        _persist_model_metrics(session, active.id, metrics)

        run = EvolutionRunORM(
            model_version_id=active.id,
            candidate_model_version_id=candidate.id,
            status="completed",
            evaluated_predictions=len(pairs),
            success_rate=metrics["success_rate"],
            avg_return_pct=metrics["avg_return_pct"],
            brier_score=metrics["brier_score"],
            calibration_error=metrics["calibration_error"],
            promoted=promote,
            summary={
                "metrics": metrics,
                "old_weights": (active.config or {}).get("weights", {}),
                "new_weights": candidate_config.get("weights", {}),
                "horizon_bias": candidate_config.get("horizon_bias", {}),
            },
        )
        session.add(run)
        session.flush()

        return {
            "status": "completed",
            "promoted": promote,
            "evolution_run_id": run.id,
            "active_model": _model_to_dict(candidate if promote else active),
            "candidate_model": _model_to_dict(candidate),
            "metrics": metrics,
        }


def _model_to_dict(model: ModelVersionORM) -> dict:
    return {
        "id": model.id,
        "name": model.name,
        "version": model.version,
        "status": model.status,
        "parent_id": model.parent_id,
        "config": model.config or {},
        "metrics": model.metrics or {},
        "note": model.note,
        "created_at": model.created_at.isoformat() if model.created_at else None,
        "activated_at": model.activated_at.isoformat() if model.activated_at else None,
    }


def _scan_run_to_dict(run: ScanRunORM) -> dict:
    return {
        "id": run.id,
        "model_version_id": run.model_version_id,
        "source": run.source,
        "result_count": run.result_count,
        "rejected_count": run.rejected_count,
        "scanned": run.scanned,
        "candidates": run.candidates,
        "analyzed": run.analyzed,
        "tier1_count": run.tier1_count,
        "tier2_count": run.tier2_count,
        "tier3_count": run.tier3_count,
        "llm_status": run.llm_status,
        "elapsed_ms": run.elapsed_ms,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }


def _symbol_map_for_run(session: Session, scan_run_id: int) -> dict[str, dict]:
    preds = (
        session.query(StockPredictionORM)
        .filter(StockPredictionORM.scan_run_id == scan_run_id)
        .order_by(StockPredictionORM.rank.asc(), StockPredictionORM.probability.desc())
        .all()
    )
    out: dict[str, dict] = {}
    for pred in preds:
        if pred.symbol in out:
            continue
        out[pred.symbol] = {
            "symbol": pred.symbol,
            "name": pred.name,
            "rank": pred.rank,
            "price_at_prediction": pred.price_at_prediction,
            "probability_pct": round(pred.probability * 100, 1),
            "best_horizon_days": pred.horizon_days,
            "target_return_pct": pred.target_return_pct,
            "expected_return_pct": pred.expected_return_pct,
        }
    return out


def _symbols_for_run(session: Session, scan_run_id: int) -> list[dict]:
    return list(_symbol_map_for_run(session, scan_run_id).values())


def _evolution_run_to_dict(run: EvolutionRunORM) -> dict:
    return {
        "id": run.id,
        "model_version_id": run.model_version_id,
        "candidate_model_version_id": run.candidate_model_version_id,
        "status": run.status,
        "evaluated_predictions": run.evaluated_predictions,
        "success_rate": run.success_rate,
        "avg_return_pct": run.avg_return_pct,
        "brier_score": run.brier_score,
        "calibration_error": run.calibration_error,
        "promoted": run.promoted,
        "summary": run.summary or {},
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }


def _prediction_to_dict(pred: StockPredictionORM, outcome: PredictionOutcomeORM | None = None) -> dict:
    return {
        "id": pred.id,
        "scan_run_id": pred.scan_run_id,
        "model_version_id": pred.model_version_id,
        "symbol": pred.symbol,
        "name": pred.name,
        "rank": pred.rank,
        "action": pred.action,
        "horizon_days": pred.horizon_days,
        "target_return_pct": pred.target_return_pct,
        "stop_loss_pct": pred.stop_loss_pct,
        "probability": pred.probability,
        "probability_pct": round(pred.probability * 100, 1),
        "expected_return_pct": pred.expected_return_pct,
        "confidence": pred.confidence,
        "score": pred.score,
        "price_at_prediction": pred.price_at_prediction,
        "features": pred.features or {},
        "trade_plan": pred.trade_plan or {},
        "status": pred.status,
        "predicted_at": pred.predicted_at.isoformat() if pred.predicted_at else None,
        "due_at": pred.due_at.isoformat() if pred.due_at else None,
        "validated_at": pred.validated_at.isoformat() if pred.validated_at else None,
        "outcome": None if outcome is None else {
            "success": outcome.success,
            "hit_target": outcome.hit_target,
            "hit_stop": outcome.hit_stop,
            "close_return_pct": outcome.close_return_pct,
            "max_return_pct": outcome.max_return_pct,
            "max_drawdown_pct": outcome.max_drawdown_pct,
            "bars_checked": outcome.bars_checked,
            "details": outcome.details or {},
            "validated_at": outcome.validated_at.isoformat() if outcome.validated_at else None,
        },
    }
