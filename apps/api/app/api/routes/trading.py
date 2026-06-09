"""交易闭环 API：模拟盘 / QMT Gateway 统一入口"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api.app.core.auth import get_current_user, require_trader
from apps.api.app.db.session import get_db
from apps.api.app.services import trading_service

router = APIRouter(prefix="/trading", tags=["trading"])


class OrderReq(BaseModel):
    symbol: str
    side: str = Field(..., pattern="^(BUY|SELL|buy|sell)$")
    quantity: int = Field(..., gt=0)
    order_type: str = Field("LIMIT", pattern="^(LIMIT|MARKET|limit|market)$")
    price: float | None = None
    name: str = ""
    source: str = "manual"
    strategy: str = ""
    reason: str = ""


class RebalancePlanReq(BaseModel):
    top_n: int = Field(8, ge=1, le=30)
    min_score: int = Field(60, ge=0, le=100)
    candidate_pool: int = Field(30, ge=1, le=300)
    enable_fundamental: bool = True
    enable_llm: bool = False
    llm_top_n: int = Field(8, ge=1, le=20)
    target_horizon_days: int | None = Field(default=None, ge=0, le=60)
    weighting_scheme: str = Field(
        "risk_adjusted",
        pattern="^(signal_proportional|equal_weight|inverse_volatility|risk_adjusted)$",
    )
    use_cache: bool = True


@router.get("/account")
def get_account(_: object = Depends(get_current_user), db: Session = Depends(get_db)):
    return trading_service.get_account(db)


@router.get("/positions")
def list_positions(_: object = Depends(get_current_user), db: Session = Depends(get_db)):
    return trading_service.list_positions(db)


@router.get("/orders")
def list_orders(limit: int = 100, _: object = Depends(get_current_user), db: Session = Depends(get_db)):
    return trading_service.list_orders(db, limit=limit)


@router.get("/fills")
def list_fills(limit: int = 100, _: object = Depends(get_current_user), db: Session = Depends(get_db)):
    return trading_service.list_fills(db, limit=limit)


@router.post("/sync")
def sync_qmt_state(limit: int = 200, _: object = Depends(require_trader), db: Session = Depends(get_db)):
    return trading_service.sync_qmt_state(db, limit=limit)


@router.post("/preview")
def preview_order(req: OrderReq, _: object = Depends(require_trader), db: Session = Depends(get_db)):
    return trading_service.preview_order(
        db,
        symbol=req.symbol,
        side=req.side,
        quantity=req.quantity,
        price=req.price,
    )


@router.post("/rebalance-plan")
def rebalance_plan(
    req: RebalancePlanReq,
    _: object = Depends(require_trader),
    db: Session = Depends(get_db),
):
    return trading_service.generate_rebalance_plan(
        db,
        top_n=req.top_n,
        min_score=req.min_score,
        candidate_pool=req.candidate_pool,
        enable_fundamental=req.enable_fundamental,
        enable_llm=req.enable_llm,
        llm_top_n=req.llm_top_n,
        target_horizon_days=req.target_horizon_days,
        weighting_scheme=req.weighting_scheme,
        use_cache=req.use_cache,
    )


@router.post("/orders")
def place_order(
    req: OrderReq,
    _: object = Depends(require_trader),
    db: Session = Depends(get_db),
):
    return trading_service.place_order(
        db,
        symbol=req.symbol,
        side=req.side,
        quantity=req.quantity,
        order_type=req.order_type,
        price=req.price,
        name=req.name,
        source=req.source,
        strategy=req.strategy,
        reason=req.reason,
    )


@router.post("/orders/{order_id}/cancel")
def cancel_order(
    order_id: str,
    _: object = Depends(require_trader),
    db: Session = Depends(get_db),
):
    try:
        return trading_service.cancel_order(db, order_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="订单不存在")
