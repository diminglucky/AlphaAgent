"""Structured JSON logging per design doc §7.1.1.

Required fields (when present):
- timestamp (ISO-8601, UTC)
- service (configurable, default "quant-api")
- level
- logger
- message
- request_id (from contextvar, set by RequestIdMiddleware)
- symbol / account_id / model_version / data_source / decision_type
  (passed via `logger.info("...", extra={"symbol": "600519.SH"})`)

Usage:
    from libs.infra.structured_logging import setup_logging, request_id_var
    setup_logging(level="INFO", service="quant-api")

    # In middleware:
    request_id_var.set(request_id)

    # In any code:
    log = logging.getLogger("quant.something")
    log.info("decision made", extra={"symbol": "600519.SH",
                                     "decision_type": "BUY",
                                     "model_version": "v1.2"})
"""

from __future__ import annotations

import json
import logging
import os
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

# Per-request context variables — middleware writes these so log records get them automatically
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
account_id_var: ContextVar[str | None] = ContextVar("account_id", default=None)


# Fields recognised by the design doc §7.1.1
_KNOWN_EXTRA_FIELDS = (
    "symbol",
    "account_id",
    "model_version",
    "data_source",
    "decision_type",
    "feature_set_version",
    "duration_ms",
    "status",
    "broker_order_id",
)


class JsonFormatter(logging.Formatter):
    """Format log records as JSON objects with design-doc-mandated fields."""

    def __init__(self, service: str = "quant-api") -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "service": self.service,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Pull request_id / account_id from contextvars
        rid = request_id_var.get()
        if rid:
            payload["request_id"] = rid

        # Account id — extra wins over contextvar
        if not getattr(record, "account_id", None):
            ctx_account = account_id_var.get()
            if ctx_account:
                payload["account_id"] = ctx_account

        # Pull recognised extras off the record
        for field in _KNOWN_EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value

        # Exception info
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(
    level: str | int = "INFO",
    service: str = "quant-api",
    *,
    force: bool = False,
    structured: bool | None = None,
) -> None:
    """Install JSON formatter on the root logger.

    Args:
        level: log level (string or int).
        service: service name to embed in every record.
        force: if True, replace any existing handlers.
        structured: if False, fall back to plain text (useful in tests).
                    If None, env var QUANT_LOG_FORMAT=text disables JSON.
    """
    if structured is None:
        structured = os.getenv("QUANT_LOG_FORMAT", "json").lower() != "text"

    root = logging.getLogger()

    if root.handlers and not force:
        # Only set level if already configured (e.g. by pytest).
        root.setLevel(level)
        return

    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    if structured:
        handler.setFormatter(JsonFormatter(service=service))
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
    root.addHandler(handler)
    root.setLevel(level)
