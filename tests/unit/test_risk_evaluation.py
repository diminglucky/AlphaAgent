"""Test risk engine pre-trade evaluation."""

from __future__ import annotations

from sqlalchemy.orm import Session

from apps.api.app.services.risk_service import RiskService


def test_block_oversized_position(seeded_session: Session) -> None:
    db_session = seeded_session
    """Buying that would push 600519 weight far above 30% should be BLOCKED."""
    svc = RiskService(db_session)
    # Sample positions: 600519 already at 515,850 value. Total ~ 800K.
    # Adding 100 × 1719 = 171,900 → weight ~ 86% (way > 30%)
    from apps.api.app.db.repositories import PortfolioRepository
    portfolio = PortfolioRepository(db_session)
    positions = portfolio.list_positions()
    summary = portfolio.get_summary()
    total = summary.total_asset if summary else 1_000_000

    allowed, events = svc.evaluate_order(
        symbol="600519.SH", side="BUY", price=1719.5, quantity=100,
        positions=positions, portfolio_total_value=total,
    )
    assert allowed is False
    assert any(e.decision == "BLOCK" for e in events)


def test_pass_small_position(seeded_session: Session) -> None:
    db_session = seeded_session
    svc = RiskService(db_session)
    from apps.api.app.db.repositories import PortfolioRepository
    portfolio = PortfolioRepository(db_session)
    allowed, events = svc.evaluate_order(
        symbol="300750.SZ", side="BUY", price=240.0, quantity=100,
        positions=portfolio.list_positions(),
        portfolio_total_value=1_000_000,
    )
    # 24,000 / 1M = 2.4% weight — should pass
    assert allowed is True


def test_industry_rule_skipped_silently(seeded_session: Session) -> None:
    db_session = seeded_session
    """Rules that require data we don't have (industry) shouldn't crash."""
    svc = RiskService(db_session)
    from apps.api.app.db.repositories import PortfolioRepository
    portfolio = PortfolioRepository(db_session)
    allowed, _events = svc.evaluate_order(
        symbol="300750.SZ", side="BUY", price=240.0, quantity=10,
        positions=portfolio.list_positions(),
        portfolio_total_value=1_000_000,
    )
    assert allowed is True  # no crash, no spurious blocks
