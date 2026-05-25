"""Replay-style deterministic checks for current AlphaAgent components."""

from __future__ import annotations

import pytest

from apps.api.app.db.models import PositionORM, WatchlistORM
from apps.api.app.services import alert_service, llm_service


@pytest.mark.replay
def test_replay_watchlist_and_positions_seed(seeded_session) -> None:
    watchlist = seeded_session.query(WatchlistORM).all()
    positions = seeded_session.query(PositionORM).all()

    assert {item.symbol for item in watchlist} == {"600519.SH", "000001.SZ"}
    assert {item.symbol for item in positions} == {"600519.SH"}


@pytest.mark.replay
def test_replay_position_stop_loss_is_deterministic(seeded_session, monkeypatch) -> None:
    alert_service.reset_position_alert_state()
    monkeypatch.setattr(alert_service.feishu_service, "send_sell_alert", lambda **kwargs: True)

    triggered = alert_service.check_position_alerts(
        seeded_session,
        [{"symbol": "600519.SH", "name": "贵州茅台", "price": 90.0}],
    )

    assert len(triggered) == 1
    assert triggered[0]["kind"] == "stop_loss"


@pytest.mark.replay
def test_replay_indicator_contract_stable() -> None:
    bars = [
        {"close": float(10 + i), "high": float(11 + i), "low": float(9 + i), "amount": 1000 + i}
        for i in range(60)
    ]

    indicators = llm_service._calc_indicators(bars)

    assert indicators["ma5"] > indicators["ma20"]
    assert indicators["rsi14"] == 100.0
    assert indicators["macd_dif"] is not None
