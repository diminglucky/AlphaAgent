"""Tests for fundamental feature engineering."""

from datetime import date

import pytest

from libs.features.fundamental import (
    FundamentalFeatures,
    build_fundamental_features,
    score_growth,
    score_valuation,
)


def _make(
    pe_ttm=None, pb=None, roe=None, revenue_yoy=None, profit_yoy=None
) -> FundamentalFeatures:
    return build_fundamental_features(
        "000001.SZ",
        date(2026, 4, 30),
        pe_ttm=pe_ttm,
        pb=pb,
        roe=roe,
        revenue_yoy=revenue_yoy,
        profit_yoy=profit_yoy,
    )


def test_cheap_high_roe_positive_valuation():
    f = _make(pe_ttm=12.0, pb=1.2, roe=0.25)
    assert score_valuation(f) > 0


def test_expensive_negative_valuation():
    f = _make(pe_ttm=60.0, pb=10.0, roe=0.05)
    assert score_valuation(f) < 0


def test_no_data_zero_score():
    f = _make()
    assert score_valuation(f) == 0.0
    assert score_growth(f) == 0.0


def test_strong_growth_positive():
    f = _make(revenue_yoy=0.40, profit_yoy=0.50)
    assert score_growth(f) > 0


def test_declining_profits_negative():
    f = _make(revenue_yoy=-0.15, profit_yoy=-0.30)
    assert score_growth(f) < 0


def test_build_roundtrip():
    f = build_fundamental_features(
        "600519.SH",
        date(2026, 4, 30),
        pe_ttm=25.0,
        pb=8.0,
        roe=0.35,
        revenue_yoy=0.12,
        profit_yoy=0.18,
        dividend_yield=0.02,
    )
    assert f.symbol == "600519.SH"
    assert f.pe_ttm == 25.0
    assert f.roe == 0.35
    assert f.dividend_yield == 0.02
