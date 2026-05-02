"""HTTP client to talk to the QMT Gateway (Design Doc §5.5).

The platform calls this whenever `QUANT_LIVE_TRADE_ENABLED=true` and a
`QUANT_QMT_GATEWAY_URL` is set. All risk control lives on the platform side;
this client only translates already-approved orders to gateway calls.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

import httpx

log = logging.getLogger("quant.qmt")


class QMTClientError(RuntimeError):
    pass


class QMTClientUnavailable(QMTClientError):
    """Raised when the gateway is unreachable / disabled."""


@dataclass
class QMTConfig:
    url: str
    api_key: str = ""
    timeout: float = 5.0
    enabled: bool = False


def load_qmt_config() -> QMTConfig:
    return QMTConfig(
        url=os.getenv("QUANT_QMT_GATEWAY_URL", "").rstrip("/"),
        api_key=os.getenv("QUANT_QMT_API_KEY", ""),
        timeout=float(os.getenv("QUANT_QMT_TIMEOUT", "5")),
        enabled=os.getenv("QUANT_LIVE_TRADE_ENABLED", "false").lower() in ("1", "true", "yes"),
    )


class QMTClient:
    """Thin wrapper over httpx; raises QMTClientUnavailable on connection issues."""

    def __init__(self, cfg: Optional[QMTConfig] = None) -> None:
        self.cfg = cfg or load_qmt_config()

    # -- predicates ----------------------------------------------------

    def is_configured(self) -> bool:
        return bool(self.cfg.url) and self.cfg.enabled

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.cfg.api_key:
            h["X-API-Key"] = self.cfg.api_key
        return h

    def _request(self, method: str, path: str, **kw) -> dict:
        if not self.cfg.url:
            raise QMTClientUnavailable("QMT gateway URL not configured")
        url = f"{self.cfg.url}{path}"
        try:
            r = httpx.request(method, url, headers=self._headers(),
                              timeout=self.cfg.timeout, **kw)
        except httpx.HTTPError as exc:
            raise QMTClientUnavailable(f"gateway connection failed: {exc}") from exc
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail", r.text)
            except Exception:  # noqa: BLE001
                detail = r.text
            raise QMTClientError(f"gateway {r.status_code}: {detail}")
        return r.json() if r.text else {}

    # -- ops -----------------------------------------------------------

    def health(self) -> dict:
        return self._request("GET", "/health")

    def place_order(
        self,
        symbol: str, side: str, quantity: int, order_type: str,
        price: Optional[float] = None, client_order_id: Optional[str] = None,
    ) -> dict:
        return self._request("POST", "/orders", json={
            "symbol": symbol, "side": side, "quantity": quantity,
            "order_type": order_type, "price": price,
            "client_order_id": client_order_id,
        })

    def cancel_order(self, order_id: str) -> dict:
        return self._request("POST", f"/orders/{order_id}/cancel")

    def get_order(self, order_id: str) -> dict:
        return self._request("GET", f"/orders/{order_id}")

    def list_positions(self) -> list[dict]:
        return self._request("GET", "/positions")  # type: ignore[return-value]

    def get_account(self) -> dict:
        return self._request("GET", "/account")
