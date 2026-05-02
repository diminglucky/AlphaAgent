"""Tests for trading calendar service (§5.3.2)."""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from apps.api.app.services.calendar_service import CalendarService


def test_weekend_is_not_trading_day(db_session: Session) -> None:
    svc = CalendarService(db_session)
    # 2026-04-25 is Saturday
    assert svc.is_trading_day("2026-04-25") is False
    # 2026-04-26 is Sunday
    assert svc.is_trading_day(date(2026, 4, 26)) is False


def test_weekday_is_trading_day(db_session: Session) -> None:
    svc = CalendarService(db_session)
    # 2026-04-23 is Thursday — should be open
    assert svc.is_trading_day(date(2026, 4, 23)) is True


def test_holiday_is_not_trading_day(db_session: Session) -> None:
    svc = CalendarService(db_session)
    # 2026-05-01 is Labor Day
    assert svc.is_trading_day(date(2026, 5, 1)) is False


def test_next_trading_day_skips_weekend(db_session: Session) -> None:
    svc = CalendarService(db_session)
    # Friday 2026-04-24 → Monday 2026-04-27
    nxt = svc.next_trading_day(date(2026, 4, 24))
    assert nxt == date(2026, 4, 27)


def test_seed_year_idempotent(db_session: Session) -> None:
    svc = CalendarService(db_session)
    added1 = svc.seed_year(2026)
    added2 = svc.seed_year(2026)
    assert added1 == 365  # 2026 is non-leap
    assert added2 == 0    # already seeded


def test_list_range_only_open(db_session: Session) -> None:
    svc = CalendarService(db_session)
    entries = svc.list_range("2026-04-23", "2026-04-30", only_open=True)
    # Apr 23 (Thu), 24 (Fri), 27 (Mon), 28 (Tue), 29 (Wed), 30 (Thu) = 6 trading days
    assert len(entries) == 6
    for e in entries:
        assert e.is_open is True
