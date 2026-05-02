"""Trading-calendar service per §5.3.2 of the design doc.

Provides:
- is_trading_day(d) — checks DB calendar; falls back to weekday rule
- next_trading_day / previous_trading_day
- list(start, end) — full calendar
- bulk_seed — populates a year of A-share calendar
- ensure_seeded — auto-seeds current/next year on first use

A-share market is closed on weekends and statutory holidays. We seed a
basic Mon-Fri calendar plus the standard 2025-2026 holiday set; this is
enough for backtests, replay tests and "is today open?" checks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db.models import TradingCalendarORM


# Statutory holidays (incomplete but realistic for tests / replay)
A_SHARE_HOLIDAYS: set[str] = {
    # 2025
    "2025-01-01",  # 元旦
    "2025-01-28", "2025-01-29", "2025-01-30", "2025-01-31",
    "2025-02-03", "2025-02-04",  # 春节
    "2025-04-04", "2025-04-07",  # 清明
    "2025-05-01", "2025-05-02", "2025-05-05",  # 劳动节
    "2025-06-02",  # 端午
    "2025-10-01", "2025-10-02", "2025-10-03", "2025-10-06", "2025-10-07", "2025-10-08",  # 国庆 + 中秋
    # 2026
    "2026-01-01", "2026-01-02",
    "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19", "2026-02-20", "2026-02-23", "2026-02-24",
    "2026-04-06",
    "2026-05-01", "2026-05-04", "2026-05-05",
    "2026-06-19",
    "2026-09-25",
    "2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08",
}


@dataclass(frozen=True)
class CalendarEntry:
    trade_date: date
    market: str
    is_open: bool
    session_type: str


def _to_date(d) -> date:
    if isinstance(d, str):
        return datetime.strptime(d, "%Y-%m-%d").date()
    if isinstance(d, datetime):
        return d.date()
    return d


def _is_weekend(d: date) -> bool:
    return d.weekday() >= 5


def _is_holiday(d: date) -> bool:
    return d.isoformat() in A_SHARE_HOLIDAYS


class CalendarService:
    def __init__(self, session: Session) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def is_trading_day(self, d, market: str = "A") -> bool:
        d = _to_date(d)
        # First check DB if seeded
        row = self._session.execute(
            select(TradingCalendarORM).where(
                TradingCalendarORM.trade_date == d.isoformat(),
                TradingCalendarORM.market == market,
            )
        ).scalar_one_or_none()
        if row is not None:
            return row.is_open
        # Fallback to rule-based
        return not _is_weekend(d) and not _is_holiday(d)

    def next_trading_day(self, d, market: str = "A") -> date:
        d = _to_date(d) + timedelta(days=1)
        for _ in range(15):  # at most a 2-week holiday
            if self.is_trading_day(d, market):
                return d
            d += timedelta(days=1)
        return d

    def previous_trading_day(self, d, market: str = "A") -> date:
        d = _to_date(d) - timedelta(days=1)
        for _ in range(15):
            if self.is_trading_day(d, market):
                return d
            d -= timedelta(days=1)
        return d

    def list_range(self, start, end, market: str = "A", only_open: bool = True) -> list[CalendarEntry]:
        start = _to_date(start)
        end = _to_date(end)
        out: list[CalendarEntry] = []
        d = start
        while d <= end:
            is_open = self.is_trading_day(d, market)
            if not only_open or is_open:
                out.append(CalendarEntry(
                    trade_date=d, market=market, is_open=is_open, session_type="regular",
                ))
            d += timedelta(days=1)
        return out

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def seed_year(self, year: int, market: str = "A") -> int:
        """Idempotently seed all calendar rows for `year`."""
        from datetime import date as _date
        d = _date(year, 1, 1)
        end = _date(year, 12, 31)
        added = 0
        while d <= end:
            existing = self._session.execute(
                select(TradingCalendarORM).where(
                    TradingCalendarORM.trade_date == d.isoformat(),
                    TradingCalendarORM.market == market,
                )
            ).scalar_one_or_none()
            if existing is None:
                self._session.add(TradingCalendarORM(
                    trade_date=d.isoformat(),
                    market=market,
                    is_open=not _is_weekend(d) and not _is_holiday(d),
                    session_type="regular",
                ))
                added += 1
            d += timedelta(days=1)
        self._session.flush()
        return added

    def ensure_seeded(self, market: str = "A") -> None:
        """Seed current + next year if not yet present."""
        today = date.today()
        for y in (today.year, today.year + 1):
            if not self._session.execute(
                select(TradingCalendarORM)
                .where(
                    TradingCalendarORM.trade_date == date(y, 1, 2).isoformat(),
                    TradingCalendarORM.market == market,
                )
                .limit(1)
            ).scalar_one_or_none():
                self.seed_year(y, market)
