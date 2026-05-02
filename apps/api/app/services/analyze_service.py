"""Analysis service: wires LLM orchestrator with market data and repositories."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from apps.api.app.core.config import get_settings
from apps.api.app.db.repositories import NewsRepository, RiskEventRepository
from apps.api.app.services.market_service import MarketService

from libs.features.technical import TechnicalFeatures, build_technical_features
from libs.llm_analyst.decision import AnalysisReport
from libs.llm_analyst.llm_client import LLMConfig
from libs.llm_analyst.orchestrator import AnalysisOrchestrator
from libs.recommendations.signal_engine import SignalEngine


_KNOWN_SYMBOLS: set[str] = {
    "600519.SH", "000001.SZ", "300750.SZ", "000858.SZ",
    "601318.SH", "600036.SH", "601166.SH", "000333.SZ",
}


def _build_llm_config() -> LLMConfig:
    cfg = LLMConfig()
    s = get_settings()
    cfg.provider = cfg.provider  # already resolved from env; settings mirror env vars
    return cfg


class AnalyzeService:
    """
    High-level service for the `/recommendations/analyze/{symbol}` endpoint.

    It:
    1. Fetches the latest market bars via MarketService
    2. Computes TechnicalFeatures and a SignalScore
    3. Queries recent news events from the DB
    4. Queries active risk events / flags from the DB
    5. Looks up instrument metadata
    6. Calls AnalysisOrchestrator to produce the multi-agent AnalysisReport
    """

    def __init__(self, db: Session) -> None:
        self._db = db
        self._market = MarketService()
        self._signal_engine = SignalEngine()
        self._orchestrator = AnalysisOrchestrator()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def analyze(self, symbol: str, portfolio_context: Optional[str] = None) -> AnalysisReport:
        if symbol not in _KNOWN_SYMBOLS:
            raise ValueError(f"Unknown symbol: {symbol}")

        features = self._compute_features(symbol)
        signal = self._signal_engine.generate_signal(features)

        instrument = self._get_instrument(symbol)
        news_items = self._get_news(symbol)
        risk_flags = self._get_risk_flags(symbol)

        ctx = portfolio_context or "无特殊持仓约束"

        return self._orchestrator.analyze(
            symbol=symbol,
            features=asdict(features),
            signal_score=signal.raw_score,
            signal_conf=signal.confidence,
            instrument=instrument,
            news_items=news_items,
            risk_flags=risk_flags,
            portfolio_context=ctx,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_features(self, symbol: str) -> TechnicalFeatures:
        _ZERO = TechnicalFeatures(
            symbol=symbol,
            as_of_date=date.today(),
            close=0.0,
            returns_1d=0.0,
            returns_5d=0.0,
            returns_20d=0.0,
            volatility_20d=0.0,
            volume=0,
            volume_ratio_5d=1.0,
            turnover_rate=0.0,
        )
        try:
            bars = self._market.get_bars(symbol=symbol, freq="1d")
        except Exception:
            return _ZERO

        if len(bars) < 5:
            return _ZERO

        bar_tuples = [(b.trade_date, b.close, b.volume, b.turnover_rate) for b in bars]
        result = build_technical_features(symbol, bar_tuples)
        return result if result is not None else _ZERO

    def _get_instrument(self, symbol: str) -> dict:
        try:
            instruments = self._market.list_instruments()
            for inst in instruments:
                if inst.symbol == symbol:
                    return asdict(inst)
        except Exception:
            pass
        return {"symbol": symbol, "industry": "未知", "status": "listed", "is_st": False}

    def _get_news(self, symbol: str) -> list[dict]:
        try:
            news_repo = NewsRepository(self._db)
            articles = news_repo.list_articles(symbol=symbol, limit=10)
            result = []
            for art in articles:
                events = news_repo.list_events_for_symbol(symbol, limit=5)
                for ev in events:
                    result.append({
                        "title": art.title,
                        "event_type": ev.event_type,
                        "summary": ev.summary,
                        "sentiment_score": ev.sentiment_score,
                        "urgency_score": ev.urgency_score,
                    })
            return result[:10]
        except Exception:
            return []

    def _get_risk_flags(self, symbol: str) -> list[str]:
        try:
            repo = RiskEventRepository(self._db)
            events = repo.list_recent(limit=20)
            return list({e.decision for e in events if e.symbol == symbol and e.decision == "BLOCK"})
        except Exception:
            return []
