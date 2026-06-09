"""自选股路由"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apps.api.app.db.session import get_db
from apps.api.app.db.models import WatchlistORM
from apps.api.app.core.auth import get_current_user, require_trader
from apps.api.app.services import market_service

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


def _normalize_symbol(symbol: str) -> str:
    """统一格式：CODE.EXCHANGE（数字代码 + 大写后缀）"""
    s = (symbol or "").strip()
    if "." in s:
        code, suffix = s.split(".", 1)
        return f"{code}.{suffix.upper()}"
    return s.upper()


class AddSymbolReq(BaseModel):
    symbol: str
    name: str = ""
    note: str = ""


@router.get("/")
def list_watchlist(_: object = Depends(get_current_user), db: Session = Depends(get_db)):
    items = db.query(WatchlistORM).order_by(WatchlistORM.sort_order, WatchlistORM.id).all()
    return [
        {
            "id": item.id,
            "symbol": item.symbol,
            "name": item.name,
            "note": item.note,
            "sort_order": item.sort_order,
        }
        for item in items
    ]


@router.post("/")
def add_symbol(req: AddSymbolReq, _: object = Depends(require_trader), db: Session = Depends(get_db)):
    symbol = _normalize_symbol(req.symbol)
    existing = db.query(WatchlistORM).filter(WatchlistORM.symbol == symbol).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"{symbol} 已在自选股中")

    # 自动获取股票名称
    name = req.name
    if not name:
        q = market_service.get_single_quote(symbol)
        name = q.get("name", symbol) if q else symbol

    max_order = db.query(WatchlistORM).count()
    item = WatchlistORM(symbol=symbol, name=name, note=req.note, sort_order=max_order)
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"id": item.id, "symbol": item.symbol, "name": item.name}


@router.delete("/{symbol}")
def remove_symbol(symbol: str, _: object = Depends(require_trader), db: Session = Depends(get_db)):
    symbol = _normalize_symbol(symbol)
    item = db.query(WatchlistORM).filter(WatchlistORM.symbol == symbol).first()
    if not item:
        raise HTTPException(status_code=404, detail="股票不在自选股中")
    db.delete(item)
    db.commit()
    return {"ok": True}


@router.get("/with-quotes")
def list_with_quotes(_: object = Depends(get_current_user), db: Session = Depends(get_db)):
    """自选股列表 + 实时行情"""
    items = db.query(WatchlistORM).order_by(WatchlistORM.sort_order, WatchlistORM.id).all()
    if not items:
        return []
    symbols = [item.symbol for item in items]
    quotes = market_service.get_realtime_quotes(symbols)
    quote_map = {q["symbol"]: q for q in quotes}

    result = []
    for item in items:
        q = quote_map.get(item.symbol, {})
        result.append({
            "id": item.id,
            "symbol": item.symbol,
            "name": item.name or q.get("name", item.symbol),
            "note": item.note,
            "price": q.get("price", 0),
            "change_pct": q.get("change_pct", 0),
            "change": q.get("change", 0),
            "volume": q.get("volume", 0),
            "turnover_rate": q.get("turnover_rate", 0),
            "pe_ratio": q.get("pe_ratio", 0),
        })
    return result
