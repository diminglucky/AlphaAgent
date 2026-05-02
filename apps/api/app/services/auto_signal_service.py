"""
Background scanner that converts market data into signals AND recommendations.

For each watched symbol every refresh cycle:
 1. Fetch historical bars
 2. Compute TechnicalFeatures
 3. Run SignalEngine → SignalScore
 4. Persist a SignalSnapshot row
 5. Convert score → RecommendationAction (BUY / HOLD / SELL)
 6. Persist Recommendation row
 7. Audit-log SIGNAL_GENERATED + RECOMMENDATION_GENERATED

This is what makes the platform actually populate signals/recommendations
tables, instead of relying on seeded sample data.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from apps.api.app.core.config import get_settings
from apps.api.app.db.repositories import (
    AuditLogRepository,
    FactorSnapshotRepository,
    RecommendationRepository,
    SignalRepository,
)
from apps.api.app.services.market_service import MarketService
from apps.api.app.services.watchlist_service import WatchlistService
from libs.features.technical import build_technical_features
from libs.quant_core.enums import (
    AuditAction,
    RecommendationAction,
    RecommendationStatus,
    RiskFlag,
    SignalType,
)
from libs.quant_core.models import AuditLog, Recommendation, SignalSnapshot
from libs.recommendations.signal_engine import SignalEngine

log = logging.getLogger("quant.auto_signal")


@dataclass
class GenerationResult:
    symbols_scanned: int
    signals_saved: int
    recommendations_saved: int
    errors: list[str]


class AutoSignalService:
    """
    Refresh signals + recommendations for every watched symbol.

    Call `run_once()` periodically (e.g. every 5 minutes) — typically from
    a background task in `ws.py`.
    """

    def __init__(self, db: Session) -> None:
        self._db = db
        self._market = MarketService()
        self._engine = SignalEngine()
        self._signals = SignalRepository(db)
        self._recs = RecommendationRepository(db)
        self._audit = AuditLogRepository(db)
        self._factors = FactorSnapshotRepository(db)
        self._settings = get_settings()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def run_once(self) -> GenerationResult:
        account_id = self._settings.default_account_id
        symbols = WatchlistService(self._db).list_symbols(account_id)
        # Always include held positions so we keep signals fresh for them
        from apps.api.app.db.repositories import PortfolioRepository
        held = {p.symbol for p in PortfolioRepository(self._db).list_positions()}
        symbols = list(set(symbols) | held)

        result = GenerationResult(0, 0, 0, [])
        for symbol in symbols:
            result.symbols_scanned += 1
            try:
                self._scan_symbol(symbol, result)
            except Exception as exc:  # noqa: BLE001
                log.warning("auto_signal[%s] failed: %s", symbol, exc)
                result.errors.append(f"{symbol}: {exc}")
        return result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _scan_symbol(self, symbol: str, result: GenerationResult) -> None:
        try:
            bars = self._market.get_bars(symbol=symbol, freq="1d")
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"{symbol}: bars unavailable ({exc})")
            return
        if len(bars) < 2:
            return

        bar_tuples = [(b.trade_date, b.close, b.volume, b.turnover_rate) for b in bars]
        features = build_technical_features(symbol, bar_tuples)
        if features is None:
            return

        signal = self._engine.generate_signal(features)
        now = datetime.now()

        # Persist feature values (Design Doc §5.3.8 traceability)
        try:
            self._factors.save_batch(
                symbol=symbol,
                as_of_time=now,
                factors={
                    "returns_1d": features.returns_1d,
                    "returns_5d": features.returns_5d,
                    "returns_20d": features.returns_20d,
                    "ma_5d": features.ma_5d,
                    "ma_20d": features.ma_20d,
                    "ma_60d": features.ma_60d,
                    "rsi_14d": features.rsi_14d,
                    "volatility_20d": features.volatility_20d,
                    "volume_ratio_5d": features.volume_ratio_5d,
                    "macd_hist": features.macd_hist,
                },
                feature_set_version=self._settings.signal_model_version,
                data_source=self._market.provider.provider_name,
            )
        except Exception:  # noqa: BLE001 — non-blocking
            pass

        # 1) Persist signal snapshot
        snap = SignalSnapshot(
            signal_id=str(uuid.uuid4()),
            symbol=symbol,
            as_of_time=now,
            signal_type=SignalType.COMBINED.value,
            raw_score=signal.raw_score,
            confidence=signal.confidence,
            components=dict(signal.components),
            expected_horizon="1d",
            model_version=self._settings.signal_model_version,
        )
        self._signals.save(snap)
        result.signals_saved += 1
        self._audit.save(AuditLog(
            log_id=str(uuid.uuid4()),
            action=AuditAction.SIGNAL_GENERATED.value,
            actor="auto_scanner",
            resource_type="signal",
            resource_id=snap.signal_id,
            details={
                "symbol": symbol,
                "raw_score": round(signal.raw_score, 4),
                "confidence": round(signal.confidence, 4),
                "components": {k: round(v, 4) for k, v in signal.components.items()},
            },
            created_at=now,
        ))

        # 2) Derive Recommendation from signal score
        action = self._engine.signal_to_action(signal, threshold=0.20)
        risk_flags: list[str] = []
        if features.volatility_20d > 0.03:
            risk_flags.append(RiskFlag.HIGH_VOLATILITY.value)
        if features.rsi_14d is not None and features.rsi_14d > 75:
            risk_flags.append("OVERBOUGHT")
        elif features.rsi_14d is not None and features.rsi_14d < 25:
            risk_flags.append("OVERSOLD")

        rec = Recommendation(
            recommendation_id=f"rec-auto-{symbol}-{int(now.timestamp())}",
            symbol=symbol,
            action=action.value,
            target_weight=self._target_weight(action, signal.confidence),
            confidence=round(signal.confidence, 3),
            time_horizon="day_trade",
            reason_summary=self._build_reason(signal, features, action),
            risk_flags=risk_flags,
            status=RecommendationStatus.READY.value,
            created_at=now,
        )
        self._recs.save(rec)
        result.recommendations_saved += 1
        self._audit.save(AuditLog(
            log_id=str(uuid.uuid4()),
            action=AuditAction.RECOMMENDATION_GENERATED.value,
            actor="auto_scanner",
            resource_type="recommendation",
            resource_id=rec.recommendation_id,
            details={
                "symbol": symbol,
                "action": action.value,
                "confidence": rec.confidence,
                "raw_score": round(signal.raw_score, 4),
            },
            created_at=now,
        ))

    def _target_weight(self, action: RecommendationAction, confidence: float) -> float:
        """Convert action + confidence into a position weight ∈ [0, 0.3]."""
        if action == RecommendationAction.BUY:
            return round(min(0.3, max(0.05, confidence * 0.3)), 3)
        if action == RecommendationAction.SELL:
            return 0.0
        return round(0.1 * confidence, 3)

    def _build_reason(self, signal, features, action) -> str:
        parts = [
            f"综合信号 {signal.raw_score:+.2f}（置信度 {signal.confidence:.0%}）",
            f"动量 {signal.components.get('momentum', 0):+.2f}",
            f"趋势 {signal.components.get('trend', 0):+.2f}",
            f"成交量 {signal.components.get('volume', 0):+.2f}",
        ]
        if features.rsi_14d is not None:
            parts.append(f"RSI {features.rsi_14d:.1f}")
        if action == RecommendationAction.BUY:
            parts.insert(0, "📈 看多机会")
        elif action == RecommendationAction.SELL:
            parts.insert(0, "📉 看空风险")
        else:
            parts.insert(0, "⏸ 观望")
        return " | ".join(parts)
