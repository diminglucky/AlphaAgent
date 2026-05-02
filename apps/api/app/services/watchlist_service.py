"""Watchlist (自选股) service — CRUD + lookup helpers.

Stores per-account symbol lists in the database so the user can manage
their own watchlist instead of being constrained to the hard-coded
`WATCHED_SYMBOLS` array.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from apps.api.app.db.models import WatchlistORM
from apps.api.app.db.repositories import AuditLogRepository
from libs.quant_core.enums import AuditAction
from libs.quant_core.models import AuditLog


# Default seed list — same as previous WATCHED_SYMBOLS so behaviour is
# unchanged for fresh installs.
DEFAULT_SYMBOLS: list[str] = [
    "600519.SH", "000001.SZ", "300750.SZ", "000858.SZ",
    "601318.SH", "600036.SH", "601166.SH", "000333.SZ",
]


@dataclass(frozen=True)
class WatchlistItem:
    item_id: str
    account_id: str
    symbol: str
    note: str
    sort_order: int
    created_at: datetime
    updated_at: datetime


class WatchlistService:
    """Per-account watchlist management."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._audit = AuditLogRepository(session)

    def _audit_log(self, op: str, account_id: str, details: dict) -> None:
        self._audit.save(AuditLog(
            log_id=str(uuid.uuid4()),
            action=AuditAction.WATCHLIST_CHANGED.value,
            actor=account_id,
            resource_type="watchlist",
            resource_id=details.get("symbol", "-"),
            details={"op": op, **details},
            created_at=datetime.now(),
        ))

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def list_items(self, account_id: str) -> list[WatchlistItem]:
        rows = self._session.execute(
            select(WatchlistORM)
            .where(WatchlistORM.account_id == account_id)
            .order_by(WatchlistORM.sort_order, WatchlistORM.created_at)
        ).scalars().all()
        return [self._to_dto(r) for r in rows]

    def list_symbols(self, account_id: str) -> list[str]:
        """Return only the symbol strings, with a fallback to DEFAULT_SYMBOLS
        when the account has no entries yet."""
        items = self.list_items(account_id)
        if items:
            return [it.symbol for it in items]
        return list(DEFAULT_SYMBOLS)

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def add(self, account_id: str, symbol: str, note: str = "", sort_order: int = 0) -> WatchlistItem:
        symbol = symbol.strip().upper()
        if not symbol:
            raise ValueError("symbol 不能为空")

        # Idempotent — same (account, symbol) returns the existing entry
        existing = self._session.execute(
            select(WatchlistORM).where(
                WatchlistORM.account_id == account_id,
                WatchlistORM.symbol == symbol,
            )
        ).scalar_one_or_none()
        now = datetime.now()
        if existing is not None:
            existing.note = note
            existing.sort_order = sort_order
            existing.updated_at = now
            self._session.flush()
            return self._to_dto(existing)

        row = WatchlistORM(
            item_id=str(uuid.uuid4()),
            account_id=account_id,
            symbol=symbol,
            note=note,
            sort_order=sort_order,
            created_at=now,
            updated_at=now,
        )
        self._session.add(row)
        self._session.flush()
        self._audit_log("add", account_id, {"symbol": symbol, "note": note})
        return self._to_dto(row)

    def remove(self, account_id: str, symbol: str) -> bool:
        symbol = symbol.strip().upper()
        result = self._session.execute(
            delete(WatchlistORM).where(
                WatchlistORM.account_id == account_id,
                WatchlistORM.symbol == symbol,
            )
        )
        ok = (result.rowcount or 0) > 0
        if ok:
            self._audit_log("remove", account_id, {"symbol": symbol})
        return ok

    def reorder(self, account_id: str, ordered_symbols: list[str]) -> int:
        """Bulk update sort_order according to position in the list."""
        updated = 0
        now = datetime.now()
        for idx, sym in enumerate(ordered_symbols):
            row = self._session.execute(
                select(WatchlistORM).where(
                    WatchlistORM.account_id == account_id,
                    WatchlistORM.symbol == sym.strip().upper(),
                )
            ).scalar_one_or_none()
            if row:
                row.sort_order = idx
                row.updated_at = now
                updated += 1
        self._session.flush()
        if updated > 0:
            self._audit_log("reorder", account_id, {"count": updated, "order": ordered_symbols})
        return updated

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _to_dto(self, r: WatchlistORM) -> WatchlistItem:
        return WatchlistItem(
            item_id=r.item_id,
            account_id=r.account_id,
            symbol=r.symbol,
            note=r.note,
            sort_order=r.sort_order,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
