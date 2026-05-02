from fastapi import APIRouter, HTTPException

from apps.api.app.schemas.execution import (
    OrderSimulationRequest,
    OrderSimulationResponse,
)
from apps.api.app.services.execution_service import ExecutionService


router = APIRouter(prefix="/orders", tags=["orders"])
service = ExecutionService()


@router.post("/simulate", response_model=OrderSimulationResponse)
def simulate_order(request: OrderSimulationRequest) -> OrderSimulationResponse:
    try:
        result = service.simulate_order(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return OrderSimulationResponse(**result)

