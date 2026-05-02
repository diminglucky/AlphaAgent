"""Multi-agent analysis endpoint."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from apps.api.app.api.routes.live_orders import get_current_user
from apps.api.app.core.auth import AuthenticatedUser
from apps.api.app.core.rate_limit import rate_limit_analyze
from apps.api.app.db.session import get_db
from apps.api.app.schemas.analysis import AnalyzeRequest, AnalysisReportResponse
from apps.api.app.services.analyze_service import AnalyzeService

router = APIRouter(prefix="/recommendations", tags=["analysis"])


@router.post(
    "/analyze/{symbol}",
    response_model=AnalysisReportResponse,
    summary="多 Agent LLM 深度分析单只股票",
    dependencies=[Depends(rate_limit_analyze)],
)
def analyze_symbol(
    symbol: str,
    body: AnalyzeRequest = None,
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> AnalysisReportResponse:
    svc = AnalyzeService(db)
    try:
        report = svc.analyze(
            symbol=symbol,
            portfolio_context=body.portfolio_context if body else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return AnalysisReportResponse(
        symbol=report.symbol,
        action=report.action.value,
        confidence=report.confidence,
        summary=report.summary,
        reasoning=report.reasoning,
        risk_flags=report.risk_flags,
        components=report.components,
        approved=report.approved,
        generated_at=report.generated_at,
        llm_powered=report.llm_powered,
    )
