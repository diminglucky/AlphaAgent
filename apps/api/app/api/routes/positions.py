"""持仓管理路由"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apps.api.app.db.session import get_db
from apps.api.app.db.models import PositionORM
from apps.api.app.services import market_service

router = APIRouter(prefix="/positions", tags=["positions"])


class UpsertPositionReq(BaseModel):
    symbol: str
    name: str = ""
    quantity: int
    avg_cost: float
    stop_loss_pct: float = 0.08   # 8% 止损
    take_profit_pct: float = 0.20  # 20% 止盈


@router.get("/")
def list_positions(db: Session = Depends(get_db)):
    positions = db.query(PositionORM).all()
    if not positions:
        return []

    symbols = [p.symbol for p in positions]
    quotes = market_service.get_realtime_quotes(symbols)
    quote_map = {q["symbol"]: q for q in quotes}

    result = []
    for p in positions:
        q = quote_map.get(p.symbol, {})
        price = q.get("price", p.avg_cost)
        market_value = price * p.quantity
        cost_value = p.avg_cost * p.quantity
        pnl = market_value - cost_value
        pnl_pct = (price - p.avg_cost) / p.avg_cost * 100 if p.avg_cost > 0 else 0

        result.append({
            "id": p.id,
            "symbol": p.symbol,
            "name": p.name or q.get("name", p.symbol),
            "quantity": p.quantity,
            "avg_cost": p.avg_cost,
            "current_price": price,
            "market_value": round(market_value, 2),
            "cost_value": round(cost_value, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "change_pct": q.get("change_pct", 0),
            "stop_loss_price": round(p.avg_cost * (1 - p.stop_loss_pct), 2),
            "take_profit_price": round(p.avg_cost * (1 + p.take_profit_pct), 2),
            "stop_loss_pct": p.stop_loss_pct,
            "take_profit_pct": p.take_profit_pct,
        })
    return result


@router.post("/")
def upsert_position(req: UpsertPositionReq, db: Session = Depends(get_db)):
    """新增或更新持仓"""
    pos = db.query(PositionORM).filter(PositionORM.symbol == req.symbol).first()

    name = req.name
    if not name:
        q = market_service.get_single_quote(req.symbol)
        name = q.get("name", req.symbol) if q else req.symbol

    if pos:
        pos.quantity = req.quantity
        pos.avg_cost = req.avg_cost
        pos.name = name
        pos.stop_loss_pct = req.stop_loss_pct
        pos.take_profit_pct = req.take_profit_pct
    else:
        pos = PositionORM(
            symbol=req.symbol,
            name=name,
            quantity=req.quantity,
            avg_cost=req.avg_cost,
            stop_loss_pct=req.stop_loss_pct,
            take_profit_pct=req.take_profit_pct,
        )
        db.add(pos)

    db.commit()
    db.refresh(pos)
    return {"id": pos.id, "symbol": pos.symbol, "name": pos.name}


@router.delete("/{symbol}")
def delete_position(symbol: str, db: Session = Depends(get_db)):
    pos = db.query(PositionORM).filter(PositionORM.symbol == symbol).first()
    if not pos:
        raise HTTPException(status_code=404, detail="持仓不存在")
    db.delete(pos)
    db.commit()
    return {"ok": True}
