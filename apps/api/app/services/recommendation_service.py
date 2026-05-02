from __future__ import annotations

from collections.abc import Mapping
from typing import Optional

from apps.api.app.db.bootstrap import ensure_database_initialized
from apps.api.app.db.repositories import RecommendationRepository
from apps.api.app.db.session import session_scope
from apps.api.app.services.sample_data import EXPLANATIONS, NOW, RECOMMENDATIONS
from libs.quant_core.models import Recommendation


class RecommendationService:
    def get_latest_recommendations(self) -> dict[str, object]:
        ensure_database_initialized()
        with session_scope() as session:
            as_of, items = RecommendationRepository(session).list_latest()

        return {
            "as_of": as_of or NOW,
            "items": items or RECOMMENDATIONS,
        }

    def explain_recommendation(self, symbol: str) -> Mapping[str, object]:
        ensure_database_initialized()
        with session_scope() as session:
            explanation = RecommendationRepository(session).get_explanation(symbol)
        explanation = explanation or EXPLANATIONS.get(symbol)
        if explanation is None:
            return {
                "symbol": symbol,
                "summary": "当前没有单独解释，说明该标的未进入重点候选池。",
                "drivers": [],
                "risk_notes": ["缺少足够上下文，不建议直接执行。"],
                "sources": [],
            }
        return explanation

    def get_symbol_recommendation(self, symbol: str) -> Optional[Recommendation]:
        ensure_database_initialized()
        with session_scope() as session:
            item = RecommendationRepository(session).get_by_symbol(symbol)
        if item is not None:
            return item
        for item in RECOMMENDATIONS:
            if item.symbol == symbol:
                return item
        return None
