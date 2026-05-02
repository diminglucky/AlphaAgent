"""QMT Gateway backends.

Two implementations:

- `MockBackend` — works on any OS; deterministic in-memory order book. Used
  for development, CI tests, and Linux/Mac dev environments where xtquant
  cannot run.

- `XtQuantBackend` — Windows-only; talks to the local QMT terminal via the
  `xtquant` python package. Activated only when running on Windows AND
  `xtquant` is importable AND `QMT_BACKEND=xtquant` is set.

The Gateway picks a backend at startup. Both expose the same interface:

    backend.health() -> dict
    backend.place_order(req: PlaceOrder) -> Order
    backend.cancel_order(order_id: str) -> Order
    backend.get_order(order_id: str) -> Order
    backend.list_positions() -> list[Position]
    backend.get_account() -> Account
"""

from __future__ import annotations

import json
import os
import pathlib
import platform
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional


def _utc_now_iso() -> str:
    """timezone-aware UTC ISO without offset — drop-in replacement for utcnow().isoformat()."""
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


# ---------------------------------------------------------------------------
# Common DTOs
# ---------------------------------------------------------------------------

@dataclass
class PlaceOrder:
    symbol: str
    side: str        # BUY / SELL
    quantity: int
    order_type: str  # LIMIT / MARKET
    price: Optional[float] = None
    client_order_id: Optional[str] = None


@dataclass
class Order:
    order_id: str
    client_order_id: Optional[str]
    symbol: str
    side: str
    order_type: str
    quantity: int
    price: Optional[float]
    status: str          # ACCEPTED / PARTIAL / FILLED / CANCELLED / REJECTED
    filled_quantity: int = 0
    avg_fill_price: float = 0.0
    submitted_at: str = ""
    updated_at: str = ""
    error_message: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Position:
    symbol: str
    quantity: int
    available_quantity: int  # T+1 constrained portion
    avg_cost: float
    market_value: float


@dataclass
class Account:
    account_id: str
    total_asset: float
    cash: float
    market_value: float
    available_cash: float


# ---------------------------------------------------------------------------
# Mock backend
# ---------------------------------------------------------------------------

class MockBackend:
    """Deterministic backend for non-Windows / dev / CI.

    Optional JSON-file persistence: set ``QMT_MOCK_STATE_FILE=/path/to/state.json``
    (or pass ``state_file=`` directly) to make orders / positions / cash
    survive process restarts — turning this into a real paper-trading
    account that can be driven via the gateway HTTP API.
    """

    name = "mock"

    def __init__(
        self,
        initial_cash: float = 1_000_000.0,
        state_file: Optional[str] = None,
    ) -> None:
        self._lock = threading.Lock()
        self._orders: dict[str, Order] = {}
        self._positions: dict[str, Position] = {}
        self._cash = initial_cash
        self._initial_cash = initial_cash
        self._account_id = "MOCK_001"
        self._state_path: Optional[pathlib.Path] = None
        sf = state_file or os.getenv("QMT_MOCK_STATE_FILE", "").strip()
        if sf:
            self._state_path = pathlib.Path(sf)
            self._load_state()

    # -- persistence ---------------------------------------------------

    def _load_state(self) -> None:
        if not self._state_path or not self._state_path.exists():
            return
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — corrupted file, start fresh
            return
        self._cash = float(data.get("cash", self._initial_cash))
        self._initial_cash = float(data.get("initial_cash", self._initial_cash))
        self._account_id = data.get("account_id", self._account_id)
        for d in data.get("orders", []):
            self._orders[d["order_id"]] = Order(**d)
        for d in data.get("positions", []):
            self._positions[d["symbol"]] = Position(**d)

    def _save_state(self) -> None:
        if not self._state_path:
            return
        payload = {
            "account_id": self._account_id,
            "cash": self._cash,
            "initial_cash": self._initial_cash,
            "orders": [asdict(o) for o in self._orders.values()],
            "positions": [asdict(p) for p in self._positions.values()],
            "saved_at": _utc_now_iso(),
        }
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._state_path.with_suffix(self._state_path.suffix + ".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self._state_path)
        except Exception as exc:  # noqa: BLE001
            print(f"[qmt_gateway] WARN: failed to persist state: {exc}", file=sys.stderr)

    # -- introspection --------------------------------------------------

    def health(self) -> dict:
        return {
            "status": "ok",
            "backend": self.name,
            "platform": platform.system(),
            "uptime_orders": len(self._orders),
            "logged_in": True,
        }

    # -- orders ---------------------------------------------------------

    def place_order(self, req: PlaceOrder) -> Order:
        with self._lock:
            now = _utc_now_iso()
            order_id = f"MOCK-{uuid.uuid4().hex[:10]}"

            # Basic sanity
            if req.quantity <= 0 or req.quantity % 100 != 0:
                return self._reject(order_id, req, now, "Quantity must be positive multiple of 100")
            if req.side not in ("BUY", "SELL"):
                return self._reject(order_id, req, now, f"Invalid side: {req.side}")
            if req.order_type == "LIMIT" and not req.price:
                return self._reject(order_id, req, now, "LIMIT order requires price")

            price = req.price if req.order_type == "LIMIT" else 0.0

            # Cash check on BUY
            if req.side == "BUY":
                est_cost = (price or 0) * req.quantity
                if est_cost > self._cash:
                    return self._reject(order_id, req, now,
                                        f"Insufficient cash: need {est_cost:.2f}, have {self._cash:.2f}")
            else:  # SELL
                pos = self._positions.get(req.symbol)
                if not pos or pos.available_quantity < req.quantity:
                    avail = pos.available_quantity if pos else 0
                    return self._reject(order_id, req, now,
                                        f"Insufficient available position: need {req.quantity}, have {avail}")

            order = Order(
                order_id=order_id,
                client_order_id=req.client_order_id,
                symbol=req.symbol, side=req.side, order_type=req.order_type,
                quantity=req.quantity, price=price,
                status="ACCEPTED", submitted_at=now, updated_at=now,
            )
            self._orders[order_id] = order

            # Auto-fill MARKET orders immediately at last LIMIT price or default
            if req.order_type == "MARKET":
                self._auto_fill(order, fill_price=price or self._last_known_price(req.symbol))

            self._save_state()
            return order

    def _reject(self, order_id: str, req: PlaceOrder, now: str, reason: str) -> Order:
        order = Order(
            order_id=order_id, client_order_id=req.client_order_id,
            symbol=req.symbol, side=req.side, order_type=req.order_type,
            quantity=req.quantity, price=req.price,
            status="REJECTED", submitted_at=now, updated_at=now,
            error_message=reason,
        )
        self._orders[order_id] = order
        self._save_state()
        return order

    def cancel_order(self, order_id: str) -> Order:
        with self._lock:
            order = self._orders.get(order_id)
            if not order:
                raise KeyError(f"Unknown order_id: {order_id}")
            if order.status in ("FILLED", "CANCELLED", "REJECTED"):
                return order
            order.status = "CANCELLED"
            order.updated_at = _utc_now_iso()
            self._save_state()
            return order

    def get_order(self, order_id: str) -> Order:
        with self._lock:
            order = self._orders.get(order_id)
            if not order:
                raise KeyError(f"Unknown order_id: {order_id}")
            return order

    def list_orders(self, limit: int = 100) -> list[Order]:
        with self._lock:
            return sorted(self._orders.values(),
                          key=lambda o: o.submitted_at, reverse=True)[:limit]

    # -- positions / account -------------------------------------------

    def list_positions(self) -> list[Position]:
        with self._lock:
            return list(self._positions.values())

    def get_account(self) -> Account:
        with self._lock:
            mv = sum(p.market_value for p in self._positions.values())
            return Account(
                account_id=self._account_id,
                total_asset=self._cash + mv,
                cash=self._cash,
                market_value=mv,
                available_cash=self._cash,
            )

    # -- helper --------------------------------------------------------

    def simulate_fill(self, order_id: str, fill_price: float, fill_qty: Optional[int] = None) -> Order:
        """Force-fill a LIMIT order — convenience for testing."""
        with self._lock:
            order = self._orders[order_id]
            if order.status not in ("ACCEPTED", "PARTIAL"):
                raise ValueError(f"Order {order_id} not fillable in status {order.status}")
            self._auto_fill(order, fill_price=fill_price, fill_qty=fill_qty)
            self._save_state()
            return order

    def _auto_fill(self, order: Order, fill_price: float, fill_qty: Optional[int] = None) -> None:
        """Apply a fill (full or partial) to the order and update positions/cash."""
        qty = fill_qty if fill_qty is not None else (order.quantity - order.filled_quantity)
        qty = min(qty, order.quantity - order.filled_quantity)
        if qty <= 0:
            return

        notional = fill_price * qty
        if order.side == "BUY":
            self._cash -= notional
            pos = self._positions.get(order.symbol)
            if pos:
                new_qty = pos.quantity + qty
                new_cost = (pos.quantity * pos.avg_cost + notional) / new_qty
                pos.quantity = new_qty
                pos.avg_cost = new_cost
                pos.market_value = new_qty * fill_price
                # T+1: today-bought stays unavailable until next session;
                # we don't simulate sessions here, but we add to available
                # to simplify Mock — gateway docs note this limitation.
                pos.available_quantity = pos.quantity
            else:
                self._positions[order.symbol] = Position(
                    symbol=order.symbol, quantity=qty,
                    available_quantity=qty,
                    avg_cost=fill_price,
                    market_value=qty * fill_price,
                )
        else:  # SELL
            pos = self._positions[order.symbol]
            pos.quantity -= qty
            pos.available_quantity = max(0, pos.available_quantity - qty)
            pos.market_value = pos.quantity * fill_price
            self._cash += notional
            if pos.quantity == 0:
                self._positions.pop(order.symbol, None)

        # Update order
        prev_qty = order.filled_quantity
        new_filled = prev_qty + qty
        order.avg_fill_price = (
            (prev_qty * order.avg_fill_price + notional) / new_filled if new_filled else 0
        )
        order.filled_quantity = new_filled
        order.status = "FILLED" if new_filled >= order.quantity else "PARTIAL"
        order.updated_at = _utc_now_iso()

    def _last_known_price(self, symbol: str) -> float:
        # Mock fallback: use position avg_cost or 100.0
        pos = self._positions.get(symbol)
        return pos.avg_cost if pos else 100.0


# ---------------------------------------------------------------------------
# XtQuant backend (Windows only) — placeholder stub
# ---------------------------------------------------------------------------

class XtQuantBackend:
    """Real backend wrapping `xtquant`. Stubbed; finish on a Windows host.

    On Windows with QMT installed, fill in the `_xt` calls per the official
    xtquant API (https://dict.thinktrader.net/innerApi/xtquant.html).
    """

    name = "xtquant"

    def __init__(self) -> None:
        if platform.system() != "Windows":
            raise RuntimeError("XtQuantBackend requires Windows + QMT terminal")
        try:
            from xtquant import xttrader, xtdata  # type: ignore  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(f"xtquant not importable: {exc}")
        # TODO(windows): initialise xttrader session, cache client
        self._inited = False

    def health(self) -> dict:
        return {"status": "ok", "backend": self.name, "logged_in": self._inited}

    def place_order(self, req: PlaceOrder) -> Order:
        raise NotImplementedError("Implement on Windows host with xtquant")

    def cancel_order(self, order_id: str) -> Order:
        raise NotImplementedError

    def get_order(self, order_id: str) -> Order:
        raise NotImplementedError

    def list_positions(self) -> list[Position]:
        raise NotImplementedError

    def get_account(self) -> Account:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def build_backend():
    """Pick a backend based on env + platform."""
    requested = os.getenv("QMT_BACKEND", "auto").lower()
    is_windows = platform.system() == "Windows"

    if requested == "mock":
        return MockBackend()
    if requested == "xtquant":
        return XtQuantBackend()
    # auto
    if is_windows:
        try:
            return XtQuantBackend()
        except Exception as exc:  # noqa: BLE001
            print(f"[qmt_gateway] xtquant unavailable ({exc}); using mock", file=sys.stderr)
            return MockBackend()
    return MockBackend()
