"""Trading service: paper trading first, QMT Gateway optional.

The main API keeps its own order/fill ledger even when forwarding to QMT.
This gives the UI a stable trading history and lets paper mode work without
Windows/QMT installed.
"""
from __future__ import annotations

import uuid
import os
import threading
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.api.app.core.config import get_settings
from apps.api.app.db.models import (
    TradeFillORM,
    TradeOrderORM,
    TradingAccountORM,
    TradingPositionORM,
)
from apps.api.app.services import alert_service, market_service
from libs.execution.a_share_rules import OrderSide, check_order
from libs.features.technical import calculate_volatility
from libs.portfolio.optimizer import PortfolioConstraints, PortfolioOptimizer, WeightingScheme
from libs.quant_core.models import Position as PortfolioPosition
from libs.risk.engine import RiskDecision, RiskEngine

_paper_account_lock = threading.RLock()


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, str) and value.strip():
        text = value.strip().replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(text).replace(tzinfo=None)
        except Exception:
            pass
    return _now()


def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except Exception:
        return default


def _i(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(value)
    except Exception:
        return default


def _normalize_symbol(symbol: str) -> str:
    s = (symbol or "").strip().upper()
    if not s:
        return s
    if "." in s:
        code, suffix = s.split(".", 1)
    else:
        prefix = s[:2]
        if prefix in {"SH", "SZ", "BJ"} and s[2:].isdigit():
            code, suffix = s[2:], prefix
        else:
            code = s
            suffix = "SH" if code.startswith(("6", "9")) else "SZ"
    code = code.strip().upper()
    for prefix in ("SH", "SZ", "BJ"):
        if code.startswith(prefix):
            code = code[2:]
            suffix = prefix
            break
    if code.isdigit():
        code = code.zfill(6)
    return f"{code}.{suffix.upper()}"


def _jsonable(v: Any) -> Any:
    import json
    return json.loads(json.dumps(v, ensure_ascii=False, default=str))


def _merge_account_raw(existing: dict | None, incoming: dict | None, total_asset: float) -> dict:
    raw = dict(existing or {})
    if isinstance(incoming, dict):
        raw.update(_jsonable(incoming))
    peak = max(
        _f(raw.get("high_water_mark")),
        _f(raw.get("peak_total_asset")),
        _f(raw.get("max_total_asset")),
        _f(raw.get("peak_nav")),
        total_asset,
    )
    if peak > 0:
        raw["high_water_mark"] = round(peak, 2)
    return raw


def _paper_account(db: Session) -> TradingAccountORM:
    acct = db.query(TradingAccountORM).filter(TradingAccountORM.account_id == "PAPER").first()
    if acct is None:
        with _paper_account_lock:
            acct = db.query(TradingAccountORM).filter(TradingAccountORM.account_id == "PAPER").first()
            if acct is None:
                cash = float(os.getenv("QUANT_PAPER_INITIAL_CASH", str(get_settings().paper_initial_cash)))
                acct = TradingAccountORM(
                    account_id="PAPER",
                    broker="paper",
                    cash=cash,
                    available_cash=cash,
                    market_value=0.0,
                    total_asset=cash,
                    raw={},
                    updated_at=_now(),
                )
                try:
                    with db.begin_nested():
                        db.add(acct)
                        db.flush()
                except IntegrityError:
                    acct = db.query(TradingAccountORM).filter(TradingAccountORM.account_id == "PAPER").one()
    _refresh_paper_account(db, acct)
    return acct


def _refresh_paper_account(db: Session, acct: TradingAccountORM | None = None) -> TradingAccountORM:
    acct = acct or _paper_account(db)
    positions = db.query(TradingPositionORM).filter(TradingPositionORM.account_id == "PAPER").all()
    symbols = [p.symbol for p in positions]
    quote_map = {}
    if symbols:
        try:
            quote_map = {q["symbol"]: q for q in market_service.get_realtime_quotes(symbols)}
        except Exception:
            quote_map = {}
    market_value = 0.0
    for p in positions:
        q = quote_map.get(p.symbol) or {}
        price = float(q.get("price") or p.avg_cost or 0.0)
        p.market_value = round(price * p.quantity, 2)
        p.updated_at = _now()
        market_value += p.market_value
    acct.market_value = round(market_value, 2)
    acct.total_asset = round(acct.cash + market_value, 2)
    acct.available_cash = acct.cash
    acct.raw = _merge_account_raw(acct.raw, None, acct.total_asset)
    acct.updated_at = _now()
    return acct


def _quote(symbol: str) -> dict:
    try:
        return market_service.get_single_quote(symbol) or {}
    except Exception:
        return {}


def _quote_price(symbol: str, fallback: Optional[float] = None) -> float:
    if fallback and fallback > 0:
        return float(fallback)
    q = _quote(symbol)
    if q and q.get("price"):
        return float(q["price"])
    return float(fallback or 0.0)


def _upsert_position_after_fill(
    db: Session,
    *,
    symbol: str,
    name: str,
    side: str,
    quantity: int,
    price: float,
) -> None:
    pos = (
        db.query(TradingPositionORM)
        .filter(TradingPositionORM.account_id == "PAPER", TradingPositionORM.symbol == symbol)
        .first()
    )
    if side == "BUY":
        if pos:
            new_qty = pos.quantity + quantity
            pos.avg_cost = (pos.quantity * pos.avg_cost + quantity * price) / new_qty
            pos.quantity = new_qty
            pos.available_quantity = new_qty
            pos.name = name or pos.name
            pos.market_value = round(new_qty * price, 2)
            pos.updated_at = _now()
        else:
            db.add(TradingPositionORM(
                account_id="PAPER",
                broker="paper",
                symbol=symbol,
                name=name or symbol,
                quantity=quantity,
                available_quantity=quantity,
                avg_cost=price,
                market_value=round(quantity * price, 2),
                updated_at=_now(),
            ))
    else:
        if not pos:
            return
        pos.quantity -= quantity
        pos.available_quantity = max(0, pos.available_quantity - quantity)
        pos.market_value = round(max(pos.quantity, 0) * price, 2)
        pos.updated_at = _now()
        if pos.quantity <= 0:
            db.delete(pos)
    alert_service.reset_position_alert_state(symbol)


def _paper_position(db: Session, symbol: str) -> TradingPositionORM | None:
    return (
        db.query(TradingPositionORM)
        .filter(TradingPositionORM.account_id == "PAPER", TradingPositionORM.symbol == symbol)
        .first()
    )


def _today_turnover(db: Session, account_id: str) -> float:
    start = _now().replace(hour=0, minute=0, second=0, microsecond=0)
    rows = (
        db.query(TradeFillORM)
        .filter(TradeFillORM.filled_at >= start)
        .all()
    )
    order_ids = {f.order_id for f in rows}
    orders = {
        o.id: o
        for o in db.query(TradeOrderORM).filter(TradeOrderORM.id.in_(order_ids)).all()
    } if order_ids else {}
    return sum(f.amount for f in rows if (orders.get(f.order_id) and orders[f.order_id].account_id == account_id))


def _positions_for_account(db: Session, account_id: str) -> list[TradingPositionORM]:
    return (
        db.query(TradingPositionORM)
        .filter(TradingPositionORM.account_id == account_id)
        .all()
    )


def _resolve_industry(symbol: str, pos: TradingPositionORM | None = None, quote: dict | None = None) -> str:
    raw = pos.raw if pos and isinstance(pos.raw, dict) else {}
    for source in (raw, quote or {}):
        if not isinstance(source, dict):
            continue
        for key in ("industry", "industry_name", "sector", "sector_name", "board"):
            value = str(source.get(key) or "").strip()
            if value:
                return value
    try:
        from apps.api.app.services import fundamental_service

        info = fundamental_service.get_stock_info(symbol)
        return str(info.get("industry") or "").strip()
    except Exception:
        return ""


def _position_return(pos: TradingPositionORM | None, price: float) -> float | None:
    if pos is None:
        return None
    cost = _f(pos.avg_cost)
    if cost <= 0 or price <= 0:
        return None
    return round((price - cost) / cost, 4)


def _portfolio_drawdown(acct: TradingAccountORM | None) -> float | None:
    if acct is None:
        return None
    total_asset = _f(acct.total_asset)
    if total_asset <= 0:
        return None
    raw = acct.raw if isinstance(acct.raw, dict) else {}
    peak = max(
        _f(raw.get("high_water_mark")),
        _f(raw.get("peak_total_asset")),
        _f(raw.get("max_total_asset")),
        _f(raw.get("peak_nav")),
        total_asset,
    )
    if peak <= 0:
        return None
    return round((total_asset - peak) / peak, 4)


def _portfolio_leverage_ratio(acct: TradingAccountORM | None) -> float | None:
    if acct is None:
        return None
    total_asset = _f(acct.total_asset)
    if total_asset <= 0:
        return None
    raw = acct.raw if isinstance(acct.raw, dict) else {}
    debt = max(
        _f(raw.get("margin_debt")),
        _f(raw.get("debt")),
        _f(raw.get("liabilities")),
        0.0,
    )
    gross_exposure = max(
        _f(raw.get("gross_exposure")),
        _f(raw.get("total_exposure")),
        _f(raw.get("stock_value")),
        _f(raw.get("position_value")),
        _f(acct.market_value) + debt,
    )
    if gross_exposure <= 0:
        return None
    return round(gross_exposure / total_asset, 4)


def _volatility_20d(
    symbol: str,
    quote: dict | None = None,
    *,
    fetch_history: bool = False,
) -> float | None:
    quote = quote or {}
    if quote.get("volatility_20d") is not None:
        return _f(quote.get("volatility_20d"))
    vol_pct = _f(quote.get("vol_20d_pct"))
    if vol_pct > 0:
        return round(vol_pct / 100.0, 4)
    if not fetch_history:
        return None
    try:
        bars = market_service.get_kline(symbol, period="daily", count=40) or []
    except Exception:
        return None
    closes = [_f(bar.get("close")) for bar in bars if _f(bar.get("close")) > 0]
    if len(closes) < 21:
        return None
    returns = [
        (closes[i] - closes[i - 1]) / closes[i - 1]
        for i in range(1, len(closes))
        if closes[i - 1] > 0
    ]
    vol = calculate_volatility(returns, 20)
    if vol is None:
        return None
    return round(vol, 4)


def _industry_weight(
    positions: list[TradingPositionORM],
    *,
    symbol: str,
    industry: str,
    order_amount: float,
    side: str,
    total_asset: float,
) -> float:
    if total_asset <= 0 or not industry:
        return 0.0
    industry_mv = 0.0
    for p in positions:
        if _resolve_industry(p.symbol, p) == industry:
            industry_mv += _f(p.market_value)
    if side == "BUY":
        industry_mv += max(order_amount, 0.0)
    elif side == "SELL":
        industry_mv = max(0.0, industry_mv - max(order_amount, 0.0))
    return round(industry_mv / total_asset, 4)


def _risk_engine_with_settings(settings) -> RiskEngine:
    engine = RiskEngine()
    if "single_stock_max_weight" in engine.rules:
        base = engine.rules["single_stock_max_weight"]
        engine.rules["single_stock_max_weight"] = base.__class__(
            rule_id=base.rule_id,
            rule_type=base.rule_type,
            scope=base.scope,
            threshold=settings.trading_single_stock_max_weight,
            action_on_breach=base.action_on_breach,
            enabled=base.enabled,
            description=base.description,
        )
    if "daily_max_turnover" in engine.rules:
        base = engine.rules["daily_max_turnover"]
        engine.rules["daily_max_turnover"] = base.__class__(
            rule_id=base.rule_id,
            rule_type=base.rule_type,
            scope=base.scope,
            threshold=settings.trading_daily_turnover_limit,
            action_on_breach=base.action_on_breach,
            enabled=base.enabled,
            description=base.description,
        )
    return engine


def _current_account_id(db: Session, mode: str) -> str:
    return _qmt_account_id(db) if mode == "qmt" else "PAPER"


def _portfolio_positions_for_plan(db: Session, account_id: str) -> list[PortfolioPosition]:
    positions = _positions_for_account(db, account_id)
    items: list[PortfolioPosition] = []
    for pos in positions:
        items.append(PortfolioPosition(
            position_id=str(pos.id or f"{pos.account_id}:{pos.symbol}"),
            account_id=pos.account_id,
            symbol=pos.symbol,
            quantity=pos.quantity,
            available_quantity=pos.available_quantity,
            avg_cost=_f(pos.avg_cost),
            market_value=_f(pos.market_value),
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            updated_at=pos.updated_at or _now(),
        ))
    return items


def _signal_score_from_scan_result(result: dict) -> float:
    ai = result.get("ai_analysis") or {}
    action = str(ai.get("action") or "BUY").upper()
    if action not in {"BUY", "HOLD"}:
        return 0.0
    evo = result.get("evolution") or {}
    probability = max(_f(evo.get("probability"), 0.5), 0.1)
    expected_return = _f(evo.get("expected_return_pct"))
    if expected_return <= 0:
        expected_return = max(_f((result.get("trade_plan") or {}).get("expected_return_pct")), 0.0)
    if expected_return <= 0:
        expected_return = max(_f(result.get("score")) / 100.0, 0.0)
    score = expected_return * probability
    if action == "HOLD":
        score *= 0.5
    return round(max(score, 0.0), 4)


def _scan_result_name(result: dict) -> str:
    return str(result.get("name") or result.get("symbol") or "")


def _weighting_scheme(value: str | None) -> WeightingScheme:
    try:
        return WeightingScheme(str(value or WeightingScheme.RISK_ADJUSTED.value))
    except Exception:
        return WeightingScheme.RISK_ADJUSTED


def _quote_map(symbols: list[str]) -> dict[str, dict]:
    if not symbols:
        return {}
    try:
        return {
            q["symbol"]: q
            for q in market_service.get_realtime_quotes(symbols)
            if isinstance(q, dict) and q.get("symbol")
        }
    except Exception:
        return {}


def _price_for_position(pos: TradingPositionORM, quotes: dict[str, dict]) -> float:
    quote = quotes.get(pos.symbol) or {}
    price = _f(quote.get("price"))
    if price > 0:
        return price
    if pos.quantity > 0 and _f(pos.market_value) > 0:
        return round(_f(pos.market_value) / pos.quantity, 4)
    return _f(pos.avg_cost)


def _blocked_risk(
    reason: str,
    *,
    rule: str = "order",
    account_id: str = "",
    metrics: dict | None = None,
) -> dict:
    return {
        "allowed": False,
        "reason": reason,
        "decision": "BLOCK",
        "checks": [{"rule": rule, "decision": "BLOCK", "message": reason}],
        "metrics": {"account_id": account_id, **(metrics or {})},
    }


def _trading_mode() -> str:
    return os.getenv("QUANT_TRADING_MODE", get_settings().trading_mode).strip().lower()


def _qmt_live_safety_check() -> tuple[bool, str, dict]:
    settings = get_settings()
    if _trading_mode() != "qmt":
        return True, "", {}

    issues: list[str] = []
    provider = str(settings.market_data_provider or "").strip().lower()
    if provider == "mock":
        issues.append("QMT live trading cannot use mock market data")
    if not settings.auth_enabled:
        issues.append("QMT live trading requires API authentication")
    gateway_key = os.getenv("QUANT_QMT_GATEWAY_API_KEY", settings.qmt_gateway_api_key).strip()
    if not gateway_key:
        issues.append("QMT live trading requires QUANT_QMT_GATEWAY_API_KEY")

    allow_mock_gateway = os.getenv("QUANT_QMT_ALLOW_MOCK_GATEWAY", "").strip().lower() in {"1", "true", "yes", "on"}
    health: dict = {}
    if not issues:
        try:
            health = _qmt_request("GET", "/health")
            backend = str(health.get("backend") or "").strip().lower()
            if backend == "mock" and not allow_mock_gateway:
                issues.append("QMT Gateway is using mock backend; set QUANT_QMT_ALLOW_MOCK_GATEWAY=true only for paper drills")
        except Exception as exc:
            issues.append(f"QMT Gateway health check failed: {exc}")

    if issues:
        reason = "; ".join(issues)
        return False, reason, _blocked_risk(
            reason,
            rule="qmt_live_safety",
            account_id="QMT",
            metrics={
                "market_data_provider": provider,
                "auth_enabled": settings.auth_enabled,
                "qmt_gateway_api_key_configured": bool(gateway_key),
                "qmt_gateway_health": health,
                "allow_mock_gateway": allow_mock_gateway,
            },
        )
    return True, "", {
        "market_data_provider": provider,
        "qmt_gateway_health": health,
        "allow_mock_gateway": allow_mock_gateway,
    }


def _validate_base_order(side: str, quantity: int, price: float | None) -> tuple[bool, str, dict]:
    if side not in {"BUY", "SELL"}:
        reason = "side must be BUY or SELL"
        return False, reason, _blocked_risk(reason)
    if quantity <= 0:
        reason = "quantity must be positive"
        return False, reason, _blocked_risk(reason)
    if price is None or price <= 0:
        reason = "order requires positive price"
        return False, reason, _blocked_risk(reason)
    return True, "", {"allowed": True, "reason": "", "checks": []}


def _account_for_id(db: Session, account_id: str) -> TradingAccountORM | None:
    if account_id == "PAPER":
        return _paper_account(db)
    return db.query(TradingAccountORM).filter(TradingAccountORM.account_id == account_id).first()


def _validate_account_capacity(
    db: Session,
    *,
    symbol: str,
    side: str,
    quantity: int,
    price: float,
    account_id: str,
    require_synced_account: bool = False,
) -> tuple[bool, str, dict]:
    acct = _account_for_id(db, account_id)
    if require_synced_account and acct is None:
        reason = f"{account_id} account snapshot missing; call /trading/sync before preview/order"
        return False, reason, _blocked_risk(
            reason,
            rule="account_sync",
            account_id=account_id,
            metrics={"requires_sync": True},
        )

    if side == "BUY":
        available_cash = _f(acct.available_cash if acct else 0.0)
        need = price * quantity
        if need > available_cash:
            reason = f"insufficient cash: need {need:.2f}, available {available_cash:.2f}"
            return False, reason, _blocked_risk(
                reason,
                rule="cash",
                account_id=account_id,
                metrics={"required_cash": round(need, 2), "available_cash": round(available_cash, 2)},
            )
    else:
        pos = (
            db.query(TradingPositionORM)
            .filter(TradingPositionORM.account_id == account_id, TradingPositionORM.symbol == symbol)
            .first()
        )
        available = pos.available_quantity if pos else 0
        if not pos or available < quantity:
            reason = f"insufficient position: need {quantity}, available {available}"
            return False, reason, _blocked_risk(
                reason,
                rule="position",
                account_id=account_id,
                metrics={"available_quantity": available},
            )
    return True, "", {"allowed": True, "reason": "", "checks": []}


def _risk_check(
    db: Session,
    *,
    symbol: str,
    side: str,
    quantity: int,
    price: float,
    account_id: str,
    quote: dict | None = None,
) -> dict:
    ok, reason, base_risk = _validate_base_order(side, quantity, price)
    if not ok:
        base_risk["metrics"]["account_id"] = account_id
        return base_risk

    settings = get_settings()
    quote = quote or {}
    pos = (
        db.query(TradingPositionORM)
        .filter(TradingPositionORM.account_id == account_id, TradingPositionORM.symbol == symbol)
        .first()
    )
    acct = _account_for_id(db, account_id)
    if account_id != "PAPER" and acct is None:
        reason = f"{account_id} account snapshot missing; call /trading/sync before preview/order"
        return _blocked_risk(reason, rule="account_sync", account_id=account_id, metrics={"requires_sync": True})

    available = pos.available_quantity if pos else 0
    market_price = _f(quote.get("price"), price)
    prev_close = _f(quote.get("prev_close"), market_price or price)
    name = str(quote.get("name") or (pos.name if pos else "") or "")
    is_st = "ST" in name.upper()
    rules = check_order(
        symbol=symbol,
        side=OrderSide(side),
        quantity=quantity,
        price=price,
        prev_close=prev_close,
        available_quantity=available,
        is_st=is_st,
        block_st=settings.trading_block_st_buy,
        enforce_trading_hours=settings.trading_enforce_hours,
    )

    risk_items = []
    if rules.ok:
        risk_items.append({"rule": "a_share_rules", "decision": "ALLOW", "message": "A 股交易规则通过"})
    else:
        risk_items.extend(
            {"rule": v.value, "decision": "BLOCK", "message": msg}
            for v, msg in zip(rules.violations, rules.messages)
        )

    positions = _positions_for_account(db, account_id)
    total_asset = max(_f(acct.total_asset if acct else 0.0), 1.0)
    current_mv = _f(pos.market_value if pos else 0.0)
    order_amount = max(price, 0.0) * quantity
    target_mv = current_mv + order_amount if side == "BUY" else max(0.0, current_mv - order_amount)
    target_weight = target_mv / total_asset
    current_weight = current_mv / total_asset
    daily_turnover_ratio = (_today_turnover(db, account_id) + order_amount) / total_asset
    industry = _resolve_industry(symbol, pos, quote) or "未知"
    industry_weight = _industry_weight(
        positions,
        symbol=symbol,
        industry=industry,
        order_amount=order_amount,
        side=side,
        total_asset=total_asset,
    )
    position_return = _position_return(pos, market_price)
    portfolio_drawdown = _portfolio_drawdown(acct)
    leverage_ratio = _portfolio_leverage_ratio(acct)
    volatility_20d = _volatility_20d(symbol, quote, fetch_history=False) if side == "BUY" else None

    engine = _risk_engine_with_settings(settings)
    risk_results = engine.validate_recommendation(
        symbol=symbol,
        action=side,
        target_weight=target_weight,
        current_weight=current_weight,
        industry=industry,
        industry_weight=industry_weight,
        position_return=position_return if side == "BUY" else None,
        portfolio_drawdown=portfolio_drawdown if side == "BUY" else None,
        volatility_20d=volatility_20d,
        leverage_ratio=leverage_ratio if side == "BUY" else None,
        daily_turnover_ratio=daily_turnover_ratio if side == "BUY" else None,
    )
    final_decision = engine.get_final_decision(risk_results)
    for item in risk_results:
        risk_items.append({
            "rule": item.rule_id,
            "decision": item.decision.value,
            "passed": item.passed,
            "message": item.message,
            "details": item.details or {},
        })

    blocked = (not rules.ok) or final_decision == RiskDecision.BLOCK
    blocking_messages = [item["message"] for item in risk_items if item.get("decision") == "BLOCK"]
    warning_messages = [
        item["message"]
        for item in risk_items
        if item.get("decision") in {RiskDecision.WARN.value, RiskDecision.DOWNGRADE.value}
    ]
    return {
        "allowed": not blocked,
        "reason": "; ".join(blocking_messages or warning_messages),
        "decision": "BLOCK" if blocked else final_decision.value,
        "checks": risk_items,
        "metrics": {
            "account_id": account_id,
            "total_asset": round(total_asset, 2),
            "target_weight": round(target_weight, 4),
            "current_weight": round(current_weight, 4),
            "daily_turnover_ratio": round(daily_turnover_ratio, 4),
            "available_quantity": available,
            "industry": industry,
            "industry_weight": round(industry_weight, 4),
            "position_return": position_return,
            "market_price": round(market_price, 4),
            "portfolio_drawdown": portfolio_drawdown,
            "leverage_ratio": leverage_ratio,
            "volatility_20d": volatility_20d,
        },
    }


def _validate_qmt_order(
    db: Session,
    *,
    symbol: str,
    side: str,
    quantity: int,
    price: float | None,
    account_id: str,
    quote: dict | None = None,
) -> tuple[bool, str, dict]:
    ok, reason, risk = _validate_base_order(side, quantity, price)
    if not ok:
        risk["metrics"]["account_id"] = account_id
        return False, reason, risk
    ok, reason, risk = _validate_account_capacity(
        db,
        symbol=symbol,
        side=side,
        quantity=quantity,
        price=price,
        account_id=account_id,
        require_synced_account=True,
    )
    if not ok:
        return False, reason, risk
    quote = quote or _quote(symbol)
    risk = _risk_check(db, symbol=symbol, side=side, quantity=quantity, price=price, account_id=account_id, quote=quote)
    if not risk["allowed"]:
        return False, risk["reason"], risk
    return True, "", risk

def _validate_order(db: Session, symbol: str, side: str, quantity: int, price: float | None) -> tuple[bool, str, dict]:
    ok, reason, risk = _validate_base_order(side, quantity, price)
    if not ok:
        return False, reason, risk
    ok, reason, risk = _validate_account_capacity(
        db,
        symbol=symbol,
        side=side,
        quantity=quantity,
        price=price,
        account_id="PAPER",
    )
    if not ok:
        return False, reason, risk
    quote = _quote(symbol)
    risk = _risk_check(db, symbol=symbol, side=side, quantity=quantity, price=price, account_id="PAPER", quote=quote)
    if not risk["allowed"]:
        return False, risk["reason"], risk
    return True, "", risk


def _order_to_dict(o: TradeOrderORM) -> dict:
    return {
        "id": o.id,
        "client_order_id": o.client_order_id,
        "broker_order_id": o.broker_order_id,
        "account_id": o.account_id,
        "broker": o.broker,
        "symbol": o.symbol,
        "name": o.name,
        "side": o.side,
        "order_type": o.order_type,
        "quantity": o.quantity,
        "price": o.price,
        "status": o.status,
        "filled_quantity": o.filled_quantity,
        "avg_fill_price": o.avg_fill_price,
        "source": o.source,
        "strategy": o.strategy,
        "reason": o.reason,
        "error_message": o.error_message,
        "submitted_at": o.submitted_at.isoformat() if o.submitted_at else None,
        "updated_at": o.updated_at.isoformat() if o.updated_at else None,
    }


def _fill_to_dict(f: TradeFillORM) -> dict:
    return {
        "id": f.id,
        "order_id": f.order_id,
        "broker_order_id": f.broker_order_id,
        "symbol": f.symbol,
        "side": f.side,
        "quantity": f.quantity,
        "price": f.price,
        "amount": f.amount,
        "fee": f.fee,
        "filled_at": f.filled_at.isoformat() if f.filled_at else None,
    }


def _trading_position_to_dict(p: TradingPositionORM) -> dict:
    return {
        "id": p.id,
        "account_id": p.account_id,
        "broker": p.broker,
        "symbol": p.symbol,
        "name": p.name,
        "quantity": p.quantity,
        "available_quantity": p.available_quantity,
        "avg_cost": p.avg_cost,
        "market_value": p.market_value,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


def get_account(db: Session) -> dict:
    mode = _trading_mode()
    if mode == "qmt":
        safe, safety_reason, safety_risk = _qmt_live_safety_check()
        if not safe:
            return {
                "mode": "qmt",
                "status": "blocked",
                "ok": False,
                "reason": safety_reason,
                "requires_live_config": True,
                "risk": safety_risk,
            }
        try:
            data = _qmt_request("GET", "/account")
            return {"mode": "qmt", "ok": True, "safety": safety_risk, **data}
        except Exception as e:
            return {"mode": "qmt", "status": "error", "ok": False, "error": str(e)}
    acct = _paper_account(db)
    return {
        "mode": "paper",
        "account_id": acct.account_id,
        "broker": acct.broker,
        "cash": acct.cash,
        "available_cash": acct.available_cash,
        "market_value": acct.market_value,
        "total_asset": acct.total_asset,
        "updated_at": acct.updated_at.isoformat() if acct.updated_at else None,
    }


def list_positions(db: Session) -> list[dict]:
    mode = _trading_mode()
    if mode == "qmt":
        safe, _, _ = _qmt_live_safety_check()
        if not safe:
            return []
        try:
            data = _qmt_request("GET", "/positions")
            items = data.get("items") if isinstance(data, dict) else data
            return items if isinstance(items, list) else []
        except Exception:
            return []
    acct = _paper_account(db)
    positions = (
        db.query(TradingPositionORM)
        .filter(TradingPositionORM.account_id == acct.account_id)
        .order_by(TradingPositionORM.market_value.desc(), TradingPositionORM.symbol.asc())
        .all()
    )
    return [_trading_position_to_dict(p) for p in positions]


def list_orders(db: Session, limit: int = 100) -> list[dict]:
    items = (
        db.query(TradeOrderORM)
        .order_by(TradeOrderORM.submitted_at.desc(), TradeOrderORM.id.desc())
        .limit(max(1, min(limit, 500)))
        .all()
    )
    return [_order_to_dict(o) for o in items]


def list_fills(db: Session, limit: int = 100) -> list[dict]:
    items = (
        db.query(TradeFillORM)
        .order_by(TradeFillORM.filled_at.desc(), TradeFillORM.id.desc())
        .limit(max(1, min(limit, 500)))
        .all()
    )
    return [_fill_to_dict(f) for f in items]


def sync_qmt_state(db: Session, *, limit: int = 200) -> dict:
    """Synchronize QMT Gateway account, positions and order fills into the local ledger."""
    ok, reason, risk = _qmt_live_safety_check()
    if not ok:
        return {
            "ok": False,
            "mode": "qmt",
            "reason": reason,
            "risk": risk,
            "requires_live_config": True,
        }
    account = _sync_qmt_account(db)
    positions = _sync_qmt_positions(db)
    order_result = _sync_qmt_orders(db, limit=limit)
    return {
        "ok": True,
        "mode": "qmt",
        "account": account,
        "positions_synced": positions,
        **order_result,
    }


def _sync_qmt_account(db: Session) -> dict:
    data = _qmt_request("GET", "/account")
    account_id = str(data.get("account_id") or "QMT")
    acct = db.query(TradingAccountORM).filter(TradingAccountORM.account_id == account_id).first()
    if not acct:
        acct = TradingAccountORM(account_id=account_id, broker="qmt")
        db.add(acct)
    acct.cash = _f(data.get("cash"))
    acct.available_cash = _f(data.get("available_cash"), acct.cash)
    acct.market_value = _f(data.get("market_value"))
    acct.total_asset = _f(data.get("total_asset"), acct.cash + acct.market_value)
    acct.raw = _merge_account_raw(acct.raw, data, acct.total_asset)
    acct.updated_at = _now()
    db.flush()
    return {
        "account_id": acct.account_id,
        "cash": acct.cash,
        "available_cash": acct.available_cash,
        "market_value": acct.market_value,
        "total_asset": acct.total_asset,
    }


def _sync_qmt_positions(db: Session) -> int:
    data = _qmt_request("GET", "/positions")
    items = data.get("items") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise RuntimeError("QMT Gateway /positions returned invalid payload")
    account_id = _qmt_account_id(db)
    seen: set[str] = set()
    synced = 0
    for item in items:
        symbol = _normalize_symbol(str(item.get("symbol") or ""))
        if not symbol:
            continue
        seen.add(symbol)
        pos = (
            db.query(TradingPositionORM)
            .filter(TradingPositionORM.account_id == account_id, TradingPositionORM.symbol == symbol)
            .first()
        )
        if not pos:
            pos = TradingPositionORM(account_id=account_id, broker="qmt", symbol=symbol)
            db.add(pos)
        pos.name = str(item.get("name") or item.get("stock_name") or symbol)
        pos.quantity = _i(item.get("quantity"))
        pos.available_quantity = _i(item.get("available_quantity"), pos.quantity)
        pos.avg_cost = _f(item.get("avg_cost"))
        pos.market_value = _f(item.get("market_value"), pos.quantity * pos.avg_cost)
        pos.raw = _jsonable(item)
        pos.updated_at = _now()
        synced += 1

    stale_q = db.query(TradingPositionORM).filter(
        TradingPositionORM.account_id == account_id,
        TradingPositionORM.broker == "qmt",
    )
    if seen:
        stale_q = stale_q.filter(~TradingPositionORM.symbol.in_(seen))
    stale_q.delete(synchronize_session=False)
    db.flush()
    return synced


def _sync_qmt_orders(db: Session, *, limit: int = 200) -> dict:
    data = _qmt_request("GET", "/orders", json=None)
    items = data.get("items") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise RuntimeError("QMT Gateway /orders returned invalid payload")
    account_id = _qmt_account_id(db)
    orders_synced = 0
    fills_created = 0
    for item in items[: max(1, min(limit, 1000))]:
        order, created = _upsert_qmt_order_from_gateway(db, item, account_id=account_id)
        orders_synced += 1 if order else 0
        if order:
            fills_created += _record_incremental_fill(db, order, item)
    db.flush()
    return {"orders_synced": orders_synced, "fills_created": fills_created}


def _qmt_account_id(db: Session) -> str:
    acct = db.query(TradingAccountORM).filter(TradingAccountORM.broker == "qmt").order_by(TradingAccountORM.id.desc()).first()
    return acct.account_id if acct else "QMT"


def _upsert_qmt_order_from_gateway(db: Session, data: dict, *, account_id: str) -> tuple[TradeOrderORM | None, bool]:
    broker_order_id = str(data.get("order_id") or data.get("broker_order_id") or "")
    client_order_id = str(data.get("client_order_id") or "")
    if not broker_order_id and not client_order_id:
        return None, False

    q = db.query(TradeOrderORM).filter(TradeOrderORM.broker == "qmt")
    if broker_order_id:
        order = q.filter(TradeOrderORM.broker_order_id == broker_order_id).first()
    else:
        order = None
    if not order and client_order_id:
        order = q.filter(TradeOrderORM.client_order_id == client_order_id).first()
    created = order is None
    if order is None:
        order = TradeOrderORM(
            client_order_id=client_order_id or f"QMT-{broker_order_id}",
            broker_order_id=broker_order_id,
            account_id=account_id,
            broker="qmt",
            submitted_at=_dt(data.get("submitted_at")),
        )
        db.add(order)

    order.broker_order_id = broker_order_id or order.broker_order_id
    order.account_id = str(data.get("account_id") or order.account_id or account_id)
    order.symbol = _normalize_symbol(str(data.get("symbol") or order.symbol))
    order.name = str(data.get("name") or data.get("stock_name") or order.name or order.symbol)
    order.side = str(data.get("side") or order.side or "").upper()
    order.order_type = str(data.get("order_type") or order.order_type or "LIMIT").upper()
    order.quantity = _i(data.get("quantity"), order.quantity)
    order.price = None if data.get("price") is None else _f(data.get("price"))
    order.status = str(data.get("status") or order.status or "UNKNOWN").upper()
    order.filled_quantity = _i(data.get("filled_quantity"), order.filled_quantity)
    order.avg_fill_price = _f(data.get("avg_fill_price"), order.avg_fill_price)
    order.error_message = str(data.get("error_message") or order.error_message or "")
    order.raw = _jsonable(data)
    order.updated_at = _dt(data.get("updated_at"))
    return order, created


def _record_incremental_fill(db: Session, order: TradeOrderORM, data: dict) -> int:
    filled_qty = _i(data.get("filled_quantity"), order.filled_quantity)
    if filled_qty <= 0:
        return 0
    existing_qty = (
        db.query(TradeFillORM)
        .filter(TradeFillORM.order_id == order.id)
        .with_entities(TradeFillORM.quantity)
        .all()
    )
    already = sum(qty for (qty,) in existing_qty)
    delta = filled_qty - already
    if delta <= 0:
        return 0
    price = _f(data.get("avg_fill_price"), order.avg_fill_price or order.price or 0.0)
    if price <= 0:
        return 0
    db.add(TradeFillORM(
        order_id=order.id,
        broker_order_id=order.broker_order_id,
        symbol=order.symbol,
        side=order.side,
        quantity=delta,
        price=price,
        amount=round(delta * price, 2),
        fee=0.0,
        filled_at=_dt(data.get("updated_at") or data.get("submitted_at")),
        raw=_jsonable({"source": "qmt_sync", "gateway_order": data}),
    ))
    return 1


def preview_order(db: Session, *, symbol: str, side: str, quantity: int, price: float | None = None) -> dict:
    mode = _trading_mode()
    symbol = _normalize_symbol(symbol)
    side = side.upper()
    trade_price = _quote_price(symbol, price)
    if mode == "qmt":
        safe, safety_reason, safety_risk = _qmt_live_safety_check()
        if not safe:
            return {
                "allowed": False,
                "reason": safety_reason,
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "price": trade_price,
                "estimated_amount": round((trade_price or 0) * quantity, 2),
                "mode": mode,
                "risk": safety_risk,
            }
        account_id = _qmt_account_id(db)
        ok, reason, risk = _validate_qmt_order(
            db,
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=trade_price,
            account_id=account_id,
        )
    else:
        ok, reason, risk = _validate_order(db, symbol, side, quantity, trade_price)
    effective_reason = reason or (risk.get("reason") if isinstance(risk, dict) else "") or ""
    return {
        "allowed": ok,
        "reason": effective_reason,
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "price": trade_price,
        "estimated_amount": round((trade_price or 0) * quantity, 2),
        "mode": mode,
        "risk": risk,
    }


def generate_rebalance_plan(
    db: Session,
    *,
    top_n: int = 8,
    min_score: int = 60,
    candidate_pool: int = 30,
    enable_fundamental: bool = True,
    enable_llm: bool = False,
    llm_top_n: int = 8,
    target_horizon_days: int | None = None,
    weighting_scheme: str = WeightingScheme.RISK_ADJUSTED.value,
    use_cache: bool = True,
) -> dict:
    mode = _trading_mode()
    if mode == "qmt":
        safe, safety_reason, safety_risk = _qmt_live_safety_check()
        if not safe:
            return {
                "ok": False,
                "mode": mode,
                "account_id": _qmt_account_id(db),
                "reason": safety_reason,
                "requires_live_config": True,
                "risk": safety_risk,
                "actions": [],
                "target_weights": [],
                "warnings": [safety_reason],
            }
    account_id = _current_account_id(db, mode)
    acct = _account_for_id(db, account_id)
    if mode == "qmt" and acct is None:
        reason = f"{account_id} account snapshot missing; call /trading/sync before rebalance planning"
        return {
            "ok": False,
            "mode": mode,
            "account_id": account_id,
            "reason": reason,
            "requires_sync": True,
            "actions": [],
            "target_weights": [],
            "warnings": [reason],
        }

    acct = acct or _paper_account(db)
    total_asset = max(_f(acct.total_asset), 1.0)

    from apps.api.app.services import scanner_service

    scan = scanner_service.scan_potential_stocks(
        top_n=max(1, min(top_n, 30)),
        min_score=min_score,
        candidate_pool=max(candidate_pool, top_n),
        use_cache=use_cache,
        required_strategies=None,
        enable_fundamental=enable_fundamental,
        enable_llm=enable_llm,
        llm_top_n=llm_top_n,
        target_horizon_days=target_horizon_days,
    )
    recommendations = list(scan.get("results") or [])

    current_positions = _positions_for_account(db, account_id)
    portfolio_positions = _portfolio_positions_for_plan(db, account_id)
    current_symbols = [p.symbol for p in current_positions]
    reco_symbols = [_normalize_symbol(str(item.get("symbol") or "")) for item in recommendations if item.get("symbol")]
    quotes = _quote_map(sorted(set(current_symbols + reco_symbols)))

    signals: dict[str, float] = {}
    current_prices: dict[str, float] = {}
    industry_map: dict[str, str] = {}
    volatilities: dict[str, float] = {}
    recommendation_map: dict[str, dict] = {}

    for item in recommendations:
        symbol = _normalize_symbol(str(item.get("symbol") or ""))
        if not symbol:
            continue
        score = _signal_score_from_scan_result(item)
        if score <= 0:
            continue
        recommendation_map[symbol] = item
        signals[symbol] = score
        price = (
            _f(item.get("price"))
            or _f((item.get("trade_plan") or {}).get("entry_mid"))
            or _f((quotes.get(symbol) or {}).get("price"))
        )
        if price > 0:
            current_prices[symbol] = price
        industry = str((((item.get("fundamental") or {}).get("info") or {}).get("industry") or "")).strip()
        if industry:
            industry_map[symbol] = industry
        vol_pct = _f((item.get("indicators") or {}).get("vol_20d_pct"))
        if vol_pct > 0:
            volatilities[symbol] = round(vol_pct / 100.0, 4)

    for pos in current_positions:
        current_prices[pos.symbol] = current_prices.get(pos.symbol) or _price_for_position(pos, quotes)
        industry = _resolve_industry(pos.symbol, pos, quotes.get(pos.symbol) or {})
        if industry:
            industry_map[pos.symbol] = industry

    if not signals:
        return {
            "ok": True,
            "mode": mode,
            "account_id": account_id,
            "scheme": _weighting_scheme(weighting_scheme).value,
            "scan_run_id": scan.get("scan_run_id"),
            "llm_status": scan.get("llm_status"),
            "signals_considered": 0,
            "target_weights": [],
            "actions": [],
            "warnings": ["扫描结果中没有足够明确的正向信号，未生成目标持仓。"],
            "expected_turnover": 0.0,
            "expected_cash_ratio": 1.0,
            "risk_metrics": {
                "turnover": 0.0,
                "cash_ratio": 1.0,
                "num_positions": 0.0,
                "max_single_weight": 0.0,
            },
            "summary": {
                "recommendations": len(recommendations),
                "actionable_actions": 0,
                "blocked_actions": 0,
            },
            "params": {
                "top_n": top_n,
                "min_score": min_score,
                "candidate_pool": candidate_pool,
                "enable_fundamental": enable_fundamental,
                "enable_llm": enable_llm,
                "llm_top_n": llm_top_n,
                "target_horizon_days": target_horizon_days,
                "use_cache": use_cache,
            },
        }

    constraints = PortfolioConstraints(
        max_single_stock_weight=get_settings().trading_single_stock_max_weight,
        max_industry_weight=0.40,
        max_turnover=get_settings().trading_daily_turnover_limit,
        min_cash_ratio=0.05,
        max_positions=30,
    )
    scheme = _weighting_scheme(weighting_scheme)
    optimizer = PortfolioOptimizer(constraints)
    optimization = optimizer.optimize(
        signals,
        portfolio_positions,
        total_asset,
        current_prices,
        industry_map=industry_map,
        scheme=scheme,
        volatilities=volatilities or None,
    )
    target_weights = optimizer.calculate_target_weights(
        signals,
        portfolio_positions,
        total_asset,
        scheme=scheme,
        volatilities=volatilities or None,
    )

    positions_by_symbol = {pos.symbol: pos for pos in current_positions}
    actions: list[dict] = []
    blocked_actions = 0
    actionable_actions = 0
    simulated_cash = _f(acct.available_cash)
    ordered_actions = sorted(
        optimization.actions,
        key=lambda action: (0 if action.action == "SELL" else 1, action.symbol),
    )
    for action in ordered_actions:
        symbol = action.symbol
        price = _f(current_prices.get(symbol))
        pos = positions_by_symbol.get(symbol)
        quantity = int(action.quantity_change)
        if action.action == "SELL" and pos:
            available = max(int(pos.available_quantity), 0)
            if available > 0:
                quantity = min(quantity, available)
                if quantity <= 0 and action.target_weight <= 0.0001:
                    quantity = available
        if quantity <= 0 or price <= 0:
            continue
        preview = preview_order(db, symbol=symbol, side=action.action, quantity=quantity, price=price)
        estimated_amount = round(price * quantity, 2)
        if action.action == "BUY" and preview.get("allowed") and estimated_amount > simulated_cash + 1e-9:
            reason = f"plan cash budget exceeded: need {estimated_amount:.2f}, remaining {simulated_cash:.2f}"
            preview = {
                **preview,
                "allowed": False,
                "reason": reason,
                "risk": _blocked_risk(
                    reason,
                    rule="plan_cash",
                    account_id=account_id,
                    metrics={
                        "required_cash": estimated_amount,
                        "remaining_cash": round(simulated_cash, 2),
                    },
                ),
            }
        elif preview.get("allowed"):
            if action.action == "SELL":
                simulated_cash += estimated_amount
            elif action.action == "BUY":
                simulated_cash -= estimated_amount
        actionable_actions += 1 if preview.get("allowed") else 0
        blocked_actions += 0 if preview.get("allowed") else 1
        reco = recommendation_map.get(symbol) or {}
        evo = reco.get("evolution") or {}
        trade_plan = reco.get("trade_plan") or {}
        actions.append({
            "symbol": symbol,
            "name": _scan_result_name(reco) or (pos.name if pos else "") or str((quotes.get(symbol) or {}).get("name") or symbol),
            "action": action.action,
            "quantity": quantity,
            "price": round(price, 2),
            "estimated_amount": estimated_amount,
            "current_weight": round(action.current_weight, 4),
            "target_weight": round(target_weights.get(symbol, action.target_weight), 4),
            "weight_gap": round(target_weights.get(symbol, action.target_weight) - action.current_weight, 4),
            "estimated_value_change": round(action.estimated_value_change, 2),
            "reason": action.reason,
            "signal_score": signals.get(symbol, 0.0),
            "probability": evo.get("probability"),
            "expected_return_pct": evo.get("expected_return_pct") or trade_plan.get("expected_return_pct"),
            "risk": preview,
        })

    target_weight_rows = []
    for symbol, weight in sorted(target_weights.items(), key=lambda item: item[1], reverse=True):
        reco = recommendation_map.get(symbol) or {}
        evo = reco.get("evolution") or {}
        trade_plan = reco.get("trade_plan") or {}
        target_weight_rows.append({
            "symbol": symbol,
            "name": _scan_result_name(reco) or str((quotes.get(symbol) or {}).get("name") or symbol),
            "target_weight": round(weight, 4),
            "price": round(_f(current_prices.get(symbol)), 2),
            "industry": industry_map.get(symbol, ""),
            "signal_score": signals.get(symbol, 0.0),
            "probability": evo.get("probability"),
            "expected_return_pct": evo.get("expected_return_pct") or trade_plan.get("expected_return_pct"),
        })

    warnings = list(optimization.warnings)
    if actions and blocked_actions == len(actions):
        warnings.append("所有调仓动作都被当前风控拦截，建议先处理仓位/回撤/现金问题。")

    return {
        "ok": True,
        "mode": mode,
        "account_id": account_id,
        "scheme": scheme.value,
        "scan_run_id": scan.get("scan_run_id"),
        "llm_status": scan.get("llm_status"),
        "signals_considered": len(signals),
        "target_weights": target_weight_rows,
        "actions": actions,
        "warnings": warnings,
        "expected_turnover": round(optimization.expected_turnover, 4),
        "expected_cash_ratio": round(optimization.expected_cash_ratio, 4),
        "risk_metrics": {k: round(v, 4) for k, v in optimization.risk_metrics.items()},
        "summary": {
            "recommendations": len(recommendations),
            "actionable_actions": actionable_actions,
            "blocked_actions": blocked_actions,
        },
        "params": {
            "top_n": top_n,
            "min_score": min_score,
            "candidate_pool": candidate_pool,
            "enable_fundamental": enable_fundamental,
            "enable_llm": enable_llm,
            "llm_top_n": llm_top_n,
            "target_horizon_days": target_horizon_days,
            "use_cache": use_cache,
        },
    }


def place_order(
    db: Session,
    *,
    symbol: str,
    side: str,
    quantity: int,
    order_type: str = "LIMIT",
    price: float | None = None,
    name: str = "",
    source: str = "manual",
    strategy: str = "",
    reason: str = "",
) -> dict:
    mode = _trading_mode()
    symbol = _normalize_symbol(symbol)
    side = side.upper()
    order_type = order_type.upper()
    client_order_id = f"AA-{uuid.uuid4().hex[:16]}"
    now = _now()
    trade_price = _quote_price(symbol, price)
    if not name:
        try:
            q = market_service.get_single_quote(symbol)
            name = q.get("name", symbol) if q else symbol
        except Exception:
            name = symbol

    if mode == "qmt":
        quote = _quote(symbol)
        account_id = _qmt_account_id(db)
        safe, safety_reason, safety_risk = _qmt_live_safety_check()
        if not safe:
            return _rejected_order(
                db,
                client_order_id=client_order_id,
                account_id=account_id,
                broker="qmt",
                symbol=symbol,
                name=name,
                side=side,
                order_type=order_type,
                quantity=quantity,
                price=price,
                source=source,
                strategy=strategy,
                reason=reason,
                error_message=safety_reason,
                raw={"risk": _jsonable(safety_risk)},
                submitted_at=now,
            )
        ok, err, risk = _validate_qmt_order(
            db,
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=trade_price,
            account_id=account_id,
            quote=quote,
        )
        if not ok:
            return _rejected_order(
                db,
                client_order_id=client_order_id,
                account_id=account_id,
                broker="qmt",
                symbol=symbol,
                name=name,
                side=side,
                order_type=order_type,
                quantity=quantity,
                price=price,
                source=source,
                strategy=strategy,
                reason=reason,
                error_message=err or risk["reason"],
                raw={"risk": _jsonable(risk)},
                submitted_at=now,
            )
        return _place_qmt_order(
            db,
            client_order_id=client_order_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type=order_type,
            price=price,
            name=name,
            source=source,
            strategy=strategy,
            reason=reason,
            submitted_at=now,
        )

    with _paper_account_lock:
        ok, err, risk = _validate_order(db, symbol, side, quantity, trade_price)
        status = "FILLED" if ok else "REJECTED"
        order = TradeOrderORM(
            client_order_id=client_order_id,
            broker_order_id=client_order_id,
            account_id="PAPER",
            broker="paper",
            symbol=symbol,
            name=name,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=trade_price if order_type == "LIMIT" else None,
            status=status,
            filled_quantity=quantity if ok else 0,
            avg_fill_price=trade_price if ok else 0.0,
            source=source,
            strategy=strategy,
            reason=reason,
            error_message=err,
            raw={"risk": _jsonable(risk)},
            submitted_at=now,
            updated_at=now,
        )
        db.add(order)
        db.flush()
        if ok:
            amount = trade_price * quantity
            acct = _paper_account(db)
            acct.cash += amount if side == "SELL" else -amount
            db.add(TradeFillORM(
                order_id=order.id,
                broker_order_id=order.broker_order_id,
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=trade_price,
                amount=amount,
                fee=0.0,
                filled_at=now,
                raw={},
            ))
            _upsert_position_after_fill(db, symbol=symbol, name=name, side=side, quantity=quantity, price=trade_price)
            _refresh_paper_account(db, acct)
        db.commit()
        return _order_to_dict(order)


def _rejected_order(
    db: Session,
    *,
    client_order_id: str,
    account_id: str,
    broker: str,
    symbol: str,
    name: str,
    side: str,
    order_type: str,
    quantity: int,
    price: float | None,
    source: str,
    strategy: str,
    reason: str,
    error_message: str,
    raw: dict,
    submitted_at: datetime,
) -> dict:
    order = TradeOrderORM(
        client_order_id=client_order_id,
        broker_order_id=client_order_id,
        account_id=account_id,
        broker=broker,
        symbol=symbol,
        name=name,
        side=side,
        order_type=order_type,
        quantity=quantity,
        price=price,
        status="REJECTED",
        filled_quantity=0,
        avg_fill_price=0.0,
        source=source,
        strategy=strategy,
        reason=reason,
        error_message=error_message,
        raw=raw,
        submitted_at=submitted_at,
        updated_at=_now(),
    )
    db.add(order)
    db.flush()
    return _order_to_dict(order)


def cancel_order(db: Session, order_id: str) -> dict:
    order = (
        db.query(TradeOrderORM)
        .filter((TradeOrderORM.client_order_id == order_id) | (TradeOrderORM.broker_order_id == order_id))
        .first()
    )
    if not order:
        raise KeyError(order_id)
    if order.status in {"FILLED", "CANCELLED", "REJECTED"}:
        return _order_to_dict(order)
    if order.broker == "qmt":
        try:
            data = _qmt_request("POST", f"/orders/{order.broker_order_id}/cancel")
            order.status = data.get("status", "CANCELLED")
            order.raw = _jsonable(data)
        except Exception as e:
            order.error_message = str(e)
    else:
        order.status = "CANCELLED"
    order.updated_at = _now()
    return _order_to_dict(order)


def _place_qmt_order(db: Session, **kwargs) -> dict:
    payload = {
        "symbol": kwargs["symbol"],
        "side": kwargs["side"],
        "quantity": kwargs["quantity"],
        "order_type": kwargs["order_type"],
        "price": kwargs["price"],
        "client_order_id": kwargs["client_order_id"],
    }
    try:
        data = _qmt_request("POST", "/orders", json=payload)
    except Exception as e:
        data = {"status": "REJECTED", "error_message": str(e)}
    order = TradeOrderORM(
        client_order_id=kwargs["client_order_id"],
        broker_order_id=str(data.get("order_id") or ""),
        account_id=str(data.get("account_id") or "QMT"),
        broker="qmt",
        symbol=kwargs["symbol"],
        name=kwargs["name"],
        side=kwargs["side"],
        order_type=kwargs["order_type"],
        quantity=kwargs["quantity"],
        price=kwargs["price"],
        status=str(data.get("status") or "REJECTED"),
        filled_quantity=int(data.get("filled_quantity") or 0),
        avg_fill_price=float(data.get("avg_fill_price") or 0.0),
        source=kwargs["source"],
        strategy=kwargs["strategy"],
        reason=kwargs["reason"],
        error_message=str(data.get("error_message") or ""),
        raw=_jsonable(data),
        submitted_at=kwargs["submitted_at"],
        updated_at=_now(),
    )
    db.add(order)
    db.flush()
    _record_incremental_fill(db, order, data)
    return _order_to_dict(order)


def _qmt_request(method: str, path: str, json: dict | None = None) -> dict:
    settings = get_settings()
    base = os.getenv("QUANT_QMT_GATEWAY_URL", settings.qmt_gateway_url).rstrip("/")
    headers = {}
    api_key = os.getenv("QUANT_QMT_GATEWAY_API_KEY", settings.qmt_gateway_api_key)
    if api_key:
        headers["X-API-Key"] = api_key
    timeout = 3.0 if method.upper() == "GET" and path == "/health" else 20.0
    with httpx.Client(timeout=timeout) as client:
        r = client.request(method, f"{base}{path}", json=json, headers=headers)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, dict) else {"items": data}
