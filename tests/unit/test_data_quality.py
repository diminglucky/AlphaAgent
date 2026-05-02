"""Tests for OHLC data quality validation (§5.4.3)."""

from __future__ import annotations

from datetime import date

from libs.market_data.quality import validate_ohlc
from libs.quant_core.models import MarketBar


def _bar(d, o, h, l, c, v=10000):
    return MarketBar(
        symbol="TEST.SH", trade_date=d, open=o, high=h, low=l, close=c,
        volume=v, amount=float(v) * c, turnover_rate=0.5,
        adj_type="qfq", data_source="test",
    )


def test_clean_bars_pass() -> None:
    bars = [
        _bar(date(2026, 4, 23), 100, 102, 99, 101),
        _bar(date(2026, 4, 24), 101, 103, 100, 102),
    ]
    rep = validate_ohlc(bars)
    assert rep.total == 2
    assert rep.ok == 2
    assert not rep.has_errors


def test_high_inconsistent_flagged() -> None:
    bars = [_bar(date(2026, 4, 23), 100, 99, 95, 98)]  # high < open
    rep = validate_ohlc(bars)
    assert rep.has_errors
    assert any(i.code == "HIGH_INCONSISTENT" for i in rep.issues)


def test_negative_price_flagged() -> None:
    bars = [_bar(date(2026, 4, 23), -1, 5, -2, 3)]
    rep = validate_ohlc(bars)
    assert rep.has_errors
    assert any(i.code == "NON_POSITIVE_PRICE" for i in rep.issues)


def test_extreme_pct_change_flagged() -> None:
    bars = [
        _bar(date(2026, 4, 23), 100, 102, 99, 100),
        _bar(date(2026, 4, 24), 100, 200, 99, 200),  # +100% — absurd
    ]
    rep = validate_ohlc(bars)
    assert any(i.code == "EXTREME_PCT_CHANGE" for i in rep.issues)


def test_st_stricter_limit_warns() -> None:
    bars = [
        _bar(date(2026, 4, 23), 10, 11, 9.5, 10),
        _bar(date(2026, 4, 24), 10, 11, 10, 10.7),  # +7% triggers ST 5%
    ]
    rep = validate_ohlc(bars, st=True)
    assert any(i.code == "PCT_CHANGE_OVER_LIMIT" for i in rep.issues)
