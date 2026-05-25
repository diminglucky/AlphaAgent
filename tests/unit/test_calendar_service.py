from datetime import datetime

from apps.api.app.services import market_service


def test_trading_time_weekend_false(monkeypatch) -> None:
    class FakeDatetime(datetime):
        @classmethod
        def now(cls):
            return cls(2026, 5, 23, 10, 0)  # Saturday

    monkeypatch.setattr(market_service, "datetime", FakeDatetime)
    assert market_service._is_trading_time() is False


def test_trading_time_weekday_session_true(monkeypatch) -> None:
    class FakeDatetime(datetime):
        @classmethod
        def now(cls):
            return cls(2026, 5, 25, 10, 0)  # Monday

    monkeypatch.setattr(market_service, "datetime", FakeDatetime)
    assert market_service._is_trading_time() is True


def test_trading_time_lunch_break_false(monkeypatch) -> None:
    class FakeDatetime(datetime):
        @classmethod
        def now(cls):
            return cls(2026, 5, 25, 12, 0)

    monkeypatch.setattr(market_service, "datetime", FakeDatetime)
    assert market_service._is_trading_time() is False
