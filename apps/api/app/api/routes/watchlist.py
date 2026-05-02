"""Watchlist (自选股) CRUD endpoints."""

from __future__ import annotations

from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apps.api.app.api.routes.live_orders import get_current_user
from apps.api.app.core.auth import AuthenticatedUser
from apps.api.app.core.config import get_settings
from apps.api.app.db.session import get_db
from apps.api.app.services.watchlist_service import WatchlistService

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


class WatchlistAddRequest(BaseModel):
    symbol: str
    note: Optional[str] = ""
    sort_order: Optional[int] = 0


class WatchlistReorderRequest(BaseModel):
    symbols: list[str]


def _account(user: AuthenticatedUser) -> str:
    """Use the user's role-based id when auth is enabled, otherwise fall
    back to the default account from settings."""
    if user and getattr(user, "user_id", None):
        return user.user_id
    return get_settings().default_account_id


@router.get("/", summary="列出自选股")
def list_watchlist(
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
):
    svc = WatchlistService(db)
    items = svc.list_items(_account(user))
    return {"items": [asdict(i) for i in items], "count": len(items)}


@router.post("/", summary="添加自选股", status_code=201)
def add_watchlist(
    req: WatchlistAddRequest,
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
):
    svc = WatchlistService(db)
    try:
        item = svc.add(_account(user), req.symbol, req.note or "", req.sort_order or 0)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    return asdict(item)


@router.delete("/{symbol}", summary="移除自选股")
def remove_watchlist(
    symbol: str,
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
):
    svc = WatchlistService(db)
    removed = svc.remove(_account(user), symbol)
    if not removed:
        raise HTTPException(404, f"自选股中不存在: {symbol}")
    db.commit()
    return {"removed": True, "symbol": symbol.upper()}


@router.put("/reorder", summary="重新排序自选股")
def reorder_watchlist(
    req: WatchlistReorderRequest,
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
):
    svc = WatchlistService(db)
    n = svc.reorder(_account(user), req.symbols)
    db.commit()
    return {"updated": n}
