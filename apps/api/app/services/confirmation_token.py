"""Manual order confirmation tokens (§5.5.4).

Issues short-lived HMAC tokens binding (symbol, side, qty, price). The trader
must submit such a token in `confirmation_token` for live order placement
when `QUANT_REQUIRE_ORDER_CONFIRMATION=true`.

Tokens are kept in-process and expire after `TTL_SECONDS`. This is good
enough for single-instance deployment; for multi-worker, switch to Redis.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
import uuid
from dataclasses import dataclass

_SECRET = os.getenv("QUANT_CONFIRMATION_SECRET", "dev-confirmation-secret-change-me")
TTL_SECONDS = 90  # token must be used within 1.5 minutes


@dataclass(frozen=True)
class _Issued:
    token: str
    payload_digest: str
    issued_at: float


# In-memory store
_store: dict[str, _Issued] = {}


def _digest(symbol: str, side: str, quantity: int, price: float) -> str:
    msg = f"{symbol}|{side.upper()}|{quantity}|{price:.4f}".encode()
    return hmac.new(_SECRET.encode(), msg, hashlib.sha256).hexdigest()[:24]


def issue_token(symbol: str, side: str, quantity: int, price: float) -> dict:
    """Generate a confirmation token bound to the order parameters."""
    digest = _digest(symbol, side, quantity, price)
    token = uuid.uuid4().hex
    _store[token] = _Issued(token=token, payload_digest=digest, issued_at=time.time())
    _evict_expired()
    return {
        "confirmation_token": token,
        "expires_in": TTL_SECONDS,
        "bound_to": {
            "symbol": symbol,
            "side": side.upper(),
            "quantity": quantity,
            "price": price,
        },
    }


def consume_token(
    token: str | None,
    symbol: str,
    side: str,
    quantity: int,
    price: float,
) -> tuple[bool, str]:
    """Validate + invalidate the token. Returns (ok, reason)."""
    if not token:
        return False, "缺少 confirmation_token"
    issued = _store.pop(token, None)
    if issued is None:
        return False, "confirmation_token 无效或已使用"
    if time.time() - issued.issued_at > TTL_SECONDS:
        return False, "confirmation_token 已过期"
    if issued.payload_digest != _digest(symbol, side, quantity, price):
        return False, "confirmation_token 与订单参数不匹配"
    return True, "ok"


def _evict_expired() -> None:
    now = time.time()
    expired = [k for k, v in _store.items() if now - v.issued_at > TTL_SECONDS]
    for k in expired:
        _store.pop(k, None)
