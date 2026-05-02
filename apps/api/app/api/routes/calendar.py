"""Trading calendar endpoints (§5.3.2)."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from apps.api.app.db.session import get_db
from apps.api.app.services.calendar_service import CalendarService

router = APIRouter(prefix="/calendar", tags=["calendar"])


@router.get("/today")
def is_today_open(market: str = "A", db: Session = Depends(get_db)):
    svc = CalendarService(db)
    today = date.today()
    return {
        "trade_date": today.isoformat(),
        "market": market,
        "is_open": svc.is_trading_day(today, market),
        "next_trading_day": svc.next_trading_day(today, market).isoformat(),
        "previous_trading_day": svc.previous_trading_day(today, market).isoformat(),
    }


@router.get("/range")
def list_calendar(
    start: str = Query(..., description="YYYY-MM-DD"),
    end: str = Query(..., description="YYYY-MM-DD"),
    market: str = "A",
    only_open: bool = True,
    db: Session = Depends(get_db),
):
    svc = CalendarService(db)
    return [
        {
            "trade_date": e.trade_date.isoformat(),
            "market": e.market,
            "is_open": e.is_open,
            "session_type": e.session_type,
        }
        for e in svc.list_range(start, end, market=market, only_open=only_open)
    ]


@router.post("/seed/{year}")
def seed_year(year: int, market: str = "A", db: Session = Depends(get_db)):
    """Seed (or top up) the calendar table for a given year."""
    added = CalendarService(db).seed_year(year, market)
    return {"year": year, "market": market, "added": added}
