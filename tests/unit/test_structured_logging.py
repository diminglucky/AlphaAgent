"""Tests for structured JSON logging (Design Doc §7.1.1)."""

from __future__ import annotations

import io
import json
import logging

import pytest

from libs.infra.structured_logging import (
    JsonFormatter,
    request_id_var,
    account_id_var,
    setup_logging,
)


def _format(record: logging.LogRecord, service: str = "quant-api") -> dict:
    return json.loads(JsonFormatter(service=service).format(record))


def _make_record(
    msg: str = "hello",
    level: int = logging.INFO,
    logger_name: str = "quant.test",
    extra: dict | None = None,
) -> logging.LogRecord:
    record = logging.LogRecord(
        name=logger_name, level=level, pathname=__file__, lineno=10,
        msg=msg, args=(), exc_info=None,
    )
    if extra:
        for k, v in extra.items():
            setattr(record, k, v)
    return record


def test_json_formatter_emits_required_fields():
    payload = _format(_make_record())
    for key in ("timestamp", "service", "level", "logger", "message"):
        assert key in payload
    assert payload["service"] == "quant-api"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "quant.test"
    assert payload["message"] == "hello"


def test_json_formatter_includes_request_id_from_contextvar():
    token = request_id_var.set("req-abc-123")
    try:
        payload = _format(_make_record())
        assert payload["request_id"] == "req-abc-123"
    finally:
        request_id_var.reset(token)


def test_json_formatter_omits_request_id_when_unset():
    payload = _format(_make_record())
    assert "request_id" not in payload


def test_json_formatter_includes_account_id_from_contextvar():
    token = account_id_var.set("acct-001")
    try:
        payload = _format(_make_record())
        assert payload["account_id"] == "acct-001"
    finally:
        account_id_var.reset(token)


def test_json_formatter_includes_design_doc_extra_fields():
    record = _make_record(extra={
        "symbol": "600519.SH",
        "decision_type": "BUY",
        "model_version": "v1.2",
        "data_source": "akshare",
    })
    payload = _format(record)
    assert payload["symbol"] == "600519.SH"
    assert payload["decision_type"] == "BUY"
    assert payload["model_version"] == "v1.2"
    assert payload["data_source"] == "akshare"


def test_json_formatter_extra_account_id_overrides_contextvar():
    token = account_id_var.set("ctx-account")
    try:
        record = _make_record(extra={"account_id": "extra-account"})
        payload = _format(record)
        assert payload["account_id"] == "extra-account"
    finally:
        account_id_var.reset(token)


def test_json_formatter_includes_exception():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys
        record = logging.LogRecord(
            name="quant.test", level=logging.ERROR, pathname=__file__, lineno=10,
            msg="failed", args=(), exc_info=sys.exc_info(),
        )
    payload = _format(record)
    assert "exception" in payload
    assert "ValueError" in payload["exception"]
    assert "boom" in payload["exception"]


def test_json_formatter_supports_chinese_message():
    payload = _format(_make_record(msg="买入贵州茅台"))
    assert payload["message"] == "买入贵州茅台"


def test_setup_logging_force_replaces_handlers():
    root = logging.getLogger()
    setup_logging(level="INFO", force=True)
    assert len(root.handlers) == 1
    fmt = root.handlers[0].formatter
    assert isinstance(fmt, JsonFormatter)


def test_setup_logging_text_mode_uses_text_formatter():
    root = logging.getLogger()
    setup_logging(level="DEBUG", force=True, structured=False)
    assert not isinstance(root.handlers[0].formatter, JsonFormatter)
    # Restore JSON for other tests
    setup_logging(level="INFO", force=True)


def test_end_to_end_logger_emits_json(capsys):
    setup_logging(level="INFO", service="test-svc", force=True)
    log = logging.getLogger("quant.e2e")

    token = request_id_var.set("rid-e2e-1")
    try:
        log.info("placed order", extra={"symbol": "600519.SH", "decision_type": "BUY"})
    finally:
        request_id_var.reset(token)

    captured = capsys.readouterr().out.strip().splitlines()
    assert captured, "expected at least one log line"
    payload = json.loads(captured[-1])
    assert payload["service"] == "test-svc"
    assert payload["request_id"] == "rid-e2e-1"
    assert payload["symbol"] == "600519.SH"
    assert payload["decision_type"] == "BUY"
    assert payload["message"] == "placed order"
