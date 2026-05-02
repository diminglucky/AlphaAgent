from apps.api.app.db.bootstrap import ensure_database_initialized
from apps.api.app.db.repositories import PortfolioRepository
from apps.api.app.db.session import session_scope
from apps.api.app.services.sample_data import PORTFOLIO_SUMMARY, POSITIONS
from libs.quant_core.models import PortfolioSummary, Position


class PortfolioService:
    def get_summary(self) -> PortfolioSummary:
        ensure_database_initialized()
        with session_scope() as session:
            summary = PortfolioRepository(session).get_summary()
        return summary or PORTFOLIO_SUMMARY

    def get_positions(self) -> list[Position]:
        ensure_database_initialized()
        with session_scope() as session:
            positions = PortfolioRepository(session).list_positions()
        return positions or POSITIONS
