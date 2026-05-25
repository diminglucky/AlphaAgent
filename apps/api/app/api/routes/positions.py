"""持仓管理路由"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apps.api.app.db.session import get_db
from apps.api.app.db.models import AlertORM, PositionORM
from apps.api.app.services import alert_service, market_service

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
    symbol = _normalize_symbol(req.symbol)
    pos = db.query(PositionORM).filter(PositionORM.symbol == symbol).first()

    name = req.name
    if not name:
        q = market_service.get_single_quote(symbol)
        name = q.get("name", symbol) if q else symbol

    if pos:
        pos.quantity = req.quantity
        pos.avg_cost = req.avg_cost
        pos.name = name
        pos.stop_loss_pct = req.stop_loss_pct
        pos.take_profit_pct = req.take_profit_pct
        # 调整成本/止损线后清理上次告警标记
        pos.last_alert_at = None
        pos.last_alert_kind = None
    else:
        pos = PositionORM(
            symbol=symbol,
            name=name,
            quantity=req.quantity,
            avg_cost=req.avg_cost,
            stop_loss_pct=req.stop_loss_pct,
            take_profit_pct=req.take_profit_pct,
        )
        db.add(pos)

    db.commit()
    db.refresh(pos)
    # 调整持仓后清理之前的告警状态，让新成本基线立即生效
    alert_service.reset_position_alert_state(symbol)
    return {"id": pos.id, "symbol": pos.symbol, "name": pos.name}


@router.delete("/{symbol}")
def delete_position(symbol: str, db: Session = Depends(get_db)):
    symbol = _normalize_symbol(symbol)
    pos = db.query(PositionORM).filter(PositionORM.symbol == symbol).first()
    if not pos:
        raise HTTPException(status_code=404, detail="持仓不存在")
    db.delete(pos)
    # 清理对应的 agent_buy / agent_sell / stop_loss 等关联提醒
    db.query(AlertORM).filter(
        AlertORM.symbol == symbol,
        AlertORM.alert_type.in_(("agent_buy", "agent_sell", "stop_loss", "take_profit")),
    ).delete(synchronize_session=False)
    db.commit()
    # 清理告警去重状态
    alert_service.reset_position_alert_state(symbol)
    return {"ok": True}


def _normalize_symbol(symbol: str) -> str:
    """统一格式：600519.SH（数字部分.交易所大写）"""
    s = (symbol or "").strip().upper()
    if not s:
        return s

    if "." in s:
        code, suffix = s.split(".", 1)
    else:
        prefix = s[:2]
        if prefix in {"SH", "SZ", "BJ"} and s[2:].isdigit():
            code, suffix = s[2:], prefix
        else:
            code = s
            suffix = "SH" if code.startswith(("6", "9")) else "SZ"

    code = code.strip().upper()
    for prefix in ("SH", "SZ", "BJ"):
        if code.startswith(prefix):
            code = code[2:]
            if not suffix:
                suffix = prefix
            break

    if code.isdigit():
        code = code.zfill(6)
    return f"{code}.{suffix.upper()}"
