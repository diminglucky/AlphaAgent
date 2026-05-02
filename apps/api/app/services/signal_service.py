"""Signal snapshot service: store and query signal snapshots."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from apps.api.app.core.config import get_settings
from apps.api.app.db.repositories import SignalRepository
from libs.quant_core.models import SignalSnapshot


def _now() -> datetime:
    return datetime.now(tz=timezone.utc).replace(tzinfo=None)


class SignalService:
    def __init__(self, session: Session) -> None:
        self._repo = SignalRepository(session)
        self._settings = get_settings()

    def save_snapshot(
        self,
        symbol: str,
        signal_type: str,
        raw_score: float,
        confidence: float,
        components: dict,
        expected_horizon: str,
    ) -> SignalSnapshot:
        snap = SignalSnapshot(
            signal_id=str(uuid.uuid4()),
            symbol=symbol,
            as_of_time=_now(),
            signal_type=signal_type,
            raw_score=raw_score,
            confidence=confidence,
            components=components,
            expected_horizon=expected_horizon,
            model_version=self._settings.signal_model_version,
        )
        self._repo.save(snap)
        return snap

    def list_latest(self) -> list[SignalSnapshot]:
        return self._repo.list_latest_per_symbol()
