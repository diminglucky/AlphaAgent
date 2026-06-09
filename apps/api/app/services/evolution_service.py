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
from collections import Counter
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
from libs.quant_core.models import MarketBar
from libs.recommendations.signal_validator import validate_signal_quality
from libs.research.backtest import BacktestConfig
from libs.research.walk_forward import WalkForwardConfig, WalkForwardResult, WalkForwardValidator

log = logging.getLogger("quant.evolution")
_validation_task: asyncio.Task | None = None
_validation_last_run: dict[str, Any] | None = None
_auto_scan_task: asyncio.Task | None = None
_auto_scan_last_run: dict[str, Any] | None = None
_failure_alert_last_sent_at: dict[str, datetime] = {}
_failure_alert_last_event: dict[str, Any] | None = None

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
AUTO_EVOLVE_HOLDOUT_RATIO = 0.2
AUTO_EVOLVE_MIN_HOLDOUT_SAMPLES = 1
AUTO_EVOLVE_MIN_SIGNAL_IC = 0.03
AUTO_EVOLVE_MIN_SIGNAL_WIN_RATE = 0.52
AUTO_EVOLVE_WALK_FORWARD_MIN_SAMPLES = 12
AUTO_EVOLVE_WALK_FORWARD_MIN_DATES = 12
AUTO_EVOLVE_WALK_FORWARD_MIN_PROFITABLE_FOLDS = 0.50
AUTO_EVOLVE_WALK_FORWARD_RETURN_TOLERANCE = 0.001
AUTO_EVOLVE_WALK_FORWARD_CONSISTENCY_TOLERANCE = 0.02
AUTO_EVOLVE_WALK_FORWARD_DRAWDOWN_TOLERANCE = 0.03
FEATURE_LABELS = {
    "technical": "技术形态",
    "fundamental": "基本面质量",
    "flow": "资金流",
    "industry": "行业强度",
    "northbound": "北向资金",
    "research": "研报关注",
    "reduction_risk": "减持风险",
    "ai": "AI 置信度",
    "strategy": "策略共振",
    "volume": "量能",
    "momentum": "动量",
    "risk": "风险质量",
}
ERROR_TYPE_LABELS = {
    "none": "无明显错误",
    "target_too_aggressive": "目标过高",
    "stop_loss_hit": "回撤/止损风险",
    "timing_horizon_mismatch": "节奏或周期错配",
    "overconfident_false_positive": "高置信误判",
    "weak_signal_quality": "信号质量不足",
    "false_positive": "方向误判",
}
VERDICT_LABELS = {
    "hit_target": "达到目标",
    "profitable_but_target_missed": "有收益但未达目标",
    "stopped_out": "触及止损",
    "gain_faded": "冲高回落",
    "high_confidence_failure": "高置信失败",
    "failed_no_edge": "缺少有效优势",
    "false_positive": "上涨判断失败",
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


def _walk_forward_runtime_params(settings: Any | None = None) -> dict[str, Any]:
    if settings is None:
        from apps.api.app.core.config import get_evolution_settings

        settings = get_evolution_settings()
    return {
        "min_samples": max(1, int(getattr(settings, "evolution_auto_walk_forward_min_samples", AUTO_EVOLVE_WALK_FORWARD_MIN_SAMPLES))),
        "min_dates": max(1, int(getattr(settings, "evolution_auto_walk_forward_min_dates", AUTO_EVOLVE_WALK_FORWARD_MIN_DATES))),
        "min_profitable_folds": _clamp(_f(getattr(settings, "evolution_auto_walk_forward_min_profitable_folds", AUTO_EVOLVE_WALK_FORWARD_MIN_PROFITABLE_FOLDS)), 0.0, 1.0),
        "return_tolerance": _clamp(_f(getattr(settings, "evolution_auto_walk_forward_return_tolerance", AUTO_EVOLVE_WALK_FORWARD_RETURN_TOLERANCE)), 0.0, 1.0),
        "consistency_tolerance": _clamp(_f(getattr(settings, "evolution_auto_walk_forward_consistency_tolerance", AUTO_EVOLVE_WALK_FORWARD_CONSISTENCY_TOLERANCE)), 0.0, 1.0),
        "drawdown_tolerance": _clamp(_f(getattr(settings, "evolution_auto_walk_forward_drawdown_tolerance", AUTO_EVOLVE_WALK_FORWARD_DRAWDOWN_TOLERANCE)), 0.0, 1.0),
    }


def _failure_alert_runtime_params(settings: Any | None = None) -> dict[str, Any]:
    if settings is None:
        from apps.api.app.core.config import get_evolution_settings

        settings = get_evolution_settings()
    return {
        "enabled": bool(getattr(settings, "evolution_failure_alert_enabled", True)),
        "cooldown_seconds": max(
            0,
            int(getattr(settings, "evolution_failure_alert_cooldown_seconds", 3600) or 0),
        ),
    }


def _compact_failure_context(context: dict[str, Any] | None) -> dict[str, Any]:
    if not context:
        return {}
    allowed = {
        "limit",
        "interval_seconds",
        "validate_time",
        "scan_run_id",
        "results",
        "predictions_created",
        "llm_status",
        "params",
    }
    return {key: value for key, value in context.items() if key in allowed}


def _notify_evolution_failure(
    failure_type: str,
    error: Any,
    *,
    context: dict[str, Any] | None = None,
    settings: Any | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Send a rate-limited operator alert for unattended evolution failures."""
    global _failure_alert_last_event

    params = _failure_alert_runtime_params(settings)
    timestamp = now or _now()
    compact_context = _compact_failure_context(context)
    event: dict[str, Any] = {
        "type": failure_type,
        "error": str(error)[:500],
        "created_at": timestamp.isoformat(),
        "enabled": params["enabled"],
        "cooldown_seconds": params["cooldown_seconds"],
        "context": compact_context,
    }
    if not params["enabled"]:
        event["alert_status"] = "disabled"
        _failure_alert_last_event = event
        return event

    last_sent = _failure_alert_last_sent_at.get(failure_type)
    cooldown = int(params["cooldown_seconds"])
    if last_sent and cooldown > 0:
        next_allowed = last_sent + timedelta(seconds=cooldown)
        if timestamp < next_allowed:
            event.update({
                "alert_status": "suppressed",
                "last_sent_at": last_sent.isoformat(),
                "next_allowed_at": next_allowed.isoformat(),
            })
            _failure_alert_last_event = event
            return event

    from apps.api.app.services import feishu_service

    label_map = {
        "validation_cycle": "自动验证/进化",
        "auto_scan": "自动采样",
        "auto_scan_loop": "自动采样循环",
    }
    label = label_map.get(failure_type, failure_type)
    context_lines = "\n".join(
        f"- {key}: {value}" for key, value in compact_context.items()
    ) or "- 无"
    try:
        sent = feishu_service.send_feishu(
            f"AlphaAgent {label}失败",
            (
                f"**任务：** {label}\n"
                f"**错误：** {event['error']}\n"
                f"**时间：** {timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"**上下文：**\n{context_lines}"
            ),
            color="red",
        )
    except Exception as exc:
        log.warning("evolution failure alert dispatch failed: %s", exc)
        sent = False
    event.update({
        "alert_status": "sent" if sent else "not_configured",
        "sent_at": timestamp.isoformat() if sent else None,
    })
    if sent:
        _failure_alert_last_sent_at[failure_type] = timestamp
    _failure_alert_last_event = event
    return event


def _jsonable(value: Any) -> Any:
    """Make nested scanner payloads safe for SQLAlchemy JSON on SQLite."""
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _prediction_model_config(session: Session, pred: StockPredictionORM) -> dict:
    model = session.get(ModelVersionORM, pred.model_version_id) if pred.model_version_id else None
    return copy.deepcopy((model.config if model else None) or DEFAULT_MODEL_CONFIG)


def _feature_contributions(
    pred: StockPredictionORM,
    config: dict | None = None,
    *,
    limit: int = 8,
) -> list[dict]:
    """Explain which model factors supported or warned against a prediction."""
    cfg = config or DEFAULT_MODEL_CONFIG
    weights = cfg.get("weights") or DEFAULT_MODEL_CONFIG["weights"]
    features = pred.features or {}
    rows: list[dict] = []
    for key, raw_weight in weights.items():
        weight = _f(raw_weight)
        value = _clamp(_f(features.get(key)), 0.0, 1.0)
        if weight >= 0:
            support_score = value * abs(weight)
            risk_score = (1.0 - value) * abs(weight) if key == "risk" else 0.0
            direction = "support" if support_score >= risk_score else "missing_support"
        else:
            support_score = (1.0 - value) * abs(weight)
            risk_score = value * abs(weight)
            direction = "risk" if risk_score > support_score else "support"
        rows.append({
            "key": key,
            "label": FEATURE_LABELS.get(key, key),
            "value": round(value, 4),
            "weight": round(weight, 4),
            "net_score": round(value * weight, 4),
            "support_score": round(support_score, 4),
            "risk_score": round(risk_score, 4),
            "direction": direction,
        })
    rows.sort(key=lambda row: max(abs(row["support_score"]), abs(row["risk_score"])), reverse=True)
    return rows[: max(1, limit)]


def _cause(factor: str, severity: float, message: str, evidence: dict | None = None) -> dict:
    return {
        "factor": factor,
        "severity": round(_clamp(severity, 0.0, 1.0), 4),
        "message": message,
        "evidence": evidence or {},
    }


def _adjustment(action: str, scope: str, message: str, priority: str = "medium") -> dict:
    return {
        "action": action,
        "scope": scope,
        "priority": priority,
        "message": message,
    }


def _diagnose_prediction_outcome(
    pred: StockPredictionORM,
    outcome: PredictionOutcomeORM,
    *,
    config: dict | None = None,
) -> dict:
    """Create a human-readable and machine-readable post-mortem for one prediction."""
    probability = _clamp(_f(pred.probability), 0.0, 1.0)
    realized = _f(outcome.close_return_pct)
    expected = _f(pred.expected_return_pct)
    target = _f(pred.target_return_pct)
    stop_loss = abs(_f(pred.stop_loss_pct))
    max_return = _f(outcome.max_return_pct)
    max_drawdown = _f(outcome.max_drawdown_pct)
    horizon = int(pred.horizon_days or outcome.horizon_days or 0)
    direction_correct = realized > 0
    target_hit = bool(outcome.hit_target)
    stop_hit = bool(outcome.hit_stop)
    expectation_gap = realized - expected
    target_gap = realized - target
    fade_from_high = max_return - realized
    contributions = _feature_contributions(pred, config, limit=8)

    if target_hit and bool(outcome.success):
        verdict = "hit_target"
        error_type = "none"
    elif direction_correct:
        verdict = "profitable_but_target_missed"
        error_type = "target_too_aggressive"
    elif stop_hit or (stop_loss > 0 and max_drawdown <= -stop_loss * 0.75):
        verdict = "stopped_out"
        error_type = "stop_loss_hit"
    elif max_return > 0 and fade_from_high >= max(2.0, target * 0.5):
        verdict = "gain_faded"
        error_type = "timing_horizon_mismatch"
    elif probability >= 0.65:
        verdict = "high_confidence_failure"
        error_type = "overconfident_false_positive"
    elif probability < 0.55:
        verdict = "failed_no_edge"
        error_type = "weak_signal_quality"
    else:
        verdict = "false_positive"
        error_type = "false_positive"

    root_causes: list[dict] = []
    lessons: list[str] = []
    adjustments: list[dict] = []
    feature_penalties: list[dict] = []
    feature_rewards: list[dict] = []
    horizon_bias_delta = 0.0

    if error_type == "none":
        top_driver = next((row for row in contributions if row["support_score"] > 0), None)
        if top_driver:
            root_causes.append(_cause(
                "effective_signal",
                min(1.0, top_driver["support_score"] * 8),
                f"{top_driver['label']} 是本次预测的主要有效信号。",
                {"feature": top_driver["key"], "value": top_driver["value"]},
            ))
            feature_rewards.append({
                "key": top_driver["key"],
                "label": top_driver["label"],
                "suggested_delta": 0.01,
                "reason": "validated_success_driver",
            })
        lessons.append(f"{horizon}日预测达到目标，当前周期的信号组合可以保留并继续积累样本。")
        adjustments.append(_adjustment(
            "reinforce_success_pattern",
            f"horizon:{horizon}",
            "保留本次有效特征组合，但等待更多样本后再大幅增权。",
            "low",
        ))
        horizon_bias_delta = 0.005
    elif error_type == "target_too_aggressive":
        severity = _clamp((target - realized) / max(abs(target), 1.0), 0.0, 1.0)
        root_causes.append(_cause(
            "target_setting",
            severity,
            f"方向判断正确，但{horizon}日目标收益偏高，收盘收益未达到目标。",
            {
                "target_return_pct": round(target, 4),
                "close_return_pct": round(realized, 4),
                "max_return_pct": round(max_return, 4),
            },
        ))
        lessons.append("预测抓到了上涨方向，但目标收益或持有周期需要更贴近真实波动。")
        adjustments.append(_adjustment(
            "lower_or_stage_target",
            f"horizon:{horizon}",
            f"下调{horizon}日目标收益，或把冲高未达标样本按“方向命中但目标过高”单独校准。",
        ))
    elif error_type == "stop_loss_hit":
        severity = _clamp(abs(max_drawdown) / max(stop_loss, 1.0), 0.0, 1.0)
        root_causes.append(_cause(
            "drawdown_risk",
            severity,
            "预测后的最大回撤接近或触及止损，风险过滤不足。",
            {
                "max_drawdown_pct": round(max_drawdown, 4),
                "stop_loss_pct": round(stop_loss, 4),
            },
        ))
        risk_rows = [
            row for row in contributions
            if (row["key"] == "reduction_risk" and row["value"] >= 0.35)
            or (row["key"] == "risk" and row["value"] <= 0.55)
        ]
        for row in risk_rows[:2]:
            feature_penalties.append({
                "key": row["key"],
                "label": row["label"],
                "suggested_delta": -0.02 if row["weight"] >= 0 else -0.01,
                "reason": "underestimated_drawdown_risk",
            })
        lessons.append("这类失败优先说明风险没有被足够惩罚，而不是简单提高买入信号权重。")
        adjustments.append(_adjustment(
            "increase_risk_penalty",
            "features:risk",
            "提高减持风险、低风险质量、过大回撤样本的惩罚权重。",
            "high",
        ))
        horizon_bias_delta = -0.01
    elif error_type == "timing_horizon_mismatch":
        root_causes.append(_cause(
            "timing",
            _clamp(fade_from_high / max(abs(target), 1.0), 0.0, 1.0),
            "预测期内曾经上涨，但收盘验证时收益回落，持有周期或退出规则不匹配。",
            {
                "max_return_pct": round(max_return, 4),
                "close_return_pct": round(realized, 4),
                "fade_from_high_pct": round(fade_from_high, 4),
            },
        ))
        lessons.append("信号可能更适合短周期验证，或需要加入“冲高后保护收益”的评估方式。")
        adjustments.append(_adjustment(
            "shift_horizon_or_add_exit_rule",
            f"horizon:{horizon}",
            "降低当前周期权重，比较更短周期是否更适合这类信号。",
        ))
        horizon_bias_delta = -0.008
    else:
        misleading = [
            row for row in contributions
            if row["weight"] > 0 and row["value"] >= 0.55
        ][:3]
        if misleading:
            labels = "、".join(row["label"] for row in misleading)
            root_causes.append(_cause(
                "misleading_positive_factors",
                _clamp(probability, 0.0, 1.0),
                f"{labels} 给出了较强正向贡献，但真实走势没有兑现。",
                {"features": [{"key": row["key"], "value": row["value"]} for row in misleading]},
            ))
            for row in misleading:
                feature_penalties.append({
                    "key": row["key"],
                    "label": row["label"],
                    "suggested_delta": -0.015,
                    "reason": "false_positive_contributor",
                })
        if probability >= 0.65:
            root_causes.append(_cause(
                "overconfidence",
                probability,
                "模型给出了较高上涨概率，但结果为负收益，概率校准偏乐观。",
                {"probability": round(probability, 4), "close_return_pct": round(realized, 4)},
            ))
            lessons.append("高置信失败要优先用于概率校准，降低类似特征组合的置信度。")
            adjustments.append(_adjustment(
                "lower_confidence_for_pattern",
                f"horizon:{horizon}",
                "降低类似高置信失败样本的概率输出，并检查主导正向因子是否过拟合。",
                "high",
            ))
        else:
            lessons.append("低置信失败说明信号本身优势不足，应提高入选门槛或等待更多确认。")
            adjustments.append(_adjustment(
                "raise_signal_threshold",
                "scanner",
                "提高最低概率/预期收益阈值，减少弱信号进入推荐池。",
            ))
        horizon_bias_delta = -0.01 if probability >= 0.65 else -0.004

    if expectation_gap < -2.0 and error_type != "none":
        root_causes.append(_cause(
            "expectation_gap",
            _clamp(abs(expectation_gap) / 10.0, 0.0, 1.0),
            "真实收益显著低于模型预期收益，预期收益估计偏乐观。",
            {
                "expected_return_pct": round(expected, 4),
                "close_return_pct": round(realized, 4),
                "gap_pct": round(expectation_gap, 4),
            },
        ))

    if not root_causes:
        root_causes.append(_cause(
            "insufficient_evidence",
            0.2,
            "单条样本不足以稳定归因，需要结合更多同类样本判断。",
        ))
    if not lessons:
        lessons.append("该样本应进入同类错误聚合，等待更多样本后再调整模型。")
    if not adjustments:
        adjustments.append(_adjustment(
            "collect_more_samples",
            f"horizon:{horizon}",
            "继续收集同类预测结果，避免单样本过度调整。",
            "low",
        ))

    return {
        "verdict": verdict,
        "verdict_label": VERDICT_LABELS.get(verdict, verdict),
        "error_type": error_type,
        "error_type_label": ERROR_TYPE_LABELS.get(error_type, error_type),
        "direction_correct": direction_correct,
        "target_hit": target_hit,
        "stop_hit": stop_hit,
        "probability": round(probability, 4),
        "probability_pct": round(probability * 100.0, 2),
        "expected_return_pct": round(expected, 4),
        "realized_return_pct": round(realized, 4),
        "max_return_pct": round(max_return, 4),
        "max_drawdown_pct": round(max_drawdown, 4),
        "expectation_gap_pct": round(expectation_gap, 4),
        "target_gap_pct": round(target_gap, 4),
        "fade_from_high_pct": round(fade_from_high, 4),
        "root_causes": root_causes,
        "lessons": lessons,
        "recommended_adjustments": adjustments,
        "feature_contributions": contributions,
        "model_feedback": {
            "probability_error": round(probability - (1.0 if bool(outcome.success) else 0.0), 4),
            "return_error_pct": round(expectation_gap, 4),
            "horizon_bias_delta": round(horizon_bias_delta, 4),
            "feature_penalties": feature_penalties,
            "feature_rewards": feature_rewards,
        },
    }


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


def _estimate_from_features(
    *,
    features: dict,
    config: dict,
    action: str,
    stop_loss: float,
    plan_expected: float,
    horizon_days: int,
) -> dict:
    weights = config.get("weights") or DEFAULT_MODEL_CONFIG["weights"]
    weight_total = sum(abs(_f(v)) for v in weights.values()) or 1.0
    weighted = sum(_f(features.get(k)) * _f(v) for k, v in weights.items()) / weight_total

    action = str(action or "BUY").upper()
    action_adj = 0.06 if action == "BUY" else (0.02 if action == "HOLD" else -0.08)
    trend_adj = _clamp(_f(features.get("ret_5d")) / 100.0, -0.04, 0.05)
    vol_ratio = _f(features.get("vol_ratio"))
    volume_adj = 0.02 if 1.2 <= vol_ratio <= 3.5 else (-0.03 if vol_ratio > 5 else 0.0)
    base_prob = _clamp(0.26 + weighted * 0.58 + action_adj + trend_adj + volume_adj, 0.08, 0.92)

    targets = config.get("targets") or DEFAULT_MODEL_CONFIG["targets"]
    horizon_bias = config.get("horizon_bias") or {}
    target = _f(targets.get(str(horizon_days)), 3.0)
    if horizon_days <= 3:
        horizon_adj = _f(features.get("momentum")) * 0.04 + _f(features.get("volume")) * 0.02 - 0.03
    elif horizon_days <= 10:
        horizon_adj = _f(features.get("technical")) * 0.03 + _f(features.get("strategy")) * 0.02
    else:
        horizon_adj = (
            _f(features.get("fundamental")) * 0.03
            + _f(features.get("flow")) * 0.015
            + _f(features.get("industry")) * 0.02
            + _f(features.get("northbound")) * 0.02
            + _f(features.get("research")) * 0.015
            - _f(features.get("reduction_risk")) * 0.04
            - 0.01
        )
    probability = _clamp(base_prob + horizon_adj + _f(horizon_bias.get(str(horizon_days))), 0.05, 0.95)
    expected_return = probability * target - (1.0 - probability) * stop_loss
    if plan_expected > 0:
        expected_return = expected_return * 0.7 + plan_expected * min(horizon_days / 10.0, 1.0) * 0.3
    return {
        "horizon_days": horizon_days,
        "target_return_pct": round(target, 2),
        "stop_loss_pct": round(stop_loss, 2),
        "probability": round(probability, 4),
        "expected_return_pct": round(expected_return, 4),
        "features": features,
    }


def estimate_predictions(stock: dict, config: dict | None = None) -> list[dict]:
    """Estimate per-horizon probabilities for one scanner result."""
    cfg = config or DEFAULT_MODEL_CONFIG
    features = _extract_features(stock)

    ai = stock.get("ai_analysis") or {}
    action = str(ai.get("action") or "BUY").upper()
    horizons = [int(h) for h in (cfg.get("horizons") or DEFAULT_MODEL_CONFIG["horizons"])]
    stop_loss = _stop_loss_pct(stock, cfg)
    plan_expected = _f((stock.get("trade_plan") or {}).get("expected_return_pct"))
    return [
        _estimate_from_features(
            features=features,
            config=cfg,
            action=action,
            stop_loss=stop_loss,
            plan_expected=plan_expected,
            horizon_days=h,
        )
        for h in horizons
    ]


def _select_estimate_for_ranking(
    estimates: list[dict],
    *,
    target_horizon_days: int | None = None,
) -> tuple[dict | None, str]:
    if not estimates:
        return None, "none"
    if target_horizon_days:
        target = int(target_horizon_days)
        exact = next((e for e in estimates if int(e["horizon_days"]) == target), None)
        if exact:
            return exact, "requested_horizon"
        closest = min(estimates, key=lambda e: abs(int(e["horizon_days"]) - target), default=None)
        if closest:
            return closest, "nearest_requested_horizon"
    return max(estimates, key=lambda x: (x["expected_return_pct"], x["probability"]), default=None), "best_expected_return"


def _normalize_symbol_list(symbols: list[str] | tuple[str, ...] | None, *, limit: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in symbols or []:
        symbol = str(raw or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        out.append(symbol)
        if len(out) >= limit:
            break
    return out


def _recent_prediction_symbols(session: Session, *, limit: int = 20) -> list[str]:
    rows = (
        session.query(StockPredictionORM.symbol)
        .order_by(StockPredictionORM.predicted_at.desc(), StockPredictionORM.id.desc())
        .limit(max(1, limit * 20))
        .all()
    )
    return _normalize_symbol_list([row[0] for row in rows], limit=limit)


def _has_historical_replay_prediction(
    session: Session,
    *,
    symbol: str,
    model_id: int,
    horizon_days: int,
    predicted_at: datetime,
) -> bool:
    candidates = (
        session.query(StockPredictionORM.raw_result)
        .filter(
            StockPredictionORM.symbol == symbol,
            StockPredictionORM.model_version_id == model_id,
            StockPredictionORM.horizon_days == horizon_days,
            StockPredictionORM.predicted_at == predicted_at,
        )
        .all()
    )
    return any((row[0] or {}).get("source") == "historical_replay" for row in candidates)


def _historical_replay_audit(
    *,
    requested_min_gap_days: int,
    effective_min_gap_days: int,
    max_horizon_days: int,
    target_horizons: list[int],
    sample_limit: int,
    bars_count: int,
) -> dict:
    return {
        "mode": "historical_replay",
        "horizon_unit": "trading_bars",
        "target_horizons": target_horizons,
        "requested_bars_count": bars_count,
        "samples_per_symbol": sample_limit,
        "anti_leakage": {
            "uses_future_features": False,
            "feature_window": "only bars up to and including prediction_bar_date",
            "outcome_window": "bars strictly after prediction_bar_date",
            "label_overlap_guard": "effective_min_gap_days >= max_horizon_days",
            "requested_min_gap_days": requested_min_gap_days,
            "effective_min_gap_days": effective_min_gap_days,
            "max_horizon_days": max_horizon_days,
        },
        "limitations": [
            "历史回放用于加速模型校准，不代表真实未来收益承诺。",
            "同一天不同预测周期仍共享同一个预测截面，应结合真实到期样本继续验证。",
            "历史 K 线无法完整模拟公告、停牌、流动性冲击和真实下单滑点。",
        ],
    }


def _sorted_valid_bars(bars: list[dict]) -> list[dict]:
    dated = [(dt, b) for b in bars or [] if (dt := _bar_date(b)) is not None and _f(b.get("close")) > 0]
    dated.sort(key=lambda item: item[0])
    return [b for _, b in dated]


def _mean_or_zero(values: list[float]) -> float:
    clean = [v for v in values if v > 0]
    return mean(clean) if clean else 0.0


def _ret_pct_from_window(bars: list[dict], idx: int, days: int) -> float:
    if idx - days < 0:
        return 0.0
    prev = _f(bars[idx - days].get("close"))
    current = _f(bars[idx].get("close"))
    if prev <= 0 or current <= 0:
        return 0.0
    return (current - prev) / prev * 100.0


def _historical_stock_from_bars(
    *,
    symbol: str,
    name: str,
    bars: list[dict],
    idx: int,
) -> dict:
    current = bars[idx]
    close = _f(current.get("close"))
    high = _f(current.get("high")) or close
    low = _f(current.get("low")) or close
    start = max(0, idx - 20)
    window = bars[start : idx + 1]
    prev_window = bars[max(0, idx - 20) : idx] or window
    ret_5d = _ret_pct_from_window(bars, idx, 5)
    ret_20d = _ret_pct_from_window(bars, idx, 20)
    volumes = [_f(b.get("volume")) for b in prev_window]
    avg_volume = _mean_or_zero(volumes)
    volume = _f(current.get("volume"))
    vol_ratio = volume / avg_volume if avg_volume > 0 and volume > 0 else 1.0
    high_20 = max([_f(b.get("high")) or _f(b.get("close")) for b in window] or [high])
    low_20 = min([_f(b.get("low")) or _f(b.get("close")) for b in window] or [low])
    avg_close_20 = _mean_or_zero([_f(b.get("close")) for b in window])
    trend_vs_ma = (close - avg_close_20) / avg_close_20 * 100.0 if avg_close_20 > 0 else 0.0
    range_position = (close - low_20) / (high_20 - low_20) if high_20 > low_20 else 0.5
    breakout_bonus = 8.0 if high_20 > 0 and close >= high_20 * 0.985 else 0.0
    volume_score = _clamp((vol_ratio - 0.6) / 2.4, 0.0, 1.0) * 20.0
    momentum_score = _clamp((ret_5d + 6.0) / 18.0, 0.0, 1.0) * 15.0
    technical_score = _clamp(
        48.0
        + ret_5d * 2.0
        + ret_20d * 0.8
        + trend_vs_ma * 1.1
        + (range_position - 0.5) * 14.0
        + breakout_bonus
        + min(max(vol_ratio - 1.0, -0.5), 2.0) * 5.0,
        15.0,
        95.0,
    )
    action = "BUY" if technical_score >= 55 else "HOLD"
    confidence = int(_clamp(technical_score + abs(ret_5d) * 0.8, 35.0, 90.0))
    stop_loss = close * 0.94 if close > 0 else 0.0
    expected_return = _clamp(ret_5d * 0.35 + ret_20d * 0.12 + (vol_ratio - 1.0) * 1.2, -4.0, 10.0)
    return {
        "symbol": symbol,
        "name": name or symbol,
        "price": round(close, 4),
        "change_pct": round(_f(current.get("change_pct")) or _ret_pct_from_window(bars, idx, 1), 4),
        "score": int(round(technical_score)),
        "dim_scores": {
            "volume": round(volume_score, 4),
            "momentum": round(momentum_score, 4),
        },
        "indicators": {
            "ret_5d": round(ret_5d, 4),
            "ret_20d": round(ret_20d, 4),
            "vol_ratio": round(vol_ratio, 4),
        },
        "strategies": [{"name": "历史回放动量"}] if technical_score >= 55 else [],
        "fundamental": {
            "quality": 12,
            "flow_score": 12,
            "industry_score": 8,
            "northbound_score": 7,
            "research_score": 6,
            "insider_reduction_score": 3,
        },
        "ai_analysis": {
            "action": action,
            "confidence": confidence,
            "risk_level": "中" if technical_score >= 45 else "高",
        },
        "trade_plan": {
            "entry_low": round(close * 0.99, 4),
            "entry_mid": round(close, 4),
            "stop_loss": round(stop_loss, 4),
            "expected_return_pct": round(expected_return, 4),
            "source": "historical_replay",
        },
        "raw_bar": _jsonable(current),
    }


def enrich_scan_results_with_model(
    results: list[dict],
    db: Session | None = None,
    target_horizon_days: int | None = None,
) -> dict:
    """Attach active model probabilities to scanner results."""
    with _ctx(db) as session:
        model = ensure_active_model(session)
        cfg = model.config or DEFAULT_MODEL_CONFIG
        enriched: list[dict] = []
        for stock in results or []:
            item = dict(stock)
            estimates = estimate_predictions(item, cfg)
            best, ranking_mode = _select_estimate_for_ranking(
                estimates,
                target_horizon_days=target_horizon_days,
            )
            if best:
                item["evolution"] = {
                    "model_version_id": model.id,
                    "model_version": model.version,
                    "ranking_mode": ranking_mode,
                    "requested_horizon_days": target_horizon_days,
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
    remaining_sell_qty = max(int(fill.quantity or 0), 0)
    if remaining_sell_qty <= 0:
        return 0
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
    fill_matches: dict[str, dict[str, int]] = {}
    for pred in candidates:
        raw = pred.raw_result or {}
        if raw.get("source") != "trade_fill":
            continue
        if account_id and raw.get("account_id") and raw.get("account_id") != account_id:
            continue
        if broker and raw.get("broker") and raw.get("broker") != broker:
            continue
        buy_fill_id = raw.get("fill_id")
        buy_qty = max(int(_f(raw.get("quantity"))), 0)
        if buy_qty <= 0:
            continue
        match_key = str(buy_fill_id or f"prediction:{pred.id}")
        match = fill_matches.get(match_key)
        if match is None:
            if remaining_sell_qty <= 0:
                break
            remaining_before = _remaining_buy_fill_quantity(session, pred, buy_fill_id=buy_fill_id, buy_quantity=buy_qty)
            matched_qty = min(remaining_sell_qty, remaining_before)
            match = {
                "matched_qty": matched_qty,
                "remaining_before": remaining_before,
                "remaining_after": remaining_before - matched_qty,
            }
            fill_matches[match_key] = match
            remaining_sell_qty -= matched_qty
        else:
            matched_qty = match["matched_qty"]
            remaining_before = match["remaining_before"]
        if matched_qty <= 0:
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
            "buy_fill_id": buy_fill_id,
            "sell_fill_id": fill.id,
            "sell_order_id": fill.order_id,
            "sell_price": round(fill.price, 4),
            "buy_quantity": buy_qty,
            "sell_quantity": int(fill.quantity or 0),
            "matched_quantity": matched_qty,
            "remaining_before": remaining_before,
            "remaining_after": match["remaining_after"],
            "holding_days": holding_days,
            "target_return_pct": pred.target_return_pct,
            "stop_loss_pct": pred.stop_loss_pct,
        }
        outcome.details["diagnosis"] = _diagnose_prediction_outcome(
            pred,
            outcome,
            config=_prediction_model_config(session, pred),
        )
        outcome.validated_at = _now()
        if existing is None:
            session.add(outcome)
        pred.status = "validated"
        pred.validated_at = outcome.validated_at
        recorded += 1
    return recorded


def _remaining_buy_fill_quantity(
    session: Session,
    pred: StockPredictionORM,
    *,
    buy_fill_id: Any,
    buy_quantity: int,
) -> int:
    if buy_fill_id in (None, ""):
        return max(buy_quantity, 0)
    matched = 0
    seen_sell_fills: set[str] = set()
    for row in (
        session.query(PredictionOutcomeORM.details)
        .filter(
            PredictionOutcomeORM.symbol == pred.symbol,
            PredictionOutcomeORM.model_version_id == pred.model_version_id,
        )
        .all()
    ):
        details = row[0] or {}
        if details.get("source") != "trade_exit":
            continue
        if str(details.get("buy_fill_id")) != str(buy_fill_id):
            continue
        sell_fill_key = str(details.get("sell_fill_id") or "")
        if sell_fill_key and sell_fill_key in seen_sell_fills:
            continue
        if sell_fill_key:
            seen_sell_fills.add(sell_fill_key)
        matched += int(_f(details.get("matched_quantity")))
    return max(buy_quantity - matched, 0)


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


def _build_outcome_from_future_bars(
    session: Session,
    pred: StockPredictionORM,
    *,
    future: list[dict],
    details_extra: dict | None = None,
    validated_at: datetime | None = None,
) -> PredictionOutcomeORM | None:
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
        **(details_extra or {}),
        "target_price": round(target_price, 4),
        "stop_price": round(stop_price, 4),
        "hit_target_day": None if hit_target_idx is None else hit_target_idx + 1,
        "hit_stop_day": None if hit_stop_idx is None else hit_stop_idx + 1,
    }
    outcome.details["diagnosis"] = _diagnose_prediction_outcome(
        pred,
        outcome,
        config=_prediction_model_config(session, pred),
    )
    outcome.validated_at = validated_at or _now()
    if existing is None:
        session.add(outcome)

    pred.status = "validated"
    pred.validated_at = outcome.validated_at
    return outcome


def _validate_one_prediction(
    session: Session,
    pred: StockPredictionORM,
    *,
    force: bool = False,
) -> PredictionOutcomeORM | None:
    count = max(80, pred.horizon_days + 40)
    bars = market_service.get_kline(pred.symbol, period="daily", count=count) or []
    future = _future_bars_for_prediction(pred, bars, force)
    return _build_outcome_from_future_bars(session, pred, future=future)


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


def backfill_historical_predictions(
    *,
    symbols: list[str] | None = None,
    symbol_limit: int = 10,
    bars_count: int = 260,
    samples_per_symbol: int = 6,
    horizon_days: int | None = None,
    min_gap_days: int = 5,
    db: Session | None = None,
) -> dict:
    """Create immediately validated replay samples from historical K-line windows."""
    with _ctx(db) as session:
        model = ensure_active_model(session)
        cfg = model.config or DEFAULT_MODEL_CONFIG
        selected_symbols = _normalize_symbol_list(symbols, limit=symbol_limit)
        if not selected_symbols:
            selected_symbols = _recent_prediction_symbols(session, limit=symbol_limit)
        if not selected_symbols:
            return {
                "ok": False,
                "reason": "no_symbols",
                "symbols": [],
                "created_predictions": 0,
                "validated_predictions": 0,
            }

        horizons = [int(h) for h in (cfg.get("horizons") or DEFAULT_MODEL_CONFIG["horizons"])]
        if horizon_days:
            requested_horizon = int(horizon_days)
            target_horizons = [requested_horizon] if requested_horizon in horizons else []
        else:
            target_horizons = horizons
        if not target_horizons:
            return {
                "ok": False,
                "reason": "unsupported_horizon",
                "symbols": selected_symbols,
                "supported_horizons": horizons,
                "requested_horizon_days": horizon_days,
                "created_predictions": 0,
                "validated_predictions": 0,
            }
        max_horizon = max(target_horizons or horizons or [20])
        min_history = max(25, max_horizon + 20)
        sample_limit = max(1, min(samples_per_symbol, 50))
        requested_min_gap = max(1, min_gap_days)
        effective_min_gap = max(requested_min_gap, max_horizon)
        replay_audit = _historical_replay_audit(
            requested_min_gap_days=requested_min_gap,
            effective_min_gap_days=effective_min_gap,
            max_horizon_days=max_horizon,
            target_horizons=target_horizons,
            sample_limit=sample_limit,
            bars_count=bars_count,
        )
        run = ScanRunORM(
            model_version_id=model.id,
            source="historical_replay",
            params=_jsonable({
                "symbols": selected_symbols,
                "symbol_limit": symbol_limit,
                "bars_count": bars_count,
                "samples_per_symbol": samples_per_symbol,
                "horizon_days": horizon_days,
                "min_gap_days": min_gap_days,
                "effective_min_gap_days": effective_min_gap,
                "audit": replay_audit,
            }),
            market_status={"mode": "historical_replay"},
            hot_industries=[],
            scanned=len(selected_symbols),
            candidates=0,
            analyzed=0,
            tier1_count=0,
            tier2_count=None,
            tier3_count=None,
            result_count=0,
            rejected_count=0,
            llm_status="disabled",
            elapsed_ms=0.0,
            created_at=_now(),
        )
        session.add(run)
        session.flush()

        created = 0
        validated = 0
        skipped: list[dict] = []
        symbol_reports: list[dict] = []
        due_cutoff = _now()
        min_gap = effective_min_gap
        for symbol in selected_symbols:
            bars_raw = market_service.get_kline(symbol, period="daily", count=max(bars_count, min_history + sample_limit * min_gap + max_horizon + 5)) or []
            bars = _sorted_valid_bars(bars_raw)
            if len(bars) < min_history + max_horizon + 1:
                skipped.append({"symbol": symbol, "reason": "insufficient_bars", "bars": len(bars)})
                symbol_reports.append({"symbol": symbol, "created": 0, "validated": 0, "skipped": "insufficient_bars"})
                continue
            quote_name = ""
            try:
                quote_name = str((market_service.get_single_quote(symbol) or {}).get("name") or "")
            except Exception:
                quote_name = ""
            latest_prediction_idx = len(bars) - max_horizon - 1
            earliest_idx = 20
            usable_span = latest_prediction_idx - earliest_idx + 1
            if usable_span <= 0:
                skipped.append({"symbol": symbol, "reason": "insufficient_window", "bars": len(bars)})
                symbol_reports.append({"symbol": symbol, "created": 0, "validated": 0, "skipped": "insufficient_window"})
                continue
            step = max(min_gap, usable_span // sample_limit)
            indices = list(range(latest_prediction_idx, earliest_idx - 1, -step))[:sample_limit]
            symbol_created = 0
            symbol_validated = 0
            for rank, idx in enumerate(indices, start=1):
                stock = _historical_stock_from_bars(
                    symbol=symbol,
                    name=quote_name or symbol,
                    bars=bars,
                    idx=idx,
                )
                estimates = estimate_predictions(stock, cfg)
                selected_estimates = [e for e in estimates if int(e["horizon_days"]) in set(target_horizons)]
                if not selected_estimates:
                    continue
                bar_dt = _bar_date(bars[idx])
                if bar_dt is None:
                    continue
                for estimate in selected_estimates:
                    horizon = int(estimate["horizon_days"])
                    future = bars[idx + 1 : idx + 1 + horizon]
                    if len(future) < horizon:
                        continue
                    future_end_dt = _bar_date(future[-1])
                    due_at = future_end_dt or (bar_dt + timedelta(days=horizon))
                    if due_at > due_cutoff:
                        continue
                    if _has_historical_replay_prediction(
                        session,
                        symbol=symbol,
                        model_id=model.id,
                        horizon_days=horizon,
                        predicted_at=bar_dt,
                    ):
                        continue
                    pred = StockPredictionORM(
                        scan_run_id=run.id,
                        model_version_id=model.id,
                        symbol=symbol,
                        name=quote_name or symbol,
                        rank=rank,
                        action=str((stock.get("ai_analysis") or {}).get("action") or "BUY").upper(),
                        horizon_days=horizon,
                        target_return_pct=estimate["target_return_pct"],
                        stop_loss_pct=estimate["stop_loss_pct"],
                        probability=estimate["probability"],
                        expected_return_pct=estimate["expected_return_pct"],
                        confidence=int(_f((stock.get("ai_analysis") or {}).get("confidence"))),
                        score=int(_f(stock.get("score"))),
                        price_at_prediction=_f(stock.get("price")),
                        features=_jsonable(estimate["features"]),
                        trade_plan=_jsonable(stock.get("trade_plan") or {}),
                        raw_result=_jsonable({**stock, "source": "historical_replay"}),
                        status="pending",
                        predicted_at=bar_dt,
                        due_at=due_at,
                    )
                    session.add(pred)
                    session.flush()
                    created += 1
                    symbol_created += 1
                    outcome = _build_outcome_from_future_bars(
                        session,
                        pred,
                        future=future,
                        details_extra={
                            "source": "historical_replay",
                            "prediction_bar_date": bars[idx].get("date"),
                            "future_start_date": future[0].get("date") if future else None,
                            "future_end_date": future[-1].get("date") if future else None,
                            "horizon_unit": "trading_bars",
                            "effective_min_gap_days": effective_min_gap,
                        },
                        validated_at=future_end_dt or due_at,
                    )
                    if outcome:
                        validated += 1
                        symbol_validated += 1
            symbol_reports.append({
                "symbol": symbol,
                "name": quote_name or symbol,
                "bars": len(bars),
                "sample_points": len(indices),
                "effective_min_gap_days": effective_min_gap,
                "created": symbol_created,
                "validated": symbol_validated,
            })

        run.candidates = created
        run.analyzed = created
        run.tier1_count = validated
        run.result_count = validated
        run.rejected_count = len(skipped)
        session.flush()
        diagnostics = get_diagnostics(limit=min(200, max(validated, 1)), db=session)
        summary = get_summary(db=session)
        return {
            "ok": True,
            "scan_run_id": run.id,
            "model_version_id": model.id,
            "model_version": model.version,
            "symbols": selected_symbols,
            "created_predictions": created,
            "validated_predictions": validated,
            "skipped": skipped,
            "symbol_reports": symbol_reports,
            "audit": replay_audit,
            "diagnostics": {
                "ready": diagnostics.get("ready"),
                "sample_count": diagnostics.get("sample_count"),
                "top_error_types": (diagnostics.get("error_types") or [])[:5],
                "top_lessons": (diagnostics.get("lessons") or [])[:5],
            },
            "readiness": summary.get("readiness"),
        }


async def _validation_loop(
    *,
    interval_seconds: int,
    initial_delay_seconds: int,
    limit: int,
    validate_time: str = "",
) -> None:
    if not validate_time and initial_delay_seconds > 0:
        await asyncio.sleep(initial_delay_seconds)
    while True:
        if validate_time:
            await asyncio.sleep(_seconds_until_daily_time(validate_time))
        try:
            cycle_summary = await asyncio.to_thread(run_validation_cycle_once, limit=limit)
            trade_result = cycle_summary.get("trade_result") or {}
            if trade_result.get("predictions_created"):
                log.info("evolution trade fill record: %s", trade_result)
            result = cycle_summary.get("validation_result") or {}
            if result.get("checked"):
                log.info("evolution auto validation: %s", result)
            cycle_result = cycle_summary.get("auto_cycle_result") or {}
            if cycle_result.get("status") not in {"disabled", "insufficient_data"}:
                log.info("evolution auto cycle: %s", cycle_result)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("evolution auto validation failed: %s", e, exc_info=True)
            _notify_evolution_failure(
                "validation_cycle",
                e,
                context={
                    "limit": limit,
                    "interval_seconds": interval_seconds,
                    "validate_time": validate_time,
                },
            )
        if not validate_time:
            await asyncio.sleep(interval_seconds)


def _normalize_validate_time(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parts = raw.split(":")
    if len(parts) != 2:
        return ""
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return ""
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return ""
    return f"{hour:02d}:{minute:02d}"


def _seconds_until_daily_time(validate_time: str, now: datetime | None = None) -> float:
    normalized = _normalize_validate_time(validate_time)
    if not normalized:
        return 0.0
    current = now or datetime.now()
    hour, minute = [int(part) for part in normalized.split(":")]
    target = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= current:
        target += timedelta(days=1)
    return max(0.0, (target - current).total_seconds())


def _compact_auto_cycle_result(result: dict) -> dict:
    if not isinstance(result, dict):
        return {"status": "unknown"}
    compact = {
        "status": result.get("status"),
        "evaluated_predictions": result.get("evaluated_predictions"),
        "min_samples": result.get("min_samples"),
        "reason": result.get("reason"),
        "reasons": result.get("reasons") or [],
        "readiness": result.get("readiness"),
    }
    active_model = result.get("active_model") or {}
    previous_model = result.get("previous_model") or {}
    if active_model.get("version"):
        compact["active_model_version"] = active_model.get("version")
    if previous_model.get("version"):
        compact["previous_model_version"] = previous_model.get("version")
    return {k: v for k, v in compact.items() if v not in (None, [])}


def run_validation_cycle_once(*, limit: int) -> dict:
    """Run one unattended validation/evolution pass and store a compact status."""
    global _validation_last_run
    started_at = _now()
    try:
        trade_result = record_trade_fills(limit=limit)
        validation_result = validate_predictions(limit=limit)
        cycle_result = auto_evolve_cycle()
        summary = {
            "ok": True,
            "started_at": started_at.isoformat(),
            "finished_at": _now().isoformat(),
            "limit": limit,
            "trade_result": trade_result,
            "validation_result": validation_result,
            "auto_cycle_result": _compact_auto_cycle_result(cycle_result),
        }
        _validation_last_run = summary
        return summary
    except Exception as exc:
        summary = {
            "ok": False,
            "started_at": started_at.isoformat(),
            "finished_at": _now().isoformat(),
            "limit": limit,
            "error": str(exc),
        }
        _validation_last_run = summary
        raise


def _auto_scan_params_from_settings(settings: Any) -> dict:
    target_horizon = int(getattr(settings, "evolution_auto_scan_target_horizon_days", 0) or 0)
    return {
        "top_n": int(getattr(settings, "evolution_auto_scan_top_n", 20)),
        "min_score": int(getattr(settings, "evolution_auto_scan_min_score", 50)),
        "candidate_pool": int(getattr(settings, "evolution_auto_scan_candidate_pool", 100)),
        "use_cache": False,
        "enable_fundamental": bool(getattr(settings, "evolution_auto_scan_enable_fundamental", True)),
        "enable_llm": bool(getattr(settings, "evolution_auto_scan_enable_llm", False)),
        "llm_top_n": int(getattr(settings, "evolution_auto_scan_llm_top_n", 8)),
        "target_horizon_days": target_horizon or None,
    }


def run_auto_scan_once() -> dict:
    """Run one scanner sampling pass for continuous model evolution."""
    global _auto_scan_last_run
    from apps.api.app.core.config import get_evolution_settings
    from apps.api.app.services import scanner_service

    settings = get_evolution_settings()
    params = _auto_scan_params_from_settings(settings)
    started_at = _now()
    try:
        output = scanner_service.scan_potential_stocks(**params)
        result = {
            "ok": not bool(output.get("error")),
            "started_at": started_at.isoformat(),
            "finished_at": _now().isoformat(),
            "params": params,
            "scan_run_id": output.get("scan_run_id"),
            "results": len(output.get("results") or []),
            "predictions_created": (output.get("evolution") or {}).get("predictions_created", 0),
            "llm_status": output.get("llm_status"),
            "error": output.get("error"),
        }
    except Exception as e:
        result = {
            "ok": False,
            "started_at": started_at.isoformat(),
            "finished_at": _now().isoformat(),
            "params": params,
            "error": str(e),
        }
    _auto_scan_last_run = result
    return result


async def _auto_scan_loop(
    *,
    interval_seconds: int,
    initial_delay_seconds: int,
) -> None:
    if initial_delay_seconds > 0:
        await asyncio.sleep(initial_delay_seconds)
    while True:
        try:
            result = await asyncio.to_thread(run_auto_scan_once)
            if result.get("ok"):
                log.info("evolution auto scan: %s", result)
            else:
                log.warning("evolution auto scan failed: %s", result)
                _notify_evolution_failure(
                    "auto_scan",
                    result.get("error") or "unknown auto scan failure",
                    context=result,
                )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("evolution auto scan loop failed: %s", e, exc_info=True)
            _notify_evolution_failure(
                "auto_scan_loop",
                e,
                context={"interval_seconds": interval_seconds},
            )
        await asyncio.sleep(interval_seconds)


def ensure_auto_scan_loop_running(
    *,
    interval_seconds: int | None = None,
    initial_delay_seconds: int | None = None,
) -> bool:
    """Start automatic scanner sampling loop when enabled."""
    global _auto_scan_task
    if _auto_scan_task and not _auto_scan_task.done():
        return True

    from apps.api.app.core.config import get_evolution_settings

    settings = get_evolution_settings()
    if not settings.evolution_auto_scan_enabled:
        log.info("evolution auto scan disabled")
        return False
    interval = int(
        interval_seconds
        if interval_seconds is not None
        else settings.evolution_auto_scan_interval_seconds
    )
    if interval <= 0:
        log.info("evolution auto scan interval disabled")
        return False
    initial_delay = int(
        initial_delay_seconds
        if initial_delay_seconds is not None
        else settings.evolution_validate_initial_delay_seconds
    )
    _auto_scan_task = asyncio.create_task(
        _auto_scan_loop(
            interval_seconds=interval,
            initial_delay_seconds=max(0, initial_delay),
        )
    )
    return True


async def stop_auto_scan_loop() -> None:
    global _auto_scan_task
    if not _auto_scan_task:
        return
    _auto_scan_task.cancel()
    try:
        await _auto_scan_task
    except asyncio.CancelledError:
        pass
    finally:
        _auto_scan_task = None


async def restart_auto_scan_loop() -> bool:
    await stop_auto_scan_loop()
    return ensure_auto_scan_loop_running()


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

    from apps.api.app.core.config import get_evolution_settings
    settings = get_evolution_settings()
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
    validate_time = _normalize_validate_time(getattr(settings, "evolution_validate_time", ""))
    _validation_task = asyncio.create_task(
        _validation_loop(
            interval_seconds=interval,
            initial_delay_seconds=max(0, initial_delay),
            limit=max(1, run_limit),
            validate_time=validate_time,
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


async def restart_validation_loop() -> bool:
    await stop_validation_loop()
    return ensure_validation_loop_running()


async def restart_background_loops() -> dict:
    validation_running = await restart_validation_loop()
    auto_scan_running = await restart_auto_scan_loop()
    return {
        "validation_running": validation_running,
        "auto_scan_running": auto_scan_running,
    }


def validation_loop_status() -> dict:
    from apps.api.app.core.config import get_evolution_settings

    settings = get_evolution_settings()
    validate_time = _normalize_validate_time(getattr(settings, "evolution_validate_time", ""))
    validate_schedule = "disabled"
    if settings.evolution_validate_interval_seconds > 0:
        validate_schedule = "daily_time" if validate_time else "interval"
    failure_alert = _failure_alert_runtime_params(settings)
    return {
        "running": _validation_task is not None and not _validation_task.done(),
        "auto_scan_running": _auto_scan_task is not None and not _auto_scan_task.done(),
        "validation_last_run": _validation_last_run,
        "auto_scan_last_run": _auto_scan_last_run,
        "failure_alert_last_event": _failure_alert_last_event,
        "failure_alert_enabled": failure_alert["enabled"],
        "failure_alert_cooldown_seconds": failure_alert["cooldown_seconds"],
        "validate_interval_seconds": settings.evolution_validate_interval_seconds,
        "validate_initial_delay_seconds": settings.evolution_validate_initial_delay_seconds,
        "validate_limit": settings.evolution_validate_limit,
        "validate_time": validate_time,
        "validate_schedule": validate_schedule,
        "auto_scan_enabled": settings.evolution_auto_scan_enabled,
        "auto_scan_interval_seconds": settings.evolution_auto_scan_interval_seconds,
        "auto_scan_top_n": settings.evolution_auto_scan_top_n,
        "auto_scan_min_score": settings.evolution_auto_scan_min_score,
        "auto_scan_candidate_pool": settings.evolution_auto_scan_candidate_pool,
        "auto_scan_enable_fundamental": settings.evolution_auto_scan_enable_fundamental,
        "auto_scan_enable_llm": settings.evolution_auto_scan_enable_llm,
        "auto_scan_llm_top_n": settings.evolution_auto_scan_llm_top_n,
        "auto_scan_target_horizon_days": settings.evolution_auto_scan_target_horizon_days,
        "auto_evolve_enabled": settings.evolution_auto_evolve_enabled,
        "auto_evolve_min_samples": settings.evolution_auto_evolve_min_samples,
        "auto_evolve_min_live_samples": getattr(settings, "evolution_auto_evolve_min_live_samples", 0),
        "auto_promote_min_success_rate": settings.evolution_auto_promote_min_success_rate,
        "auto_promote_min_avg_return_pct": settings.evolution_auto_promote_min_avg_return_pct,
        "auto_promote_max_brier_score": settings.evolution_auto_promote_max_brier_score,
        "auto_promote_max_calibration_error": settings.evolution_auto_promote_max_calibration_error,
        "auto_walk_forward_min_samples": settings.evolution_auto_walk_forward_min_samples,
        "auto_walk_forward_min_dates": settings.evolution_auto_walk_forward_min_dates,
        "auto_walk_forward_min_profitable_folds": settings.evolution_auto_walk_forward_min_profitable_folds,
        "auto_walk_forward_return_tolerance": settings.evolution_auto_walk_forward_return_tolerance,
        "auto_walk_forward_consistency_tolerance": settings.evolution_auto_walk_forward_consistency_tolerance,
        "auto_walk_forward_drawdown_tolerance": settings.evolution_auto_walk_forward_drawdown_tolerance,
        "auto_rollback_enabled": settings.evolution_auto_rollback_enabled,
        "auto_rollback_min_samples": settings.evolution_auto_rollback_min_samples,
        "auto_rollback_min_success_rate": settings.evolution_auto_rollback_min_success_rate,
        "auto_rollback_min_avg_return_pct": settings.evolution_auto_rollback_min_avg_return_pct,
        "auto_rollback_max_brier_score": settings.evolution_auto_rollback_max_brier_score,
    }


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


def _prediction_sample_source(pred: StockPredictionORM, outcome: PredictionOutcomeORM | None = None) -> str:
    outcome_details = (outcome.details or {}) if outcome else {}
    outcome_source = str(outcome_details.get("source") or "")
    raw_source = str((pred.raw_result or {}).get("source") or "")
    if outcome_source == "historical_replay" or raw_source == "historical_replay":
        return "historical_replay"
    if outcome_source == "trade_exit" or raw_source == "trade_fill":
        return "trade_execution"
    return "live_prediction"


SAMPLE_SOURCE_LABELS = {
    "live_prediction": "真实到期预测",
    "historical_replay": "历史回放",
    "trade_execution": "真实成交退出",
}


def _metric_rows_from_pairs(
    pairs: list[tuple[StockPredictionORM, PredictionOutcomeORM]],
    *,
    probability_resolver=None,
) -> list[dict]:
    rows = []
    for pred, out in pairs:
        probability = _clamp(
            probability_resolver(pred, out) if probability_resolver else pred.probability,
            0.0,
            1.0,
        )
        rows.append({
            "horizon_days": int(pred.horizon_days),
            "probability": probability,
            "success": bool(out.success),
            "close_return_pct": _f(out.close_return_pct),
            "max_return_pct": _f(out.max_return_pct),
        })
    return rows


def _compute_metrics_from_rows(rows: list[dict]) -> dict:
    if not rows:
        return {
            "sample_count": 0,
            "success_rate": 0.0,
            "avg_return_pct": 0.0,
            "avg_max_return_pct": 0.0,
            "brier_score": 0.0,
            "calibration_error": 0.0,
            "by_horizon": [],
        }

    actual = [1.0 if row["success"] else 0.0 for row in rows]
    probs = [_clamp(row["probability"], 0.0, 1.0) for row in rows]
    returns = [row["close_return_pct"] for row in rows]
    max_returns = [row["max_return_pct"] for row in rows]
    success_rate = mean(actual)
    brier = mean([(p - a) ** 2 for p, a in zip(probs, actual)])
    cal = abs(mean(probs) - success_rate)

    by_horizon = []
    for horizon in sorted({row["horizon_days"] for row in rows}):
        h_rows = [row for row in rows if row["horizon_days"] == horizon]
        h_actual = [1.0 if row["success"] else 0.0 for row in h_rows]
        h_probs = [_clamp(row["probability"], 0.0, 1.0) for row in h_rows]
        by_horizon.append({
            "horizon_days": horizon,
            "sample_count": len(h_rows),
            "success_rate": round(mean(h_actual), 4),
            "avg_return_pct": round(mean([row["close_return_pct"] for row in h_rows]), 4),
            "avg_max_return_pct": round(mean([row["max_return_pct"] for row in h_rows]), 4),
            "brier_score": round(mean([(p - a) ** 2 for p, a in zip(h_probs, h_actual)]), 4),
            "calibration_error": round(abs(mean(h_probs) - mean(h_actual)), 4),
        })

    return {
        "sample_count": len(rows),
        "success_rate": round(success_rate, 4),
        "avg_return_pct": round(mean(returns), 4),
        "avg_max_return_pct": round(mean(max_returns), 4),
        "brier_score": round(brier, 4),
        "calibration_error": round(cal, 4),
        "by_horizon": by_horizon,
    }


def _compute_metrics_from_pairs(pairs: list[tuple[StockPredictionORM, PredictionOutcomeORM]]) -> dict:
    return _compute_metrics_from_rows(_metric_rows_from_pairs(pairs))


def _compute_metrics_by_sample_source(pairs: list[tuple[StockPredictionORM, PredictionOutcomeORM]]) -> dict:
    grouped: dict[str, list[tuple[StockPredictionORM, PredictionOutcomeORM]]] = {
        "live_prediction": [],
        "historical_replay": [],
        "trade_execution": [],
    }
    for pred, out in pairs:
        grouped.setdefault(_prediction_sample_source(pred, out), []).append((pred, out))
    return {
        key: {
            "key": key,
            "label": SAMPLE_SOURCE_LABELS.get(key, key),
            **_compute_metrics_from_pairs(source_pairs),
        }
        for key, source_pairs in grouped.items()
    }


def _real_world_metric_pairs(
    pairs: list[tuple[StockPredictionORM, PredictionOutcomeORM]],
) -> list[tuple[StockPredictionORM, PredictionOutcomeORM]]:
    return [
        (pred, out)
        for pred, out in pairs
        if _prediction_sample_source(pred, out) != "historical_replay"
    ]


def _live_prediction_metric_pairs(
    pairs: list[tuple[StockPredictionORM, PredictionOutcomeORM]],
) -> list[tuple[StockPredictionORM, PredictionOutcomeORM]]:
    return [
        (pred, out)
        for pred, out in pairs
        if _prediction_sample_source(pred, out) == "live_prediction"
    ]


def _real_world_horizon_health(
    pairs: list[tuple[StockPredictionORM, PredictionOutcomeORM]],
    *,
    min_samples: int = 5,
) -> dict:
    metrics = _compute_metrics_from_pairs(_live_prediction_metric_pairs(pairs))
    rows = []
    for row in metrics.get("by_horizon") or []:
        sample_count = int(row.get("sample_count") or 0)
        success_rate = _f(row.get("success_rate"))
        avg_return = _f(row.get("avg_return_pct"))
        calibration_error = _f(row.get("calibration_error"))
        blockers: list[str] = []
        if sample_count < min_samples:
            status = "insufficient"
            label = "样本不足"
            blockers.append(f"真实预测样本 {sample_count} < {min_samples}")
        elif avg_return < 0 or success_rate < 0.45 or calibration_error > 0.35:
            status = "risk"
            label = "现实风险"
            if avg_return < 0:
                blockers.append("平均收益为负")
            if success_rate < 0.45:
                blockers.append("真实命中率偏低")
            if calibration_error > 0.35:
                blockers.append("概率校准偏差过大")
        elif success_rate >= 0.55 and avg_return > 0 and calibration_error <= 0.25:
            status = "healthy"
            label = "相对健康"
        else:
            status = "watch"
            label = "继续观察"
        rows.append({
            **row,
            "status": status,
            "label": label,
            "min_samples": min_samples,
            "blockers": blockers,
        })

    covered = {int(row["horizon_days"]) for row in rows}
    for horizon in DEFAULT_MODEL_CONFIG["horizons"]:
        if int(horizon) in covered:
            continue
        rows.append({
            "horizon_days": int(horizon),
            "sample_count": 0,
            "success_rate": 0.0,
            "avg_return_pct": 0.0,
            "avg_max_return_pct": 0.0,
            "brier_score": 0.0,
            "calibration_error": 0.0,
            "status": "insufficient",
            "label": "样本不足",
            "min_samples": min_samples,
            "blockers": [f"真实预测样本 0 < {min_samples}"],
        })

    rows.sort(key=lambda item: int(item.get("horizon_days") or 0))
    return {
        "source": "live_prediction",
        "label": SAMPLE_SOURCE_LABELS["live_prediction"],
        "sample_count": metrics.get("sample_count", 0),
        "min_samples_per_horizon": min_samples,
        "rows": rows,
        "summary": {
            "healthy": sum(1 for row in rows if row["status"] == "healthy"),
            "watch": sum(1 for row in rows if row["status"] == "watch"),
            "risk": sum(1 for row in rows if row["status"] == "risk"),
            "insufficient": sum(1 for row in rows if row["status"] == "insufficient"),
        },
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


def _pair_time_key(pair: tuple[StockPredictionORM, PredictionOutcomeORM]) -> tuple:
    pred, out = pair
    return (
        out.validated_at or pred.validated_at or pred.predicted_at or _now(),
        pred.predicted_at or _now(),
        int(pred.id or 0),
    )


def _split_train_holdout_pairs(
    pairs: list[tuple[StockPredictionORM, PredictionOutcomeORM]],
    *,
    holdout_ratio: float = AUTO_EVOLVE_HOLDOUT_RATIO,
    min_holdout: int = AUTO_EVOLVE_MIN_HOLDOUT_SAMPLES,
) -> tuple[list[tuple[StockPredictionORM, PredictionOutcomeORM]], list[tuple[StockPredictionORM, PredictionOutcomeORM]]]:
    if len(pairs) < 2:
        return list(pairs), []
    ordered = sorted(pairs, key=_pair_time_key)
    holdout_size = max(min_holdout, int(round(len(ordered) * holdout_ratio)))
    holdout_size = min(holdout_size, len(ordered) - 1)
    if holdout_size <= 0:
        return ordered, []
    return ordered[:-holdout_size], ordered[-holdout_size:]


def _estimate_prediction_for_config(pred: StockPredictionORM, config: dict) -> dict:
    features = pred.features or {}
    return _estimate_from_features(
        features=features,
        config=config or DEFAULT_MODEL_CONFIG,
        action=str(pred.action or "BUY").upper(),
        stop_loss=_f(pred.stop_loss_pct, _f((config or {}).get("stop_loss_pct"), 8.0)),
        plan_expected=_f((pred.trade_plan or {}).get("expected_return_pct")),
        horizon_days=int(pred.horizon_days or 0),
    )


def _estimate_prediction_probability_for_config(pred: StockPredictionORM, config: dict) -> float:
    estimate = _estimate_prediction_for_config(pred, config)
    return _f(estimate.get("probability"), 0.5)


def _metrics_for_pairs_with_config(
    pairs: list[tuple[StockPredictionORM, PredictionOutcomeORM]],
    config: dict,
) -> dict:
    return _compute_metrics_from_rows(
        _metric_rows_from_pairs(
            pairs,
            probability_resolver=lambda pred, out: _estimate_prediction_probability_for_config(pred, config),
        )
    )


def _compute_signal_quality_for_pairs(
    pairs: list[tuple[StockPredictionORM, PredictionOutcomeORM]],
    config: dict,
) -> dict:
    if not pairs:
        return {
            "sample_count": 0,
            "ready": False,
            "mean_ic": None,
            "mean_win_rate": None,
            "by_horizon": [],
        }

    by_horizon: list[dict] = []
    for horizon in sorted({int(pred.horizon_days or 0) for pred, out in pairs}):
        h_pairs = [(pred, out) for pred, out in pairs if int(pred.horizon_days or 0) == horizon]
        signal_scores: list[float] = []
        forward_returns: list[float] = []
        for pred, out in h_pairs:
            estimate = _estimate_prediction_for_config(pred, config)
            signal_scores.append(_f(estimate.get("expected_return_pct")))
            forward_returns.append(_f(out.close_return_pct))
        result = validate_signal_quality(signal_scores, forward_returns)
        by_horizon.append({
            "horizon_days": horizon,
            "sample_count": result.n_observations,
            "ic": None if result.ic_1d is None else round(result.ic_1d, 4),
            "win_rate": None if result.win_rate_1d is None else round(result.win_rate_1d, 4),
            "avg_return_when_positive": None if result.avg_return_when_positive_1d is None else round(result.avg_return_when_positive_1d, 4),
            "avg_return_when_negative": None if result.avg_return_when_negative_1d is None else round(result.avg_return_when_negative_1d, 4),
            "long_short_spread": None if result.long_short_spread_1d is None else round(result.long_short_spread_1d, 4),
            "useful": result.is_useful_1d,
        })

    meaningful_rows = [row for row in by_horizon if int(row["sample_count"] or 0) >= 4]
    valid_ic_rows = [row for row in meaningful_rows if row["ic"] is not None]
    valid_wr_rows = [row for row in meaningful_rows if row["win_rate"] is not None]

    def _weighted_mean(rows: list[dict], key: str) -> float | None:
        total = sum(int(row["sample_count"] or 0) for row in rows)
        if total <= 0:
            return None
        return round(sum(_f(row[key]) * int(row["sample_count"] or 0) for row in rows) / total, 4)

    return {
        "sample_count": len(pairs),
        "ready": bool(valid_ic_rows or valid_wr_rows),
        "mean_ic": _weighted_mean(valid_ic_rows, "ic"),
        "mean_win_rate": _weighted_mean(valid_wr_rows, "win_rate"),
        "meaningful_horizon_count": len(meaningful_rows),
        "useful_horizon_count": sum(1 for row in by_horizon if row["useful"]),
        "by_horizon": by_horizon,
    }


def _candidate_holdout_reasons(
    candidate_metrics: dict,
    baseline_metrics: dict,
    *,
    prefix: str = "candidate holdout",
) -> list[str]:
    reasons: list[str] = []
    if _f(candidate_metrics.get("brier_score"), 1.0) > _f(baseline_metrics.get("brier_score"), 1.0):
        reasons.append(
            f"{prefix} brier_score {_f(candidate_metrics.get('brier_score'), 1.0):.4f} > "
            f"active {_f(baseline_metrics.get('brier_score'), 1.0):.4f}"
        )
    if _f(candidate_metrics.get("calibration_error"), 1.0) > _f(baseline_metrics.get("calibration_error"), 1.0):
        reasons.append(
            f"{prefix} calibration_error {_f(candidate_metrics.get('calibration_error'), 1.0):.4f} > "
            f"active {_f(baseline_metrics.get('calibration_error'), 1.0):.4f}"
        )
    return reasons


def _candidate_holdout_gate(candidate_metrics: dict, baseline_metrics: dict) -> tuple[bool, list[str]]:
    reasons = _candidate_holdout_reasons(candidate_metrics, baseline_metrics)
    return not reasons, reasons


def _candidate_real_world_holdout_gate(candidate_metrics: dict, baseline_metrics: dict) -> tuple[bool, list[str]]:
    reasons = _candidate_holdout_reasons(
        candidate_metrics,
        baseline_metrics,
        prefix="real-world candidate holdout",
    )
    return not reasons, reasons


def _candidate_signal_quality_reasons(
    candidate_quality: dict,
    baseline_quality: dict,
    *,
    prefix: str = "candidate signal",
) -> list[str]:
    if not candidate_quality.get("ready"):
        return []

    reasons: list[str] = []
    candidate_ic = candidate_quality.get("mean_ic")
    baseline_ic = baseline_quality.get("mean_ic")
    candidate_wr = candidate_quality.get("mean_win_rate")
    baseline_wr = baseline_quality.get("mean_win_rate")

    if candidate_ic is not None and candidate_ic < AUTO_EVOLVE_MIN_SIGNAL_IC:
        reasons.append(
            f"{prefix} ic {_f(candidate_ic):.4f} < {AUTO_EVOLVE_MIN_SIGNAL_IC:.4f}"
        )
    if candidate_wr is not None and candidate_wr < AUTO_EVOLVE_MIN_SIGNAL_WIN_RATE:
        reasons.append(
            f"{prefix} win_rate {_f(candidate_wr):.4f} < {AUTO_EVOLVE_MIN_SIGNAL_WIN_RATE:.4f}"
        )
    if baseline_ic is not None and candidate_ic is not None and candidate_ic < baseline_ic:
        reasons.append(
            f"{prefix} ic {_f(candidate_ic):.4f} < active {_f(baseline_ic):.4f}"
        )
    if baseline_wr is not None and candidate_wr is not None and candidate_wr < baseline_wr:
        reasons.append(
            f"{prefix} win_rate {_f(candidate_wr):.4f} < active {_f(baseline_wr):.4f}"
        )
    return reasons


def _candidate_signal_quality_gate(candidate_quality: dict, baseline_quality: dict) -> tuple[bool, list[str]]:
    reasons = _candidate_signal_quality_reasons(candidate_quality, baseline_quality)
    return not reasons, reasons


def _candidate_real_world_signal_quality_gate(candidate_quality: dict, baseline_quality: dict) -> tuple[bool, list[str]]:
    reasons = _candidate_signal_quality_reasons(
        candidate_quality,
        baseline_quality,
        prefix="real-world candidate signal",
    )
    return not reasons, reasons


def _replay_symbol_for_prediction(pred: StockPredictionORM) -> str:
    return f"{pred.symbol}#prediction:{pred.id or 0}"


def _pair_entry_date(pred: StockPredictionORM, out: PredictionOutcomeORM) -> datetime:
    return pred.predicted_at or out.validated_at or pred.validated_at or _now()


def _bars_for_replay_pair(
    pred: StockPredictionORM,
    out: PredictionOutcomeORM,
) -> list[MarketBar]:
    start = _f(out.start_price) or _f(pred.price_at_prediction)
    if start <= 0:
        return []
    end = _f(out.end_price) or start * (1 + _f(out.close_return_pct) / 100.0)
    if end <= 0:
        return []

    symbol = _replay_symbol_for_prediction(pred)
    entry_day = _pair_entry_date(pred, out).date()
    bars_checked = int(out.bars_checked or pred.horizon_days or 1)
    horizon = max(1, bars_checked)
    max_price = max(_f(out.max_price), start, end)
    min_price = min(_f(out.min_price, start), start, end)

    bars: list[MarketBar] = []
    prev_close = start
    mid_idx = max(1, horizon // 2)
    for idx in range(horizon + 1):
        ratio = idx / horizon
        close = start + (end - start) * ratio
        open_price = start if idx == 0 else prev_close
        high = max(open_price, close)
        low = min(open_price, close)
        if idx == mid_idx:
            high = max(high, max_price)
            low = min(low, min_price)
        bars.append(MarketBar(
            symbol=symbol,
            trade_date=entry_day + timedelta(days=idx),
            open=round(open_price, 4),
            high=round(high, 4),
            low=round(low, 4),
            close=round(close, 4),
            volume=100_000,
            amount=round(close * 100_000, 2),
            turnover_rate=0.5,
            adj_type="qfq",
            data_source="evolution_replay",
        ))
        prev_close = close
    return bars


def _replay_data_for_pairs(
    pairs: list[tuple[StockPredictionORM, PredictionOutcomeORM]],
) -> tuple[dict[str, list[MarketBar]], list[tuple[StockPredictionORM, PredictionOutcomeORM]]]:
    data: dict[str, list[MarketBar]] = {}
    usable_pairs: list[tuple[StockPredictionORM, PredictionOutcomeORM]] = []
    for pred, out in sorted(pairs, key=_pair_time_key):
        bars = _bars_for_replay_pair(pred, out)
        if not bars:
            continue
        data[_replay_symbol_for_prediction(pred)] = bars
        usable_pairs.append((pred, out))
    return data, usable_pairs


def _prediction_is_tradeable_for_config(pred: StockPredictionORM, config: dict) -> bool:
    if str(pred.action or "BUY").upper() != "BUY":
        return False
    estimate = _estimate_prediction_for_config(pred, config)
    probability = _f(estimate.get("probability"))
    expected_return = _f(estimate.get("expected_return_pct"))
    return probability >= 0.55 or expected_return > 0


def _replay_strategy_factory(
    pairs: list[tuple[StockPredictionORM, PredictionOutcomeORM]],
    config: dict,
):
    entries_by_date: dict[Any, list[str]] = {}
    exits_by_date: dict[Any, list[str]] = {}
    for pred, out in pairs:
        if not _prediction_is_tradeable_for_config(pred, config):
            continue
        symbol = _replay_symbol_for_prediction(pred)
        entry_day = _pair_entry_date(pred, out).date()
        horizon = max(1, int(out.bars_checked or pred.horizon_days or 1))
        exit_day = entry_day + timedelta(days=horizon)
        entries_by_date.setdefault(entry_day, []).append(symbol)
        exits_by_date.setdefault(exit_day, []).append(symbol)

    def factory():
        opened: set[str] = set()

        def strategy(trade_date, current_data):
            actions: list[tuple[str, str]] = []
            for symbol in exits_by_date.get(trade_date, []):
                if symbol in opened:
                    actions.append((symbol, "SELL"))
                    opened.remove(symbol)
            for symbol in entries_by_date.get(trade_date, []):
                if symbol in current_data and symbol not in opened:
                    actions.append((symbol, "BUY"))
                    opened.add(symbol)
            return actions

        return strategy

    return factory


def _walk_forward_config_for_replay(
    unique_dates: int,
    params: dict[str, Any] | None = None,
) -> WalkForwardConfig | None:
    p = params or _walk_forward_runtime_params()
    if unique_dates < int(p["min_dates"]):
        return None
    in_sample = max(10, min(60, unique_dates // 2))
    remaining = unique_dates - in_sample
    if remaining < 2:
        return None
    oos = max(1, min(20, remaining // 2))
    if unique_dates < in_sample + oos * 2:
        return None
    return WalkForwardConfig(
        in_sample_bars=in_sample,
        oos_bars=oos,
        step_bars=oos,
        min_folds=2,
        backtest_config=BacktestConfig(
            initial_capital=1_000_000.0,
            max_position_size=0.15,
            max_positions=20,
        ),
    )


def _walk_forward_result_to_dict(result: WalkForwardResult) -> dict:
    fold_trades = [int(fold.metrics.total_trades or 0) for fold in result.folds]
    return {
        "n_folds": result.n_folds,
        "oos_total_return_mean": round(result.oos_total_return_mean, 6),
        "oos_sharpe_mean": round(result.oos_sharpe_mean, 6),
        "oos_max_drawdown_mean": round(result.oos_max_drawdown_mean, 6),
        "oos_win_rate_mean": round(result.oos_win_rate_mean, 6),
        "oos_profit_factor_mean": round(result.oos_profit_factor_mean, 6),
        "pct_profitable_folds": round(result.pct_profitable_folds, 6),
        "consistency_score": round(result.consistency_score, 6),
        "total_trades": sum(fold_trades),
        "folds": [
            {
                "fold_idx": fold.fold_idx,
                "oos_start": fold.oos_start.isoformat(),
                "oos_end": fold.oos_end.isoformat(),
                "total_return": round(fold.metrics.total_return, 6),
                "max_drawdown": round(fold.metrics.max_drawdown, 6),
                "win_rate": round(fold.metrics.win_rate, 6),
                "total_trades": int(fold.metrics.total_trades or 0),
            }
            for fold in result.folds
        ],
    }


def _walk_forward_validation_for_pairs(
    pairs: list[tuple[StockPredictionORM, PredictionOutcomeORM]],
    *,
    baseline_config: dict,
    candidate_config: dict,
    runtime_params: dict[str, Any] | None = None,
) -> dict:
    params = runtime_params or _walk_forward_runtime_params()
    data, usable_pairs = _replay_data_for_pairs(pairs)
    unique_dates = len({bar.trade_date for bars in data.values() for bar in bars})
    cfg = _walk_forward_config_for_replay(unique_dates, params)
    base = {
        "ready": False,
        "sample_count": len(usable_pairs),
        "unique_dates": unique_dates,
    }
    if len(usable_pairs) < int(params["min_samples"]) or cfg is None:
        return {
            **base,
            "reason": "insufficient_walk_forward_history",
            "min_samples": int(params["min_samples"]),
            "min_unique_dates": int(params["min_dates"]),
        }

    validator = WalkForwardValidator(cfg)
    try:
        baseline = validator.run(data, _replay_strategy_factory(usable_pairs, baseline_config))
        candidate = validator.run(data, _replay_strategy_factory(usable_pairs, candidate_config))
    except ValueError as exc:
        return {**base, "reason": str(exc)}

    return {
        **base,
        "ready": True,
        "config": {
            "in_sample_bars": cfg.in_sample_bars,
            "oos_bars": cfg.oos_bars,
            "step_bars": cfg.step_bars,
            "min_folds": cfg.min_folds,
        },
        "thresholds": {
            "min_samples": int(params["min_samples"]),
            "min_dates": int(params["min_dates"]),
            "min_profitable_folds": _f(params["min_profitable_folds"]),
            "return_tolerance": _f(params["return_tolerance"]),
            "consistency_tolerance": _f(params["consistency_tolerance"]),
            "drawdown_tolerance": _f(params["drawdown_tolerance"]),
        },
        "baseline": _walk_forward_result_to_dict(baseline),
        "candidate": _walk_forward_result_to_dict(candidate),
    }


def _walk_forward_readiness_for_pairs(
    pairs: list[tuple[StockPredictionORM, PredictionOutcomeORM]],
    runtime_params: dict[str, Any] | None = None,
) -> dict:
    """Return cheap readiness counters without running walk-forward replay."""
    params = runtime_params or _walk_forward_runtime_params()
    usable_count = 0
    trade_dates = set()
    for pred, out in pairs:
        start = _f(out.start_price) or _f(pred.price_at_prediction)
        if start <= 0:
            continue
        end = _f(out.end_price) or start * (1 + _f(out.close_return_pct) / 100.0)
        if end <= 0:
            continue
        usable_count += 1
        entry_day = _pair_entry_date(pred, out).date()
        horizon = max(1, int(out.bars_checked or pred.horizon_days or 1))
        for idx in range(horizon + 1):
            trade_dates.add(entry_day + timedelta(days=idx))
    unique_dates = len(trade_dates)
    min_samples = int(params["min_samples"])
    min_dates = int(params["min_dates"])
    required_dates = min_dates
    while (
        required_dates < min_dates + 365
        and _walk_forward_config_for_replay(required_dates, params) is None
    ):
        required_dates += 1
    config_ready = _walk_forward_config_for_replay(unique_dates, params) is not None
    ready = usable_count >= min_samples and config_ready
    return {
        "ready": ready,
        "sample_count": usable_count,
        "min_samples": min_samples,
        "sample_gap": max(0, min_samples - usable_count),
        "unique_dates": unique_dates,
        "min_unique_dates": min_dates,
        "required_unique_dates": required_dates,
        "date_gap": max(0, required_dates - unique_dates),
        "config_ready": config_ready,
    }


def _candidate_walk_forward_gate(
    validation: dict,
    runtime_params: dict[str, Any] | None = None,
    *,
    require_ready: bool = False,
) -> tuple[bool, list[str]]:
    params = runtime_params or _walk_forward_runtime_params()
    if not validation.get("ready"):
        if require_ready:
            sample_count = int(validation.get("sample_count") or 0)
            unique_dates = int(validation.get("unique_dates") or 0)
            min_samples = int(validation.get("min_samples") or params["min_samples"])
            min_dates = int(
                validation.get("min_unique_dates")
                or validation.get("min_dates")
                or params["min_dates"]
            )
            reason = str(validation.get("reason") or "not_ready")
            return False, [
                "candidate walk-forward not ready "
                f"({reason}): samples {sample_count}/{min_samples}, "
                f"unique_dates {unique_dates}/{min_dates}"
            ]
        return True, []

    baseline = validation.get("baseline") or {}
    candidate = validation.get("candidate") or {}
    reasons: list[str] = []
    if int(candidate.get("total_trades") or 0) <= 0:
        reasons.append("candidate walk-forward generated no trades")
    if _f(candidate.get("pct_profitable_folds")) < _f(params["min_profitable_folds"]):
        reasons.append(
            f"candidate walk-forward profitable_folds {_f(candidate.get('pct_profitable_folds')):.4f} < "
            f"{_f(params['min_profitable_folds']):.4f}"
        )
    if _f(candidate.get("oos_total_return_mean")) < -_f(params["return_tolerance"]):
        reasons.append(
            f"candidate walk-forward return {_f(candidate.get('oos_total_return_mean')):.4f} < 0"
        )
    if (
        _f(candidate.get("oos_total_return_mean")) + _f(params["return_tolerance"])
        < _f(baseline.get("oos_total_return_mean"))
    ):
        reasons.append(
            f"candidate walk-forward return {_f(candidate.get('oos_total_return_mean')):.4f} < "
            f"active {_f(baseline.get('oos_total_return_mean')):.4f}"
        )
    if (
        _f(candidate.get("consistency_score")) + _f(params["consistency_tolerance"])
        < _f(baseline.get("consistency_score"))
    ):
        reasons.append(
            f"candidate walk-forward consistency {_f(candidate.get('consistency_score')):.4f} < "
            f"active {_f(baseline.get('consistency_score')):.4f}"
        )
    if (
        _f(candidate.get("oos_max_drawdown_mean"))
        > _f(baseline.get("oos_max_drawdown_mean")) + _f(params["drawdown_tolerance"])
    ):
        reasons.append(
            f"candidate walk-forward drawdown {_f(candidate.get('oos_max_drawdown_mean')):.4f} > "
            f"active {_f(baseline.get('oos_max_drawdown_mean')):.4f}"
        )
    return not reasons, reasons


def _promote_candidate(
    session: Session,
    *,
    active: ModelVersionORM,
    candidate: ModelVersionORM,
    metrics: dict,
    thresholds: dict,
    reasons: list[str],
    source: str,
    summary_extra: dict | None = None,
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
            **(summary_extra or {}),
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


def _auto_evolution_readiness(
    *,
    pairs: list[tuple[StockPredictionORM, PredictionOutcomeORM]],
    settings: Any,
    train_pairs: list[tuple[StockPredictionORM, PredictionOutcomeORM]] | None = None,
    holdout_pairs: list[tuple[StockPredictionORM, PredictionOutcomeORM]] | None = None,
) -> dict:
    if train_pairs is None or holdout_pairs is None:
        train_pairs, holdout_pairs = _split_train_holdout_pairs(pairs)
    min_samples = int(getattr(settings, "evolution_auto_evolve_min_samples", 60))
    min_live_samples = int(getattr(settings, "evolution_auto_evolve_min_live_samples", 0) or 0)
    sample_segments = _compute_metrics_by_sample_source(pairs)
    live_metrics = sample_segments.get("live_prediction") or {}
    live_sample_count = int(live_metrics.get("sample_count") or 0)
    wf = _walk_forward_readiness_for_pairs(pairs)
    sample_gap = max(0, min_samples - len(pairs))
    live_sample_gap = max(0, min_live_samples - live_sample_count)
    ready = (
        bool(getattr(settings, "evolution_auto_evolve_enabled", True))
        and sample_gap == 0
        and live_sample_gap == 0
        and bool(train_pairs)
        and bool(holdout_pairs)
        and bool(wf.get("ready"))
    )
    blockers: list[str] = []
    if not getattr(settings, "evolution_auto_evolve_enabled", True):
        blockers.append("auto_evolve_disabled")
    if sample_gap:
        blockers.append("insufficient_validated_predictions")
    if live_sample_gap:
        blockers.append("insufficient_live_predictions")
    if not train_pairs or not holdout_pairs:
        blockers.append("need_train_and_holdout_samples")
    if not wf.get("ready"):
        blockers.append("insufficient_walk_forward_history")
    return {
        "ready": ready,
        "blockers": blockers,
        "evaluated_predictions": len(pairs),
        "min_samples": min_samples,
        "sample_gap": sample_gap,
        "live_sample_count": live_sample_count,
        "min_live_samples": min_live_samples,
        "live_sample_gap": live_sample_gap,
        "sample_segments": sample_segments,
        "train_sample_count": len(train_pairs),
        "holdout_sample_count": len(holdout_pairs),
        "walk_forward": wf,
    }


def _record_auto_evolve_decision(
    session: Session,
    *,
    model: ModelVersionORM,
    status: str,
    metrics: dict,
    promoted: bool = False,
    summary: dict | None = None,
) -> None:
    session.add(EvolutionRunORM(
        model_version_id=model.id,
        status=status,
        evaluated_predictions=int(metrics.get("sample_count") or 0),
        success_rate=_f(metrics.get("success_rate")),
        avg_return_pct=_f(metrics.get("avg_return_pct")),
        brier_score=_f(metrics.get("brier_score")),
        calibration_error=_f(metrics.get("calibration_error")),
        promoted=promoted,
        summary=summary or {},
    ))


def auto_evolve_cycle(db: Session | None = None) -> dict:
    """Run the safe automatic evolution cycle: rollback, then promote/generate."""
    from apps.api.app.core.config import get_evolution_settings

    settings = get_evolution_settings()
    if not settings.evolution_auto_evolve_enabled:
        return {"status": "disabled"}

    with _ctx(db) as session:
        active = ensure_active_model(session)
        pairs = _metric_pairs(session, active.id)
        active_metrics = _compute_metrics_from_pairs(pairs)
        sample_segments = _compute_metrics_by_sample_source(pairs)
        live_metrics = sample_segments.get("live_prediction") or {
            "key": "live_prediction",
            "label": SAMPLE_SOURCE_LABELS["live_prediction"],
            "sample_count": 0,
        }
        real_world_pairs = _real_world_metric_pairs(pairs)
        real_world_metrics = _compute_metrics_from_pairs(real_world_pairs)
        train_pairs, holdout_pairs = _split_train_holdout_pairs(pairs)
        _, real_world_holdout_pairs = _split_train_holdout_pairs(real_world_pairs)
        train_metrics = _compute_metrics_from_pairs(train_pairs)
        holdout_baseline_metrics = _metrics_for_pairs_with_config(
            holdout_pairs,
            active.config or DEFAULT_MODEL_CONFIG,
        )
        holdout_baseline_signal_quality = _compute_signal_quality_for_pairs(
            holdout_pairs,
            active.config or DEFAULT_MODEL_CONFIG,
        )
        real_world_holdout_baseline_metrics = _metrics_for_pairs_with_config(
            real_world_holdout_pairs,
            active.config or DEFAULT_MODEL_CONFIG,
        )
        real_world_holdout_baseline_signal_quality = _compute_signal_quality_for_pairs(
            real_world_holdout_pairs,
            active.config or DEFAULT_MODEL_CONFIG,
        )
        readiness = _auto_evolution_readiness(
            pairs=pairs,
            settings=settings,
            train_pairs=train_pairs,
            holdout_pairs=holdout_pairs,
        )
        thresholds = {
            "min_success_rate": settings.evolution_auto_promote_min_success_rate,
            "min_avg_return_pct": settings.evolution_auto_promote_min_avg_return_pct,
            "max_brier_score": settings.evolution_auto_promote_max_brier_score,
            "max_calibration_error": settings.evolution_auto_promote_max_calibration_error,
        }

        if (
            settings.evolution_auto_rollback_enabled
            and active.parent_id
            and len(real_world_pairs) >= settings.evolution_auto_rollback_min_samples
        ):
            rollback_thresholds = {
                "min_success_rate": settings.evolution_auto_rollback_min_success_rate,
                "min_avg_return_pct": settings.evolution_auto_rollback_min_avg_return_pct,
                "max_brier_score": settings.evolution_auto_rollback_max_brier_score,
            }
            should_rollback, rollback_reasons = _rollback_gate(real_world_metrics, rollback_thresholds)
            parent = session.get(ModelVersionORM, active.parent_id)
            if should_rollback and parent:
                return _rollback_active_model(
                    session,
                    active=active,
                    parent=parent,
                    metrics=real_world_metrics,
                    thresholds=rollback_thresholds,
                    reasons=rollback_reasons,
                )

        min_samples = int(settings.evolution_auto_evolve_min_samples)
        min_live_samples = int(getattr(settings, "evolution_auto_evolve_min_live_samples", 0) or 0)
        if len(pairs) < min_samples:
            reason = "insufficient_validated_predictions"
            _record_auto_evolve_decision(
                session,
                model=active,
                status="insufficient_data",
                metrics=active_metrics,
                summary={
                    "source": "auto_evolve",
                    "metrics": active_metrics,
                    "train_metrics": train_metrics,
                    "holdout_baseline_metrics": holdout_baseline_metrics,
                    "holdout_baseline_signal_quality": holdout_baseline_signal_quality,
                    "real_world_holdout_baseline_metrics": real_world_holdout_baseline_metrics,
                    "real_world_holdout_baseline_signal_quality": real_world_holdout_baseline_signal_quality,
                    "sample_segments": sample_segments,
                    "live_metrics": live_metrics,
                    "real_world_metrics": real_world_metrics,
                    "readiness": readiness,
                    "reason": reason,
                },
            )
            session.flush()
            return {
                "status": "insufficient_data",
                "min_samples": min_samples,
                "evaluated_predictions": len(pairs),
                "metrics": active_metrics,
                "train_sample_count": len(train_pairs),
                "holdout_sample_count": len(holdout_pairs),
                "holdout_baseline_signal_quality": holdout_baseline_signal_quality,
                "real_world_holdout_baseline_metrics": real_world_holdout_baseline_metrics,
                "real_world_holdout_baseline_signal_quality": real_world_holdout_baseline_signal_quality,
                "sample_segments": sample_segments,
                "live_metrics": live_metrics,
                "real_world_metrics": real_world_metrics,
                "readiness": readiness,
                "reason": reason,
            }
        if int(live_metrics.get("sample_count") or 0) < min_live_samples:
            reason = "insufficient_live_predictions"
            _record_auto_evolve_decision(
                session,
                model=active,
                status="insufficient_data",
                metrics=active_metrics,
                summary={
                    "source": "auto_evolve",
                    "metrics": active_metrics,
                    "train_metrics": train_metrics,
                    "holdout_baseline_metrics": holdout_baseline_metrics,
                    "holdout_baseline_signal_quality": holdout_baseline_signal_quality,
                    "real_world_holdout_baseline_metrics": real_world_holdout_baseline_metrics,
                    "real_world_holdout_baseline_signal_quality": real_world_holdout_baseline_signal_quality,
                    "sample_segments": sample_segments,
                    "live_metrics": live_metrics,
                    "real_world_metrics": real_world_metrics,
                    "readiness": readiness,
                    "reason": reason,
                },
            )
            session.flush()
            return {
                "status": "insufficient_data",
                "min_samples": min_samples,
                "min_live_samples": min_live_samples,
                "evaluated_predictions": len(pairs),
                "metrics": active_metrics,
                "train_sample_count": len(train_pairs),
                "holdout_sample_count": len(holdout_pairs),
                "holdout_baseline_signal_quality": holdout_baseline_signal_quality,
                "real_world_holdout_baseline_metrics": real_world_holdout_baseline_metrics,
                "real_world_holdout_baseline_signal_quality": real_world_holdout_baseline_signal_quality,
                "sample_segments": sample_segments,
                "live_metrics": live_metrics,
                "real_world_metrics": real_world_metrics,
                "readiness": readiness,
                "reason": reason,
            }
        if not train_pairs or not holdout_pairs:
            reason = "need_train_and_holdout_samples"
            _record_auto_evolve_decision(
                session,
                model=active,
                status="insufficient_data",
                metrics=active_metrics,
                summary={
                    "source": "auto_evolve",
                    "metrics": active_metrics,
                    "train_metrics": train_metrics,
                    "holdout_baseline_metrics": holdout_baseline_metrics,
                    "holdout_baseline_signal_quality": holdout_baseline_signal_quality,
                    "real_world_holdout_baseline_metrics": real_world_holdout_baseline_metrics,
                    "real_world_holdout_baseline_signal_quality": real_world_holdout_baseline_signal_quality,
                    "sample_segments": sample_segments,
                    "live_metrics": live_metrics,
                    "real_world_metrics": real_world_metrics,
                    "readiness": readiness,
                    "reason": reason,
                },
            )
            session.flush()
            return {
                "status": "insufficient_data",
                "min_samples": min_samples,
                "evaluated_predictions": len(pairs),
                "metrics": active_metrics,
                "train_sample_count": len(train_pairs),
                "holdout_sample_count": len(holdout_pairs),
                "holdout_baseline_signal_quality": holdout_baseline_signal_quality,
                "real_world_holdout_baseline_metrics": real_world_holdout_baseline_metrics,
                "real_world_holdout_baseline_signal_quality": real_world_holdout_baseline_signal_quality,
                "sample_segments": sample_segments,
                "live_metrics": live_metrics,
                "real_world_metrics": real_world_metrics,
                "readiness": readiness,
                "reason": reason,
            }

        live_allowed, live_reasons = _promotion_gate(live_metrics, thresholds)
        if min_live_samples > 0 and not live_allowed:
            reasons = [f"live_prediction {reason}" for reason in live_reasons]
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
                    "train_metrics": train_metrics,
                    "holdout_baseline_metrics": holdout_baseline_metrics,
                    "holdout_baseline_signal_quality": holdout_baseline_signal_quality,
                    "real_world_holdout_baseline_metrics": real_world_holdout_baseline_metrics,
                    "real_world_holdout_baseline_signal_quality": real_world_holdout_baseline_signal_quality,
                    "sample_segments": sample_segments,
                    "live_metrics": live_metrics,
                    "real_world_metrics": real_world_metrics,
                    "readiness": readiness,
                    "thresholds": thresholds,
                    "reasons": reasons,
                    "reason": "live_prediction_quality_gate_failed",
                },
            ))
            session.flush()
            return {
                "status": "auto_blocked",
                "evaluated_predictions": len(pairs),
                "metrics": active_metrics,
                "train_metrics": train_metrics,
                "holdout_baseline_metrics": holdout_baseline_metrics,
                "holdout_baseline_signal_quality": holdout_baseline_signal_quality,
                "real_world_holdout_baseline_metrics": real_world_holdout_baseline_metrics,
                "real_world_holdout_baseline_signal_quality": real_world_holdout_baseline_signal_quality,
                "sample_segments": sample_segments,
                "live_metrics": live_metrics,
                "real_world_metrics": real_world_metrics,
                "readiness": readiness,
                "thresholds": thresholds,
                "reasons": reasons,
                "reason": "live_prediction_quality_gate_failed",
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
                    "train_metrics": train_metrics,
                    "holdout_baseline_metrics": holdout_baseline_metrics,
                    "holdout_baseline_signal_quality": holdout_baseline_signal_quality,
                    "sample_segments": sample_segments,
                    "live_metrics": live_metrics,
                    "real_world_metrics": real_world_metrics,
                    "readiness": readiness,
                    "thresholds": thresholds,
                    "reasons": reasons,
                },
            ))
            session.flush()
            return {
                "status": "auto_blocked",
                "evaluated_predictions": len(pairs),
                "metrics": active_metrics,
                "train_metrics": train_metrics,
                "holdout_baseline_metrics": holdout_baseline_metrics,
                "holdout_baseline_signal_quality": holdout_baseline_signal_quality,
                "sample_segments": sample_segments,
                "live_metrics": live_metrics,
                "real_world_metrics": real_world_metrics,
                "readiness": readiness,
                "thresholds": thresholds,
                "reasons": reasons,
            }

        candidate_config = _adjust_weights(active.config or DEFAULT_MODEL_CONFIG, train_pairs)
        candidate_holdout_metrics = _metrics_for_pairs_with_config(
            holdout_pairs,
            candidate_config,
        )
        candidate_signal_quality = _compute_signal_quality_for_pairs(
            holdout_pairs,
            candidate_config,
        )
        real_world_candidate_holdout_metrics = _metrics_for_pairs_with_config(
            real_world_holdout_pairs,
            candidate_config,
        )
        real_world_candidate_signal_quality = _compute_signal_quality_for_pairs(
            real_world_holdout_pairs,
            candidate_config,
        )
        walk_forward_validation = _walk_forward_validation_for_pairs(
            pairs,
            baseline_config=active.config or DEFAULT_MODEL_CONFIG,
            candidate_config=candidate_config,
        )
        walk_forward_allowed, walk_forward_reasons = _candidate_walk_forward_gate(
            walk_forward_validation,
            require_ready=True,
        )
        holdout_allowed, holdout_reasons = _candidate_holdout_gate(
            candidate_holdout_metrics,
            holdout_baseline_metrics,
        )
        signal_quality_allowed, signal_quality_reasons = _candidate_signal_quality_gate(
            candidate_signal_quality,
            holdout_baseline_signal_quality,
        )
        real_world_holdout_allowed, real_world_holdout_reasons = _candidate_real_world_holdout_gate(
            real_world_candidate_holdout_metrics,
            real_world_holdout_baseline_metrics,
        )
        real_world_signal_quality_allowed, real_world_signal_quality_reasons = _candidate_real_world_signal_quality_gate(
            real_world_candidate_signal_quality,
            real_world_holdout_baseline_signal_quality,
        )
        gate_summary = {
            "holdout_passed": holdout_allowed,
            "holdout_reasons": holdout_reasons,
            "signal_quality_passed": signal_quality_allowed,
            "signal_quality_reasons": signal_quality_reasons,
            "real_world_holdout_passed": real_world_holdout_allowed,
            "real_world_holdout_reasons": real_world_holdout_reasons,
            "real_world_signal_quality_passed": real_world_signal_quality_allowed,
            "real_world_signal_quality_reasons": real_world_signal_quality_reasons,
            "walk_forward_passed": walk_forward_allowed,
            "walk_forward_reasons": walk_forward_reasons,
        }
        if not holdout_allowed:
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
                    "train_metrics": train_metrics,
                    "holdout_baseline_metrics": holdout_baseline_metrics,
                    "holdout_baseline_signal_quality": holdout_baseline_signal_quality,
                    "candidate_holdout_metrics": candidate_holdout_metrics,
                    "candidate_signal_quality": candidate_signal_quality,
                    "real_world_holdout_baseline_metrics": real_world_holdout_baseline_metrics,
                    "real_world_holdout_baseline_signal_quality": real_world_holdout_baseline_signal_quality,
                    "real_world_candidate_holdout_metrics": real_world_candidate_holdout_metrics,
                    "real_world_candidate_signal_quality": real_world_candidate_signal_quality,
                    "walk_forward_validation": walk_forward_validation,
                    "sample_segments": sample_segments,
                    "live_metrics": live_metrics,
                    "real_world_metrics": real_world_metrics,
                    "readiness": readiness,
                    "thresholds": thresholds,
                    "reasons": holdout_reasons,
                    **gate_summary,
                },
            ))
            session.flush()
            return {
                "status": "auto_blocked",
                "evaluated_predictions": len(pairs),
                "metrics": active_metrics,
                "train_metrics": train_metrics,
                "holdout_baseline_metrics": holdout_baseline_metrics,
                "holdout_baseline_signal_quality": holdout_baseline_signal_quality,
                "candidate_holdout_metrics": candidate_holdout_metrics,
                "candidate_signal_quality": candidate_signal_quality,
                "real_world_holdout_baseline_metrics": real_world_holdout_baseline_metrics,
                "real_world_holdout_baseline_signal_quality": real_world_holdout_baseline_signal_quality,
                "real_world_candidate_holdout_metrics": real_world_candidate_holdout_metrics,
                "real_world_candidate_signal_quality": real_world_candidate_signal_quality,
                "walk_forward_validation": walk_forward_validation,
                "sample_segments": sample_segments,
                "live_metrics": live_metrics,
                "real_world_metrics": real_world_metrics,
                "readiness": readiness,
                "thresholds": thresholds,
                "reasons": holdout_reasons,
                **gate_summary,
            }
        if not signal_quality_allowed:
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
                    "train_metrics": train_metrics,
                    "holdout_baseline_metrics": holdout_baseline_metrics,
                    "holdout_baseline_signal_quality": holdout_baseline_signal_quality,
                    "candidate_holdout_metrics": candidate_holdout_metrics,
                    "candidate_signal_quality": candidate_signal_quality,
                    "real_world_holdout_baseline_metrics": real_world_holdout_baseline_metrics,
                    "real_world_holdout_baseline_signal_quality": real_world_holdout_baseline_signal_quality,
                    "real_world_candidate_holdout_metrics": real_world_candidate_holdout_metrics,
                    "real_world_candidate_signal_quality": real_world_candidate_signal_quality,
                    "walk_forward_validation": walk_forward_validation,
                    "sample_segments": sample_segments,
                    "live_metrics": live_metrics,
                    "real_world_metrics": real_world_metrics,
                    "readiness": readiness,
                    "thresholds": thresholds,
                    "reasons": signal_quality_reasons,
                    **gate_summary,
                },
            ))
            session.flush()
            return {
                "status": "auto_blocked",
                "evaluated_predictions": len(pairs),
                "metrics": active_metrics,
                "train_metrics": train_metrics,
                "holdout_baseline_metrics": holdout_baseline_metrics,
                "holdout_baseline_signal_quality": holdout_baseline_signal_quality,
                "candidate_holdout_metrics": candidate_holdout_metrics,
                "candidate_signal_quality": candidate_signal_quality,
                "real_world_holdout_baseline_metrics": real_world_holdout_baseline_metrics,
                "real_world_holdout_baseline_signal_quality": real_world_holdout_baseline_signal_quality,
                "real_world_candidate_holdout_metrics": real_world_candidate_holdout_metrics,
                "real_world_candidate_signal_quality": real_world_candidate_signal_quality,
                "walk_forward_validation": walk_forward_validation,
                "sample_segments": sample_segments,
                "live_metrics": live_metrics,
                "real_world_metrics": real_world_metrics,
                "readiness": readiness,
                "thresholds": thresholds,
                "reasons": signal_quality_reasons,
                **gate_summary,
            }
        if not real_world_holdout_allowed:
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
                    "train_metrics": train_metrics,
                    "holdout_baseline_metrics": holdout_baseline_metrics,
                    "holdout_baseline_signal_quality": holdout_baseline_signal_quality,
                    "candidate_holdout_metrics": candidate_holdout_metrics,
                    "candidate_signal_quality": candidate_signal_quality,
                    "real_world_holdout_baseline_metrics": real_world_holdout_baseline_metrics,
                    "real_world_holdout_baseline_signal_quality": real_world_holdout_baseline_signal_quality,
                    "real_world_candidate_holdout_metrics": real_world_candidate_holdout_metrics,
                    "real_world_candidate_signal_quality": real_world_candidate_signal_quality,
                    "walk_forward_validation": walk_forward_validation,
                    "sample_segments": sample_segments,
                    "live_metrics": live_metrics,
                    "real_world_metrics": real_world_metrics,
                    "readiness": readiness,
                    "thresholds": thresholds,
                    "reasons": real_world_holdout_reasons,
                    "reason": "real_world_holdout_gate_failed",
                    **gate_summary,
                },
            ))
            session.flush()
            return {
                "status": "auto_blocked",
                "evaluated_predictions": len(pairs),
                "metrics": active_metrics,
                "train_metrics": train_metrics,
                "holdout_baseline_metrics": holdout_baseline_metrics,
                "holdout_baseline_signal_quality": holdout_baseline_signal_quality,
                "candidate_holdout_metrics": candidate_holdout_metrics,
                "candidate_signal_quality": candidate_signal_quality,
                "real_world_holdout_baseline_metrics": real_world_holdout_baseline_metrics,
                "real_world_holdout_baseline_signal_quality": real_world_holdout_baseline_signal_quality,
                "real_world_candidate_holdout_metrics": real_world_candidate_holdout_metrics,
                "real_world_candidate_signal_quality": real_world_candidate_signal_quality,
                "walk_forward_validation": walk_forward_validation,
                "sample_segments": sample_segments,
                "live_metrics": live_metrics,
                "real_world_metrics": real_world_metrics,
                "readiness": readiness,
                "thresholds": thresholds,
                "reasons": real_world_holdout_reasons,
                "reason": "real_world_holdout_gate_failed",
                **gate_summary,
            }
        if not real_world_signal_quality_allowed:
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
                    "train_metrics": train_metrics,
                    "holdout_baseline_metrics": holdout_baseline_metrics,
                    "holdout_baseline_signal_quality": holdout_baseline_signal_quality,
                    "candidate_holdout_metrics": candidate_holdout_metrics,
                    "candidate_signal_quality": candidate_signal_quality,
                    "real_world_holdout_baseline_metrics": real_world_holdout_baseline_metrics,
                    "real_world_holdout_baseline_signal_quality": real_world_holdout_baseline_signal_quality,
                    "real_world_candidate_holdout_metrics": real_world_candidate_holdout_metrics,
                    "real_world_candidate_signal_quality": real_world_candidate_signal_quality,
                    "walk_forward_validation": walk_forward_validation,
                    "sample_segments": sample_segments,
                    "live_metrics": live_metrics,
                    "real_world_metrics": real_world_metrics,
                    "readiness": readiness,
                    "thresholds": thresholds,
                    "reasons": real_world_signal_quality_reasons,
                    "reason": "real_world_signal_quality_gate_failed",
                    **gate_summary,
                },
            ))
            session.flush()
            return {
                "status": "auto_blocked",
                "evaluated_predictions": len(pairs),
                "metrics": active_metrics,
                "train_metrics": train_metrics,
                "holdout_baseline_metrics": holdout_baseline_metrics,
                "holdout_baseline_signal_quality": holdout_baseline_signal_quality,
                "candidate_holdout_metrics": candidate_holdout_metrics,
                "candidate_signal_quality": candidate_signal_quality,
                "real_world_holdout_baseline_metrics": real_world_holdout_baseline_metrics,
                "real_world_holdout_baseline_signal_quality": real_world_holdout_baseline_signal_quality,
                "real_world_candidate_holdout_metrics": real_world_candidate_holdout_metrics,
                "real_world_candidate_signal_quality": real_world_candidate_signal_quality,
                "walk_forward_validation": walk_forward_validation,
                "sample_segments": sample_segments,
                "live_metrics": live_metrics,
                "real_world_metrics": real_world_metrics,
                "readiness": readiness,
                "thresholds": thresholds,
                "reasons": real_world_signal_quality_reasons,
                "reason": "real_world_signal_quality_gate_failed",
                **gate_summary,
            }
        if not walk_forward_allowed:
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
                    "train_metrics": train_metrics,
                    "holdout_baseline_metrics": holdout_baseline_metrics,
                    "holdout_baseline_signal_quality": holdout_baseline_signal_quality,
                    "candidate_holdout_metrics": candidate_holdout_metrics,
                    "candidate_signal_quality": candidate_signal_quality,
                    "real_world_holdout_baseline_metrics": real_world_holdout_baseline_metrics,
                    "real_world_holdout_baseline_signal_quality": real_world_holdout_baseline_signal_quality,
                    "real_world_candidate_holdout_metrics": real_world_candidate_holdout_metrics,
                    "real_world_candidate_signal_quality": real_world_candidate_signal_quality,
                    "walk_forward_validation": walk_forward_validation,
                    "sample_segments": sample_segments,
                    "live_metrics": live_metrics,
                    "real_world_metrics": real_world_metrics,
                    "readiness": readiness,
                    "thresholds": thresholds,
                    "reasons": walk_forward_reasons,
                    **gate_summary,
                },
            ))
            session.flush()
            return {
                "status": "auto_blocked",
                "evaluated_predictions": len(pairs),
                "metrics": active_metrics,
                "train_metrics": train_metrics,
                "holdout_baseline_metrics": holdout_baseline_metrics,
                "holdout_baseline_signal_quality": holdout_baseline_signal_quality,
                "candidate_holdout_metrics": candidate_holdout_metrics,
                "candidate_signal_quality": candidate_signal_quality,
                "real_world_holdout_baseline_metrics": real_world_holdout_baseline_metrics,
                "real_world_holdout_baseline_signal_quality": real_world_holdout_baseline_signal_quality,
                "real_world_candidate_holdout_metrics": real_world_candidate_holdout_metrics,
                "real_world_candidate_signal_quality": real_world_candidate_signal_quality,
                "walk_forward_validation": walk_forward_validation,
                "sample_segments": sample_segments,
                "live_metrics": live_metrics,
                "real_world_metrics": real_world_metrics,
                "readiness": readiness,
                "thresholds": thresholds,
                "reasons": walk_forward_reasons,
                **gate_summary,
            }

        candidate = (
            session.query(ModelVersionORM)
            .filter(ModelVersionORM.parent_id == active.id, ModelVersionORM.status == "candidate")
            .order_by(ModelVersionORM.id.desc())
            .first()
        )
        if candidate is None:
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
        else:
            candidate.config = candidate_config
            candidate.metrics = active_metrics

        _promote_candidate(
            session,
            active=active,
            candidate=candidate,
            metrics=active_metrics,
            thresholds=thresholds,
            reasons=[],
            source="auto_evolve",
            summary_extra={
                "train_metrics": train_metrics,
                "holdout_baseline_metrics": holdout_baseline_metrics,
                "holdout_baseline_signal_quality": holdout_baseline_signal_quality,
                "candidate_holdout_metrics": candidate_holdout_metrics,
                "candidate_signal_quality": candidate_signal_quality,
                "real_world_holdout_baseline_metrics": real_world_holdout_baseline_metrics,
                "real_world_holdout_baseline_signal_quality": real_world_holdout_baseline_signal_quality,
                "real_world_candidate_holdout_metrics": real_world_candidate_holdout_metrics,
                "real_world_candidate_signal_quality": real_world_candidate_signal_quality,
                "walk_forward_validation": walk_forward_validation,
                "sample_segments": sample_segments,
                "live_metrics": live_metrics,
                "real_world_metrics": real_world_metrics,
                "readiness": readiness,
                **gate_summary,
            },
        )
        session.flush()
        return {
            "status": "auto_promoted",
            "evaluated_predictions": len(pairs),
            "active_model": _model_to_dict(candidate),
            "previous_model": _model_to_dict(active),
            "metrics": active_metrics,
            "train_metrics": train_metrics,
            "holdout_baseline_metrics": holdout_baseline_metrics,
            "holdout_baseline_signal_quality": holdout_baseline_signal_quality,
            "candidate_holdout_metrics": candidate_holdout_metrics,
            "candidate_signal_quality": candidate_signal_quality,
            "real_world_holdout_baseline_metrics": real_world_holdout_baseline_metrics,
            "real_world_holdout_baseline_signal_quality": real_world_holdout_baseline_signal_quality,
            "real_world_candidate_holdout_metrics": real_world_candidate_holdout_metrics,
            "real_world_candidate_signal_quality": real_world_candidate_signal_quality,
            "walk_forward_validation": walk_forward_validation,
            "sample_segments": sample_segments,
            "live_metrics": live_metrics,
            "real_world_metrics": real_world_metrics,
            "readiness": readiness,
            "thresholds": thresholds,
            **gate_summary,
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
    from apps.api.app.core.config import get_evolution_settings

    with _ctx(db) as session:
        model = ensure_active_model(session)
        pairs = _metric_pairs(session, model.id)
        metrics = _compute_metrics_from_pairs(pairs)
        sample_segments = _compute_metrics_by_sample_source(pairs)
        real_world_horizon_health = _real_world_horizon_health(pairs)
        readiness = _auto_evolution_readiness(
            pairs=pairs,
            settings=get_evolution_settings(),
        )
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
            "sample_segments": sample_segments,
            "real_world_horizon_health": real_world_horizon_health,
            "readiness": readiness,
            "counts": {
                "total_predictions": total,
                "pending": pending,
                "due": due,
                "validated": validated,
            },
            "latest_scan_runs": [_scan_run_to_dict(r) for r in latest_runs],
            "latest_evolution_runs": [_evolution_run_to_dict(r) for r in latest_evolution],
        }


def _diagnosis_for_pair(
    session: Session,
    pred: StockPredictionORM,
    outcome: PredictionOutcomeORM,
) -> dict:
    details = outcome.details or {}
    diagnosis = details.get("diagnosis") if isinstance(details, dict) else None
    if isinstance(diagnosis, dict) and diagnosis.get("error_type"):
        return diagnosis
    return _diagnose_prediction_outcome(
        pred,
        outcome,
        config=_prediction_model_config(session, pred),
    )


def _counter_rows(
    counter: Counter,
    *,
    total: int,
    label_resolver=None,
    limit: int = 10,
) -> list[dict]:
    rows = []
    for key, count in counter.most_common(limit):
        rows.append({
            "key": key,
            "label": label_resolver(key) if label_resolver else key,
            "count": int(count),
            "rate": round(count / total, 4) if total else 0.0,
        })
    return rows


def get_diagnostics(
    *,
    limit: int = 100,
    db: Session | None = None,
    model_version_id: int | None = None,
) -> dict:
    """Aggregate recent prediction post-mortems into a learning report."""
    with _ctx(db) as session:
        q = session.query(PredictionOutcomeORM)
        if model_version_id is not None:
            q = q.filter(PredictionOutcomeORM.model_version_id == model_version_id)
        outcomes = (
            q.order_by(PredictionOutcomeORM.validated_at.desc(), PredictionOutcomeORM.id.desc())
            .limit(max(1, min(limit, 1000)))
            .all()
        )

        rows: list[dict] = []
        for outcome in outcomes:
            pred = session.get(StockPredictionORM, outcome.prediction_id)
            if not pred:
                continue
            diagnosis = _diagnosis_for_pair(session, pred, outcome)
            rows.append({
                "prediction": pred,
                "outcome": outcome,
                "diagnosis": diagnosis,
            })

        total = len(rows)
        if not rows:
            return {
                "ready": False,
                "sample_count": 0,
                "generated_at": _now().isoformat(),
                "reason": "no_validated_predictions",
                "error_types": [],
                "verdicts": [],
                "root_causes": [],
                "lessons": [],
                "recommended_actions": [],
                "feature_feedback": {"penalties": [], "rewards": []},
                "high_confidence_misses": [],
                "worst_predictions": [],
            }

        error_counter: Counter = Counter()
        verdict_counter: Counter = Counter()
        cause_counter: Counter = Counter()
        lesson_counter: Counter = Counter()
        action_counter: Counter = Counter()
        penalty_counter: Counter = Counter()
        reward_counter: Counter = Counter()
        return_by_error: dict[str, list[float]] = {}
        prob_by_error: dict[str, list[float]] = {}

        high_confidence_misses: list[dict] = []
        worst_predictions: list[dict] = []
        for row in rows:
            pred = row["prediction"]
            outcome = row["outcome"]
            diagnosis = row["diagnosis"]
            error_type = str(diagnosis.get("error_type") or "unknown")
            verdict = str(diagnosis.get("verdict") or "unknown")
            error_counter[error_type] += 1
            verdict_counter[verdict] += 1
            return_by_error.setdefault(error_type, []).append(_f(outcome.close_return_pct))
            prob_by_error.setdefault(error_type, []).append(_f(pred.probability))

            for cause in diagnosis.get("root_causes") or []:
                factor = str(cause.get("factor") or "unknown")
                cause_counter[factor] += 1
            for lesson in diagnosis.get("lessons") or []:
                lesson_counter[str(lesson)] += 1
            for action in diagnosis.get("recommended_adjustments") or []:
                key = str(action.get("action") or action.get("message") or "unknown")
                action_counter[key] += 1

            feedback = diagnosis.get("model_feedback") or {}
            for penalty in feedback.get("feature_penalties") or []:
                key = str(penalty.get("key") or "unknown")
                penalty_counter[(key, str(penalty.get("label") or FEATURE_LABELS.get(key, key)))] += 1
            for reward in feedback.get("feature_rewards") or []:
                key = str(reward.get("key") or "unknown")
                reward_counter[(key, str(reward.get("label") or FEATURE_LABELS.get(key, key)))] += 1

            item = {
                "id": pred.id,
                "symbol": pred.symbol,
                "name": pred.name,
                "horizon_days": pred.horizon_days,
                "probability_pct": round(_f(pred.probability) * 100, 1),
                "expected_return_pct": round(_f(pred.expected_return_pct), 4),
                "close_return_pct": round(_f(outcome.close_return_pct), 4),
                "max_return_pct": round(_f(outcome.max_return_pct), 4),
                "max_drawdown_pct": round(_f(outcome.max_drawdown_pct), 4),
                "error_type": error_type,
                "error_type_label": diagnosis.get("error_type_label") or ERROR_TYPE_LABELS.get(error_type, error_type),
                "verdict": verdict,
                "verdict_label": diagnosis.get("verdict_label") or VERDICT_LABELS.get(verdict, verdict),
                "primary_cause": (diagnosis.get("root_causes") or [{}])[0].get("message"),
                "validated_at": outcome.validated_at.isoformat() if outcome.validated_at else None,
            }
            if _f(pred.probability) >= 0.65 and not bool(outcome.success):
                high_confidence_misses.append(item)
            worst_predictions.append(item)

        error_rows = []
        for error_type, count in error_counter.most_common():
            returns = return_by_error.get(error_type) or [0.0]
            probs = prob_by_error.get(error_type) or [0.0]
            error_rows.append({
                "key": error_type,
                "label": ERROR_TYPE_LABELS.get(error_type, error_type),
                "count": int(count),
                "rate": round(count / total, 4),
                "avg_return_pct": round(mean(returns), 4),
                "avg_probability_pct": round(mean(probs) * 100.0, 2),
            })

        def _feature_feedback_rows(counter: Counter) -> list[dict]:
            rows_out = []
            for (key, label), count in counter.most_common(10):
                rows_out.append({
                    "key": key,
                    "label": label,
                    "count": int(count),
                    "rate": round(count / total, 4),
                })
            return rows_out

        recommended_actions = []
        for key, count in action_counter.most_common(8):
            recommended_actions.append({
                "action": key,
                "count": int(count),
                "rate": round(count / total, 4),
            })

        high_confidence_misses.sort(key=lambda item: (item["probability_pct"], -item["close_return_pct"]), reverse=True)
        worst_predictions.sort(key=lambda item: item["close_return_pct"])
        return {
            "ready": True,
            "sample_count": total,
            "generated_at": _now().isoformat(),
            "error_types": error_rows,
            "verdicts": _counter_rows(
                verdict_counter,
                total=total,
                label_resolver=lambda key: VERDICT_LABELS.get(key, key),
            ),
            "root_causes": _counter_rows(cause_counter, total=total, limit=12),
            "lessons": [
                {"message": lesson, "count": int(count), "rate": round(count / total, 4)}
                for lesson, count in lesson_counter.most_common(8)
            ],
            "recommended_actions": recommended_actions,
            "feature_feedback": {
                "penalties": _feature_feedback_rows(penalty_counter),
                "rewards": _feature_feedback_rows(reward_counter),
            },
            "high_confidence_misses": high_confidence_misses[:10],
            "worst_predictions": worst_predictions[:10],
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
    if successes and failures:
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

    penalty_counts: Counter = Counter()
    reward_counts: Counter = Counter()
    horizon_feedback: dict[str, list[float]] = {}
    for pred, out in pairs:
        diagnosis = ((out.details or {}).get("diagnosis") or {}) if isinstance(out.details, dict) else {}
        feedback = diagnosis.get("model_feedback") or {}
        for penalty in feedback.get("feature_penalties") or []:
            key = str(penalty.get("key") or "")
            if key in weights:
                penalty_counts[key] += 1
        for reward in feedback.get("feature_rewards") or []:
            key = str(reward.get("key") or "")
            if key in weights:
                reward_counts[key] += 1
        delta = _f(feedback.get("horizon_bias_delta"))
        if delta:
            horizon_feedback.setdefault(str(pred.horizon_days), []).append(delta)

    pair_count = max(len(pairs), 1)
    for key, count in penalty_counts.items():
        impact = _clamp(count / pair_count * 0.18, 0.0, 0.10)
        old_weight = _f(weights[key])
        if old_weight < 0:
            weights[key] = -abs(old_weight) * (1.0 + impact)
        else:
            weights[key] = max(0.02, old_weight * (1.0 - impact))
    for key, count in reward_counts.items():
        impact = _clamp(count / pair_count * 0.12, 0.0, 0.08)
        old_weight = _f(weights[key])
        if old_weight < 0:
            weights[key] = -max(0.02, abs(old_weight) * (1.0 - impact))
        else:
            weights[key] = max(0.02, old_weight * (1.0 + impact))

    total = sum(abs(v) for v in weights.values()) or 1.0
    cfg["weights"] = {k: round(v / total, 4) for k, v in weights.items()}

    metrics = _compute_metrics_from_pairs(pairs)
    overall = _f(metrics.get("success_rate"))
    bias = copy.deepcopy(cfg.get("horizon_bias") or {})
    for row in metrics.get("by_horizon") or []:
        key = str(row["horizon_days"])
        prev = _f(bias.get(key))
        bias[key] = round(_clamp(prev + (_f(row["success_rate"]) - overall) * 0.08, -0.12, 0.12), 4)
    for key, deltas in horizon_feedback.items():
        prev = _f(bias.get(key))
        bias[key] = round(_clamp(prev + mean(deltas), -0.12, 0.12), 4)
    cfg["horizon_bias"] = bias
    if penalty_counts or reward_counts or horizon_feedback:
        cfg["last_diagnostic_feedback"] = {
            "feature_penalties": dict(penalty_counts),
            "feature_rewards": dict(reward_counts),
            "horizon_bias_feedback": {key: round(mean(values), 4) for key, values in horizon_feedback.items()},
        }
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
        train_pairs, holdout_pairs = _split_train_holdout_pairs(pairs)
        train_metrics = _compute_metrics_from_pairs(train_pairs)
        holdout_baseline_metrics = _metrics_for_pairs_with_config(
            holdout_pairs,
            active.config or DEFAULT_MODEL_CONFIG,
        )
        holdout_baseline_signal_quality = _compute_signal_quality_for_pairs(
            holdout_pairs,
            active.config or DEFAULT_MODEL_CONFIG,
        )
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
                summary={
                    "reason": f"validated samples {len(pairs)} < min_samples {threshold}",
                    "metrics": metrics,
                    "train_metrics": train_metrics,
                    "holdout_baseline_metrics": holdout_baseline_metrics,
                    "holdout_baseline_signal_quality": holdout_baseline_signal_quality,
                },
            )
            session.add(run)
            session.flush()
            return {
                "status": "insufficient_data",
                "min_samples": threshold,
                "evaluated_predictions": len(pairs),
                "metrics": metrics,
                "train_metrics": train_metrics,
                "holdout_baseline_metrics": holdout_baseline_metrics,
                "holdout_baseline_signal_quality": holdout_baseline_signal_quality,
                "evolution_run_id": run.id,
            }
        if not train_pairs or not holdout_pairs:
            run = EvolutionRunORM(
                model_version_id=active.id,
                status="insufficient_data",
                evaluated_predictions=len(pairs),
                success_rate=metrics["success_rate"],
                avg_return_pct=metrics["avg_return_pct"],
                brier_score=metrics["brier_score"],
                calibration_error=metrics["calibration_error"],
                promoted=False,
                summary={
                    "reason": "need_train_and_holdout_samples",
                    "metrics": metrics,
                    "train_metrics": train_metrics,
                    "holdout_baseline_metrics": holdout_baseline_metrics,
                    "holdout_baseline_signal_quality": holdout_baseline_signal_quality,
                },
            )
            session.add(run)
            session.flush()
            return {
                "status": "insufficient_data",
                "min_samples": threshold,
                "evaluated_predictions": len(pairs),
                "metrics": metrics,
                "train_metrics": train_metrics,
                "holdout_baseline_metrics": holdout_baseline_metrics,
                "holdout_baseline_signal_quality": holdout_baseline_signal_quality,
                "evolution_run_id": run.id,
                "reason": "need_train_and_holdout_samples",
            }

        candidate_config = _adjust_weights(active.config or DEFAULT_MODEL_CONFIG, train_pairs)
        candidate_holdout_metrics = _metrics_for_pairs_with_config(
            holdout_pairs,
            candidate_config,
        )
        candidate_signal_quality = _compute_signal_quality_for_pairs(
            holdout_pairs,
            candidate_config,
        )
        holdout_allowed, holdout_reasons = _candidate_holdout_gate(
            candidate_holdout_metrics,
            holdout_baseline_metrics,
        )
        signal_quality_allowed, signal_quality_reasons = _candidate_signal_quality_gate(
            candidate_signal_quality,
            holdout_baseline_signal_quality,
        )
        walk_forward_validation = _walk_forward_validation_for_pairs(
            pairs,
            baseline_config=active.config or DEFAULT_MODEL_CONFIG,
            candidate_config=candidate_config,
        )
        walk_forward_allowed, walk_forward_reasons = _candidate_walk_forward_gate(walk_forward_validation)
        promote_allowed = promote and holdout_allowed and signal_quality_allowed and walk_forward_allowed
        version = _next_version(active.version)
        candidate = ModelVersionORM(
            name=active.name,
            version=version,
            status="active" if promote_allowed else "candidate",
            parent_id=active.id,
            config=candidate_config,
            metrics=metrics,
            note="由历史预测验证结果自动校准生成",
            activated_at=_now() if promote_allowed else None,
        )
        if promote_allowed:
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
            promoted=promote_allowed,
            summary={
                "metrics": metrics,
                "train_metrics": train_metrics,
                "holdout_baseline_metrics": holdout_baseline_metrics,
                "holdout_baseline_signal_quality": holdout_baseline_signal_quality,
                "candidate_holdout_metrics": candidate_holdout_metrics,
                "candidate_signal_quality": candidate_signal_quality,
                "holdout_passed": holdout_allowed,
                "holdout_reasons": holdout_reasons,
                "signal_quality_passed": signal_quality_allowed,
                "signal_quality_reasons": signal_quality_reasons,
                "walk_forward_validation": walk_forward_validation,
                "walk_forward_passed": walk_forward_allowed,
                "walk_forward_reasons": walk_forward_reasons,
                "old_weights": (active.config or {}).get("weights", {}),
                "new_weights": candidate_config.get("weights", {}),
                "horizon_bias": candidate_config.get("horizon_bias", {}),
            },
        )
        session.add(run)
        session.flush()

        return {
            "status": "completed",
            "promoted": promote_allowed,
            "evolution_run_id": run.id,
            "active_model": _model_to_dict(candidate if promote_allowed else active),
            "candidate_model": _model_to_dict(candidate),
            "metrics": metrics,
            "train_metrics": train_metrics,
            "holdout_baseline_metrics": holdout_baseline_metrics,
            "holdout_baseline_signal_quality": holdout_baseline_signal_quality,
            "candidate_holdout_metrics": candidate_holdout_metrics,
            "candidate_signal_quality": candidate_signal_quality,
            "holdout_passed": holdout_allowed,
            "holdout_reasons": holdout_reasons,
            "signal_quality_passed": signal_quality_allowed,
            "signal_quality_reasons": signal_quality_reasons,
            "walk_forward_validation": walk_forward_validation,
            "walk_forward_passed": walk_forward_allowed,
            "walk_forward_reasons": walk_forward_reasons,
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
