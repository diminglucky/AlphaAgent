"""Fundamental features for A-share stocks.

Fundamental data (PE, PB, ROE, revenue growth …) is fetched from a market-data
provider and normalised into a typed dataclass so signal engines and agents can
consume it uniformly.

Currently the builder is implemented as a lightweight pass-through that accepts
pre-fetched fields.  A richer version would call the market-data provider
directly and handle missing values from incomplete disclosures.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass(frozen=True)
class FundamentalFeatures:
    """Fundamental features for a single stock on a given date."""

    symbol: str
    as_of_date: date

    # Valuation
    pe_ttm: Optional[float] = None        # Price / Trailing 12-month EPS
    pb: Optional[float] = None            # Price / Book
    ps_ttm: Optional[float] = None        # Price / Sales (TTM)
    ev_ebitda: Optional[float] = None     # Enterprise Value / EBITDA

    # Profitability
    roe: Optional[float] = None           # Return on Equity (latest annual)
    roa: Optional[float] = None           # Return on Assets
    gross_margin: Optional[float] = None  # Gross profit margin
    net_margin: Optional[float] = None    # Net profit margin

    # Growth
    revenue_yoy: Optional[float] = None   # Revenue year-over-year growth
    profit_yoy: Optional[float] = None    # Net profit year-over-year growth

    # Financial health
    debt_to_equity: Optional[float] = None
    current_ratio: Optional[float] = None

    # Dividend
    dividend_yield: Optional[float] = None


def score_valuation(features: FundamentalFeatures) -> float:
    """Return a valuation score in [-1, 1]; negative = expensive, positive = cheap.

    Thresholds are rough A-share market averages and can be tuned per sector.
    """
    score = 0.0
    checks = 0

    if features.pe_ttm is not None and features.pe_ttm > 0:
        if features.pe_ttm < 15:
            score += 0.4
        elif features.pe_ttm < 25:
            score += 0.2
        elif features.pe_ttm > 50:
            score -= 0.4
        elif features.pe_ttm > 35:
            score -= 0.2
        checks += 1

    if features.pb is not None and features.pb > 0:
        if features.pb < 1.5:
            score += 0.3
        elif features.pb < 3.0:
            score += 0.1
        elif features.pb > 8.0:
            score -= 0.3
        checks += 1

    if features.roe is not None:
        if features.roe > 0.20:
            score += 0.3
        elif features.roe > 0.12:
            score += 0.1
        elif features.roe < 0.0:
            score -= 0.4
        checks += 1

    if checks == 0:
        return 0.0
    return max(-1.0, min(1.0, score / checks * checks))


def score_growth(features: FundamentalFeatures) -> float:
    """Return a growth score in [-1, 1]; positive = strong growth."""
    score = 0.0
    checks = 0

    if features.revenue_yoy is not None:
        if features.revenue_yoy > 0.30:
            score += 0.5
        elif features.revenue_yoy > 0.10:
            score += 0.2
        elif features.revenue_yoy < -0.10:
            score -= 0.3
        checks += 1

    if features.profit_yoy is not None:
        if features.profit_yoy > 0.30:
            score += 0.5
        elif features.profit_yoy > 0.10:
            score += 0.2
        elif features.profit_yoy < -0.20:
            score -= 0.4
        checks += 1

    if checks == 0:
        return 0.0
    return max(-1.0, min(1.0, score / checks * checks))


def build_fundamental_features(
    symbol: str,
    as_of_date: date,
    *,
    pe_ttm: Optional[float] = None,
    pb: Optional[float] = None,
    ps_ttm: Optional[float] = None,
    ev_ebitda: Optional[float] = None,
    roe: Optional[float] = None,
    roa: Optional[float] = None,
    gross_margin: Optional[float] = None,
    net_margin: Optional[float] = None,
    revenue_yoy: Optional[float] = None,
    profit_yoy: Optional[float] = None,
    debt_to_equity: Optional[float] = None,
    current_ratio: Optional[float] = None,
    dividend_yield: Optional[float] = None,
) -> FundamentalFeatures:
    """Construct a :class:`FundamentalFeatures` from raw provider values."""
    return FundamentalFeatures(
        symbol=symbol,
        as_of_date=as_of_date,
        pe_ttm=pe_ttm,
        pb=pb,
        ps_ttm=ps_ttm,
        ev_ebitda=ev_ebitda,
        roe=roe,
        roa=roa,
        gross_margin=gross_margin,
        net_margin=net_margin,
        revenue_yoy=revenue_yoy,
        profit_yoy=profit_yoy,
        debt_to_equity=debt_to_equity,
        current_ratio=current_ratio,
        dividend_yield=dividend_yield,
    )
