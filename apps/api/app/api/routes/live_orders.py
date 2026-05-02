"""Live order management endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from apps.api.app.core.auth import AuthenticatedUser, get_current_user, require_trader
from apps.api.app.core.config import get_settings
from apps.api.app.db.session import get_db
from apps.api.app.schemas.execution import (
    OrderResponse,
    PlaceOrderRequest,
    SimulateFillRequest,
    TradeFillResponse,
)
from apps.api.app.services.order_service import OrderService

router = APIRouter(prefix="/orders/live", tags=["orders-live"])


def _order_to_response(order) -> OrderResponse:
    return OrderResponse(
        order_id=order.order_id,
        account_id=order.account_id,
        symbol=order.symbol,
        side=order.side,
        order_type=order.order_type,
        price=order.price,
        quantity=order.quantity,
        filled_quantity=order.filled_quantity,
        status=order.status,
        broker_order_id=order.broker_order_id,
        source=order.source,
        reject_reason=order.reject_reason,
        created_at=order.created_at,
        updated_at=order.updated_at,
    )


@router.post("/confirm-token")
def issue_confirmation_token(req: PlaceOrderRequest):
    """Issue a manual confirmation token (§5.5.4)."""
    from apps.api.app.services.confirmation_token import issue_token
    return issue_token(req.symbol, req.side, req.quantity, req.price)


@router.post("", response_model=OrderResponse, status_code=201)
def place_order(
    req: PlaceOrderRequest,
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(require_trader),
) -> OrderResponse:
    # Manual confirmation gate (§5.5.4)
    settings = get_settings()
    if settings.require_order_confirmation:
        from apps.api.app.services.confirmation_token import consume_token
        ok, reason = consume_token(
            req.confirmation_token, req.symbol, req.side, req.quantity, req.price
        )
        if not ok:
            raise HTTPException(status_code=400, detail=f"MANUAL_CONFIRMATION_REQUIRED: {reason}")

    try:
        order = OrderService(db).place_order(
            symbol=req.symbol,
            side=req.side,
            order_type=req.order_type,
            price=req.price,
            quantity=req.quantity,
            source=req.source,
            actor=user.api_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _order_to_response(order)


@router.get("", response_model=list[OrderResponse])
def list_orders(
    limit: int = 50,
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> list[OrderResponse]:
    orders = OrderService(db).list_orders(limit=limit)
    return [_order_to_response(o) for o in orders]


@router.get("/{order_id}", response_model=OrderResponse)
def get_order(
    order_id: str,
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> OrderResponse:
    try:
        order = OrderService(db).get_order(order_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _order_to_response(order)


@router.delete("/{order_id}", response_model=OrderResponse)
def cancel_order(
    order_id: str,
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(require_trader),
) -> OrderResponse:
    try:
        order = OrderService(db).cancel_order(order_id, actor=user.api_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _order_to_response(order)


@router.post("/{order_id}/fills", response_model=TradeFillResponse, status_code=201)
def simulate_fill(
    order_id: str,
    req: SimulateFillRequest,
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(require_trader),
) -> TradeFillResponse:
    try:
        fill = OrderService(db).simulate_fill(order_id, req.fill_price, req.fill_quantity)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TradeFillResponse(
        fill_id=fill.fill_id,
        order_id=fill.order_id,
        symbol=fill.symbol,
        fill_price=fill.fill_price,
        fill_quantity=fill.fill_quantity,
        fill_time=fill.fill_time,
        commission=fill.commission,
    )


@router.get("/{order_id}/fills", response_model=list[TradeFillResponse])
def list_fills(
    order_id: str,
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> list[TradeFillResponse]:
    fills = OrderService(db).list_fills(order_id)
    return [
        TradeFillResponse(
            fill_id=f.fill_id,
            order_id=f.order_id,
            symbol=f.symbol,
            fill_price=f.fill_price,
            fill_quantity=f.fill_quantity,
            fill_time=f.fill_time,
            commission=f.commission,
        )
        for f in fills
    ]
