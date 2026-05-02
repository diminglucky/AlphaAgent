from apps.api.app.core.config import reset_settings_cache
from apps.api.app.db.bootstrap import ensure_database_initialized, reset_bootstrap_cache
from apps.api.app.db.repositories import PortfolioRepository, RecommendationRepository
from apps.api.app.db.session import reset_db_caches, session_scope


def test_database_bootstrap_seeds_demo_data(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "quant-test.db"
    monkeypatch.setenv("QUANT_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("QUANT_SEED_DEMO_DATA", "true")

    reset_settings_cache()
    reset_db_caches()
    reset_bootstrap_cache()

    ensure_database_initialized()

    with session_scope() as session:
        portfolio_repo = PortfolioRepository(session)
        recommendation_repo = RecommendationRepository(session)

        summary = portfolio_repo.get_summary()
        positions = portfolio_repo.list_positions()
        as_of, recommendations = recommendation_repo.list_latest()

    assert summary is not None
    assert summary.account_id == "acct-demo-001"
    assert len(positions) >= 2
    assert as_of is not None
    assert len(recommendations) >= 3

    reset_settings_cache()
    reset_db_caches()
    reset_bootstrap_cache()

