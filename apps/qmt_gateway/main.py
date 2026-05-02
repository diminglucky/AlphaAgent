"""QMT Gateway HTTP service.

Run on a Windows host (or anywhere with `QMT_BACKEND=mock`) and the trading
platform talks to it over HTTP. See docs/qmt-integration.md.

    python -m apps.qmt_gateway.main --port 8788

Env:
    QMT_BACKEND=auto|mock|xtquant   # auto picks xtquant on Windows
    QMT_GATEWAY_API_KEY=...         # optional; clients must send X-API-Key
"""

from __future__ import annotations

import argparse
import os
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Header, status
from pydantic import BaseModel, Field

from apps.qmt_gateway.backends import PlaceOrder, build_backend


app = FastAPI(title="Quant QMT Gateway", version="1.0")
_backend = None


def get_backend():
    global _backend
    if _backend is None:
        _backend = build_backend()
    return _backend


def _check_api_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    expected = os.getenv("QMT_GATEWAY_API_KEY", "").strip()
    if not expected:
        return
    if x_api_key != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid X-API-Key")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class PlaceOrderReq(BaseModel):
    symbol: str
    side: str = Field(..., pattern="^(BUY|SELL)$")
    quantity: int = Field(..., gt=0)
    order_type: str = Field(..., pattern="^(LIMIT|MARKET)$")
    price: Optional[float] = None
    client_order_id: Optional[str] = None


class SimulateFillReq(BaseModel):
    fill_price: float = Field(..., gt=0)
    fill_quantity: Optional[int] = Field(None, gt=0)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
def health(_: None = Depends(_check_api_key)) -> dict:
    return get_backend().health()


@app.post("/orders", status_code=201)
def place_order(req: PlaceOrderReq, _: None = Depends(_check_api_key)) -> dict:
    order = get_backend().place_order(PlaceOrder(
        symbol=req.symbol, side=req.side, quantity=req.quantity,
        order_type=req.order_type, price=req.price,
        client_order_id=req.client_order_id,
    ))
    return order.to_dict()


@app.get("/orders")
def list_orders(limit: int = 100, _: None = Depends(_check_api_key)) -> list[dict]:
    backend = get_backend()
    if hasattr(backend, "list_orders"):
        return [o.to_dict() for o in backend.list_orders(limit=limit)]
    return []


@app.get("/orders/{order_id}")
def get_order(order_id: str, _: None = Depends(_check_api_key)) -> dict:
    try:
        return get_backend().get_order(order_id).to_dict()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/orders/{order_id}/cancel")
def cancel_order(order_id: str, _: None = Depends(_check_api_key)) -> dict:
    try:
        return get_backend().cancel_order(order_id).to_dict()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/orders/{order_id}/simulate_fill")
def simulate_fill(
    order_id: str, req: SimulateFillReq, _: None = Depends(_check_api_key)
) -> dict:
    """Mock-only endpoint: force-fill a pending order. Useful for tests."""
    backend = get_backend()
    if not hasattr(backend, "simulate_fill"):
        raise HTTPException(status_code=400, detail="Real backend does not support simulate_fill")
    try:
        return backend.simulate_fill(order_id, fill_price=req.fill_price,
                                     fill_qty=req.fill_quantity).to_dict()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/positions")
def list_positions(_: None = Depends(_check_api_key)) -> list[dict]:
    return [p.__dict__ for p in get_backend().list_positions()]


@app.get("/account")
def get_account(_: None = Depends(_check_api_key)) -> dict:
    return get_backend().get_account().__dict__


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8788)
    args = parser.parse_args()

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
