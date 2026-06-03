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
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Optional


def _utc_now_iso() -> str:
    """timezone-aware UTC ISO without offset — drop-in replacement for utcnow().isoformat()."""
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except Exception:
        return default


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(value)
    except Exception:
        try:
            return int(float(value))
        except Exception:
            return default


def _attr(obj: Any, *names: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        for name in names:
            value = obj.get(name)
            if value not in (None, ""):
                return value
        return default
    for name in names:
        if hasattr(obj, name):
            value = getattr(obj, name)
            if value not in (None, ""):
                return value
    return default


def _format_xt_time(value: Any) -> str:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None).isoformat()
    if value in (None, ""):
        return _utc_now_iso()
    text = str(value).strip()
    for fmt in ("%Y%m%d%H%M%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).isoformat()
        except ValueError:
            pass
    try:
        numeric = float(text)
        if numeric > 10_000_000_000:
            numeric /= 1000.0
        if numeric > 1_000_000_000:
            return datetime.fromtimestamp(numeric, tz=timezone.utc).replace(tzinfo=None).isoformat()
    except Exception:
        pass
    return _utc_now_iso()


def _normalize_symbol(symbol: str) -> str:
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
            suffix = prefix
            break
    if code.isdigit():
        code = code.zfill(6)
    return f"{code}.{suffix.upper()}"


def _is_success_code(value: Any) -> bool:
    if value is None or value is True:
        return True
    if value is False:
        return False
    try:
        return int(float(value)) == 0
    except Exception:
        return False


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
    account_id: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Position:
    symbol: str
    quantity: int
    available_quantity: int  # T+1 constrained portion
    avg_cost: float
    market_value: float
    name: str = ""


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
# XtQuant backend (Windows only)
# ---------------------------------------------------------------------------

class XtQuantBackend:
    """Real backend wrapping ``xtquant``.

    The constructor accepts injected ``trader`` / ``account`` objects so tests
    can exercise the adapter on non-Windows hosts. Production startup still
    requires Windows, a logged-in QMT terminal, ``xtquant`` importability, and
    explicit account/user-path env configuration.
    """

    name = "xtquant"

    def __init__(
        self,
        *,
        trader: Any | None = None,
        account: Any | None = None,
        xtconstant: Any | None = None,
        xtdata: Any | None = None,
        platform_name: str | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._trader = trader
        self._account = account
        self._xtconstant = xtconstant
        self._xtdata = xtdata
        self._strategy_name = os.getenv("QMT_XT_STRATEGY_NAME", "AlphaAgent")
        self._account_id = str(_attr(account, "account_id", "account", "id", default=os.getenv("QMT_XT_ACCOUNT_ID", "QMT")))
        self._inited = False

        if self._trader is not None and self._account is not None and self._xtconstant is not None:
            self._inited = True
            return

        current_platform = platform_name or platform.system()
        if current_platform != "Windows":
            raise RuntimeError("XtQuantBackend requires Windows + QMT terminal")
        try:
            from xtquant import xtconstant, xtdata  # type: ignore
            from xtquant.xttrader import XtQuantTrader  # type: ignore
            from xtquant.xttype import StockAccount  # type: ignore
        except ImportError as exc:
            raise RuntimeError(f"xtquant not importable: {exc}")

        user_path = os.getenv("QMT_XT_USER_PATH", "").strip()
        account_id = os.getenv("QMT_XT_ACCOUNT_ID", "").strip()
        account_type = os.getenv("QMT_XT_ACCOUNT_TYPE", "STOCK").strip() or "STOCK"
        if not user_path:
            raise RuntimeError("QMT_XT_USER_PATH is required for XtQuantBackend")
        if not account_id:
            raise RuntimeError("QMT_XT_ACCOUNT_ID is required for XtQuantBackend")

        session_id = _coerce_int(
            os.getenv("QMT_XT_SESSION_ID"),
            int(time.time() * 1000) % 2_000_000_000,
        )
        self._trader = XtQuantTrader(user_path, session_id)
        try:
            self._account = StockAccount(account_id, account_type)
        except TypeError:
            self._account = StockAccount(account_id)
        self._account_id = account_id
        self._xtconstant = xtconstant
        self._xtdata = xtdata

        self._trader.start()
        connect_result = self._trader.connect()
        if not _is_success_code(connect_result):
            raise RuntimeError(f"xtquant connect failed: {connect_result}")
        subscribe_result = self._trader.subscribe(self._account)
        if not _is_success_code(subscribe_result):
            raise RuntimeError(f"xtquant subscribe failed: {subscribe_result}")
        self._inited = True

    def health(self) -> dict:
        logged_in = self._inited
        payload = {
            "status": "ok" if logged_in else "degraded",
            "backend": self.name,
            "platform": platform.system(),
            "logged_in": logged_in,
            "account_id": self._account_id,
        }
        if self._inited:
            try:
                account = self.get_account()
                payload.update({
                    "cash": account.cash,
                    "available_cash": account.available_cash,
                    "total_asset": account.total_asset,
                })
            except Exception as exc:  # noqa: BLE001
                payload.update({"status": "degraded", "logged_in": False, "error": str(exc)})
        return payload

    def place_order(self, req: PlaceOrder) -> Order:
        with self._lock:
            now = _utc_now_iso()
            fallback_order_id = f"QMT-{uuid.uuid4().hex[:10]}"
            if req.quantity <= 0 or req.quantity % 100 != 0:
                return self._reject(fallback_order_id, req, now, "Quantity must be positive multiple of 100")
            if req.side not in ("BUY", "SELL"):
                return self._reject(fallback_order_id, req, now, f"Invalid side: {req.side}")
            if req.order_type not in ("LIMIT", "MARKET"):
                return self._reject(fallback_order_id, req, now, f"Invalid order_type: {req.order_type}")
            if req.order_type == "LIMIT" and not req.price:
                return self._reject(fallback_order_id, req, now, "LIMIT order requires price")

            try:
                side_const = self._side_const(req.side)
                price_type = self._price_type_const(req.order_type, req.symbol)
                price = float(req.price or 0.0)
                remark = req.client_order_id or fallback_order_id
                raw_order_id = self._trader.order_stock(
                    self._account,
                    _normalize_symbol(req.symbol),
                    side_const,
                    int(req.quantity),
                    price_type,
                    price,
                    self._strategy_name,
                    remark,
                )
            except Exception as exc:  # noqa: BLE001
                return self._reject(fallback_order_id, req, now, f"xtquant order_stock failed: {exc}")

            if raw_order_id in (None, "") or (_coerce_int(raw_order_id, 1) <= 0 and str(raw_order_id).lstrip("-").isdigit()):
                return self._reject(fallback_order_id, req, now, f"xtquant order_stock rejected: {raw_order_id}")

            order_id = str(raw_order_id)
            try:
                order = self.get_order(order_id)
                if order.client_order_id in (None, ""):
                    order.client_order_id = req.client_order_id
                return order
            except KeyError:
                return Order(
                    order_id=order_id,
                    client_order_id=req.client_order_id,
                    symbol=_normalize_symbol(req.symbol),
                    side=req.side,
                    order_type=req.order_type,
                    quantity=req.quantity,
                    price=price if req.order_type == "LIMIT" else None,
                    status="ACCEPTED",
                    submitted_at=now,
                    updated_at=now,
                    account_id=self._account_id,
                )

    def cancel_order(self, order_id: str) -> Order:
        with self._lock:
            try:
                result = self._trader.cancel_order_stock(self._account, order_id)
            except TypeError:
                result = self._trader.cancel_order_stock(self._account, _coerce_int(order_id))
            except Exception as exc:  # noqa: BLE001
                raise KeyError(f"Cancel failed for {order_id}: {exc}") from exc
            if _coerce_int(result, 0) < 0:
                raise KeyError(f"Cancel failed for {order_id}: {result}")

            try:
                return self.get_order(order_id)
            except KeyError:
                now = _utc_now_iso()
                return Order(
                    order_id=str(order_id),
                    client_order_id=None,
                    symbol="",
                    side="",
                    order_type="",
                    quantity=0,
                    price=None,
                    status="CANCELLED",
                    submitted_at=now,
                    updated_at=now,
                    account_id=self._account_id,
                )

    def get_order(self, order_id: str) -> Order:
        target = str(order_id)
        for order in self.list_orders(limit=500):
            if str(order.order_id) == target:
                return order
        raise KeyError(f"Unknown order_id: {order_id}")

    def list_orders(self, limit: int = 100) -> list[Order]:
        orders = self._query_stock_orders()
        mapped = [self._map_order(o) for o in orders]
        return sorted(mapped, key=lambda o: o.submitted_at, reverse=True)[:limit]

    def list_positions(self) -> list[Position]:
        try:
            rows = self._trader.query_stock_positions(self._account)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"xtquant query_stock_positions failed: {exc}") from exc
        if rows is None:
            raise RuntimeError("xtquant query_stock_positions returned None")
        return [self._map_position(row) for row in (rows or [])]

    def get_account(self) -> Account:
        try:
            asset = self._trader.query_stock_asset(self._account)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"xtquant query_stock_asset failed: {exc}") from exc
        if asset is None:
            raise RuntimeError("xtquant query_stock_asset returned None")
        account_id = str(_attr(asset, "account_id", "account", "id", default=self._account_id))
        cash = _coerce_float(_attr(asset, "cash", "cash_balance", "available_cash", "enable_balance"))
        available_cash = _coerce_float(_attr(asset, "available_cash", "enable_balance"), cash)
        market_value = _coerce_float(_attr(asset, "market_value", "stock_value", "securities_value"))
        total_asset = _coerce_float(_attr(asset, "total_asset", "asset", "total_value"), cash + market_value)
        return Account(
            account_id=account_id,
            total_asset=total_asset,
            cash=cash,
            market_value=market_value,
            available_cash=available_cash,
        )

    # -- xtquant mapping helpers --------------------------------------

    def _reject(self, order_id: str, req: PlaceOrder, now: str, reason: str) -> Order:
        return Order(
            order_id=order_id,
            client_order_id=req.client_order_id,
            symbol=_normalize_symbol(req.symbol),
            side=req.side,
            order_type=req.order_type,
            quantity=req.quantity,
            price=req.price,
            status="REJECTED",
            submitted_at=now,
            updated_at=now,
            error_message=reason,
            account_id=self._account_id,
        )

    def _required_const(self, *names: str) -> Any:
        for name in names:
            if isinstance(name, str) and name.strip().lstrip("-").isdigit():
                return int(name)
            if self._xtconstant is not None and hasattr(self._xtconstant, name):
                return getattr(self._xtconstant, name)
        raise RuntimeError(f"xtconstant missing one of: {', '.join(names)}")

    def _side_const(self, side: str) -> Any:
        return self._required_const("STOCK_BUY" if side == "BUY" else "STOCK_SELL")

    def _price_type_const(self, order_type: str, symbol: str) -> Any:
        if order_type == "LIMIT":
            return self._required_const("FIX_PRICE")
        suffix = _normalize_symbol(symbol).split(".")[-1]
        override = os.getenv(f"QMT_XT_MARKET_PRICE_TYPE_{suffix}", "").strip()
        if override:
            return self._required_const(override)
        if suffix == "SH":
            return self._required_const(
                "MARKET_SH_CONVERT_5_CANCEL",
                "MARKET_SH_OPTIMAL_5_CANCEL",
                "MARKET_PEER_PRICE_FIRST",
            )
        if suffix == "SZ":
            return self._required_const(
                "MARKET_SZ_CONVERT_5_CANCEL",
                "MARKET_SZ_INSTBUSI_RESTCANCEL",
                "MARKET_PEER_PRICE_FIRST",
            )
        return self._required_const("MARKET_PEER_PRICE_FIRST")

    def _query_stock_orders(self) -> list[Any]:
        try:
            rows = self._trader.query_stock_orders(self._account)
        except TypeError:
            rows = self._trader.query_stock_orders(self._account, False)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"xtquant query_stock_orders failed: {exc}") from exc
        if rows is None:
            raise RuntimeError("xtquant query_stock_orders returned None")
        return list(rows or [])

    def _map_order(self, raw: Any) -> Order:
        raw_order_id = _attr(raw, "order_id", "order_sysid", "entrust_no", "order_no", "seq", default="")
        order_id = str(raw_order_id or "")
        side = self._side_from_xt(_attr(raw, "order_type", "entrust_bs", "side", default=""))
        price_type = _attr(raw, "price_type", "order_price_type", default=None)
        price = _coerce_float(_attr(raw, "price", "order_price", "entrust_price"), 0.0)
        order_type = "LIMIT" if price_type == self._const_or_none("FIX_PRICE") or price > 0 else "MARKET"
        quantity = _coerce_int(_attr(raw, "order_volume", "volume", "quantity", "entrust_amount"))
        filled_quantity = _coerce_int(_attr(raw, "traded_volume", "deal_volume", "filled_quantity", "business_amount"))
        avg_fill_price = _coerce_float(_attr(raw, "traded_price", "avg_traded_price", "deal_price", "avg_fill_price"))
        status_msg = str(_attr(raw, "status_msg", "error_msg", "error_message", default="") or "")
        status = self._status_from_xt(
            _attr(raw, "order_status", "status", "entrust_status", default=""),
            filled_quantity=filled_quantity,
            quantity=quantity,
            error_message=status_msg,
        )
        submitted_at = _format_xt_time(_attr(raw, "order_time", "entrust_time", "submitted_at", default=None))
        return Order(
            order_id=order_id,
            client_order_id=str(_attr(raw, "order_remark", "remark", "client_order_id", default="") or ""),
            symbol=_normalize_symbol(str(_attr(raw, "stock_code", "symbol", "code", default="") or "")),
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price if order_type == "LIMIT" else None,
            status=status,
            filled_quantity=filled_quantity,
            avg_fill_price=avg_fill_price,
            submitted_at=submitted_at,
            updated_at=_format_xt_time(_attr(raw, "updated_at", "update_time", "order_time", default=None)),
            error_message=status_msg or None,
            account_id=str(_attr(raw, "account_id", "account", default=self._account_id) or self._account_id),
        )

    def _map_position(self, raw: Any) -> Position:
        symbol = _normalize_symbol(str(_attr(raw, "stock_code", "symbol", "code", default="") or ""))
        quantity = _coerce_int(_attr(raw, "volume", "quantity", "current_amount"))
        available = _coerce_int(_attr(raw, "can_use_volume", "available_quantity", "enable_amount"), quantity)
        avg_cost = _coerce_float(_attr(raw, "open_price", "avg_cost", "cost_price", "avg_price"))
        market_value = _coerce_float(_attr(raw, "market_value", "stock_value"), quantity * avg_cost)
        return Position(
            symbol=symbol,
            quantity=quantity,
            available_quantity=available,
            avg_cost=avg_cost,
            market_value=market_value,
            name=str(_attr(raw, "stock_name", "name", default=symbol) or symbol),
        )

    def _const_or_none(self, name: str) -> Any:
        if self._xtconstant is not None and hasattr(self._xtconstant, name):
            return getattr(self._xtconstant, name)
        return None

    def _side_from_xt(self, value: Any) -> str:
        if value == self._const_or_none("STOCK_BUY"):
            return "BUY"
        if value == self._const_or_none("STOCK_SELL"):
            return "SELL"
        text = str(value).upper()
        if "BUY" in text or "买" in text:
            return "BUY"
        if "SELL" in text or "卖" in text:
            return "SELL"
        return text or ""

    def _status_from_xt(
        self,
        value: Any,
        *,
        filled_quantity: int,
        quantity: int,
        error_message: str,
    ) -> str:
        if quantity > 0 and filled_quantity >= quantity:
            return "FILLED"
        if error_message:
            lowered_error = error_message.lower()
            if any(token in lowered_error for token in ("reject", "fail", "error", "废", "错", "拒")):
                return "REJECTED"

        status_map = {
            self._const_or_none("ORDER_SUCCEEDED"): "FILLED",
            self._const_or_none("ORDER_PART_SUCC"): "PARTIAL",
            self._const_or_none("ORDER_PARTSUCC_CANCEL"): "PARTIAL",
            self._const_or_none("ORDER_PART_CANCEL"): "PARTIAL",
            self._const_or_none("ORDER_CANCELED"): "CANCELLED",
            self._const_or_none("ORDER_REPORTED_CANCEL"): "CANCELLED",
            self._const_or_none("ORDER_JUNK"): "REJECTED",
            self._const_or_none("ORDER_REPORTED"): "ACCEPTED",
            self._const_or_none("ORDER_WAIT_REPORTING"): "ACCEPTED",
            self._const_or_none("ORDER_UNREPORTED"): "ACCEPTED",
        }
        if value in status_map and status_map[value]:
            if status_map[value] == "CANCELLED" and filled_quantity > 0:
                return "PARTIAL"
            return status_map[value]

        text = str(value).upper()
        if any(token in text for token in ("REJECT", "JUNK", "FAIL", "废", "错", "拒")):
            return "REJECTED"
        if any(token in text for token in ("CANCEL", "撤")):
            return "PARTIAL" if filled_quantity > 0 else "CANCELLED"
        if any(token in text for token in ("PART", "部")) or filled_quantity > 0:
            return "PARTIAL"
        if any(token in text for token in ("FILLED", "SUCCEEDED", "成交", "已成")):
            return "FILLED"
        return "ACCEPTED"


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
