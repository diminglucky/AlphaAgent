from apps.api.app.schemas.execution import OrderSimulationRequest
from apps.api.app.services.execution_service import ExecutionService


def test_simulate_order_accepts_reasonable_buy() -> None:
    service = ExecutionService()

    result = service.simulate_order(
        OrderSimulationRequest(
            symbol="300750.SZ",
            side="BUY",
            quantity=100,
            price=236.8,
        )
    )

    assert result["accepted"] is True
    assert result["remaining_cash_after_order"] > 0

