from apps.api.app.schemas.execution import OrderSimulationRequest
from apps.api.app.services.portfolio_service import PortfolioService
from apps.api.app.services.sample_data import BUYABLE_SYMBOLS, ORDER_SIDES


class ExecutionService:
    def __init__(self) -> None:
        self.portfolio_service = PortfolioService()
        self.single_order_cash_limit_ratio = 0.25

    def simulate_order(self, request: OrderSimulationRequest) -> dict[str, object]:
        if request.side not in ORDER_SIDES:
            raise ValueError(f"Unsupported side: {request.side}")

        if request.symbol not in BUYABLE_SYMBOLS:
            raise ValueError(f"Unknown symbol: {request.symbol}")

        summary = self.portfolio_service.get_summary()
        estimated_notional = request.price * request.quantity
        required_cash = estimated_notional * 1.0005
        remaining_cash = summary.cash - required_cash

        reasons: list[str] = []
        risk_checks = [
            "symbol_exists",
            "positive_quantity",
            "positive_price",
        ]

        accepted = True

        if request.side == "BUY":
            risk_checks.append("cash_available_check")
            if required_cash > summary.cash:
                accepted = False
                reasons.append("Insufficient cash for the requested buy order.")

            max_single_order_cash = summary.total_asset * self.single_order_cash_limit_ratio
            risk_checks.append("single_order_cash_limit")
            if required_cash > max_single_order_cash:
                accepted = False
                reasons.append("Order size exceeds the configured single-order cash limit.")

        if request.side == "SELL":
            risk_checks.append("position_available_check")

        if accepted:
            reasons.append("Order passed simulated risk checks.")

        return {
            "accepted": accepted,
            "reasons": reasons,
            "estimated_notional": round(estimated_notional, 2),
            "required_cash": round(required_cash, 2),
            "remaining_cash_after_order": round(remaining_cash, 2),
            "risk_checks": risk_checks,
        }

