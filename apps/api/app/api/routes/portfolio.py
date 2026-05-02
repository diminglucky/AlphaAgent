from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException

from apps.api.app.core.auth import AuthenticatedUser, require_trader
from apps.api.app.schemas.portfolio import (
    PortfolioSummaryResponse,
    PositionResponse,
    RebalanceActionResponse,
    RebalanceRequest,
    RebalanceResponse,
)
from apps.api.app.services.portfolio_service import PortfolioService
from libs.portfolio.optimizer import PortfolioOptimizer, WeightingScheme


router = APIRouter(prefix="/portfolio", tags=["portfolio"])
service = PortfolioService()


@router.get("/summary", response_model=PortfolioSummaryResponse)
def get_portfolio_summary() -> PortfolioSummaryResponse:
    return PortfolioSummaryResponse(**asdict(service.get_summary()))


@router.get("/positions", response_model=list[PositionResponse])
def get_positions() -> list[PositionResponse]:
    return [PositionResponse(**asdict(item)) for item in service.get_positions()]


@router.post("/rebalance", response_model=RebalanceResponse)
def rebalance(
    req: RebalanceRequest,
    user: AuthenticatedUser = Depends(require_trader),
) -> RebalanceResponse:
    """Compute a rebalancing plan from signal scores.

    Calls :class:`PortfolioOptimizer` with the requested allocation *scheme*
    and returns the list of BUY/SELL actions along with expected turnover,
    cash ratio, and any constraint warnings.  **No orders are placed** — this
    is a read-only planning endpoint.
    """
    try:
        scheme = WeightingScheme(req.scheme)
    except ValueError:
        valid = ", ".join(s.value for s in WeightingScheme)
        raise HTTPException(
            status_code=422,
            detail=f"Unknown scheme '{req.scheme}'. Valid values: {valid}",
        )

    positions = service.get_positions()
    summary = service.get_summary()
    total_value = summary.total_asset or 1.0

    optimizer = PortfolioOptimizer()
    result = optimizer.optimize(
        signals=req.signals,
        current_positions=positions,
        total_value=total_value,
        current_prices=req.prices,
        scheme=scheme,
        volatilities=req.volatilities,
    )

    return RebalanceResponse(
        actions=[
            RebalanceActionResponse(
                symbol=a.symbol,
                current_weight=a.current_weight,
                target_weight=a.target_weight,
                action=a.action,
                quantity_change=a.quantity_change,
                estimated_value_change=a.estimated_value_change,
                reason=a.reason,
            )
            for a in result.actions
        ],
        expected_turnover=result.expected_turnover,
        expected_cash_ratio=result.expected_cash_ratio,
        risk_metrics=result.risk_metrics,
        warnings=result.warnings,
    )

