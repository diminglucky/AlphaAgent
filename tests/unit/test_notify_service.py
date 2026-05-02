"""Tests for NotifyService — webhook + email channel formatting and dispatch."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from apps.api.app.services.notify_service import (
    ChannelConfig,
    NotifyService,
)


def test_no_channels_when_unconfigured():
    n = NotifyService(ChannelConfig())
    results = n.send("title", "body")
    assert results == {}


def test_webhook_generic_format():
    cfg = ChannelConfig(webhook_url="https://example.test/hook", webhook_format="generic")
    n = NotifyService(cfg)
    payload = n._format_webhook("alert", "stuff happened", "warning")
    assert payload == {"title": "alert", "body": "stuff happened", "level": "warning"}


def test_webhook_feishu_format():
    cfg = ChannelConfig(webhook_url="https://x", webhook_format="feishu")
    payload = NotifyService(cfg)._format_webhook("alert", "body", "info")
    assert payload["msg_type"] == "text"
    assert "alert" in payload["content"]["text"]


def test_webhook_dingtalk_format():
    cfg = ChannelConfig(webhook_url="https://x", webhook_format="dingtalk")
    payload = NotifyService(cfg)._format_webhook("alert", "body", "info")
    assert payload["msgtype"] == "text"


def test_webhook_slack_format():
    cfg = ChannelConfig(webhook_url="https://x", webhook_format="slack")
    payload = NotifyService(cfg)._format_webhook("alert", "body", "info")
    assert "alert" in payload["text"]


def test_webhook_dispatch_calls_httpx():
    cfg = ChannelConfig(webhook_url="https://example.test/hook")
    n = NotifyService(cfg)
    with patch("httpx.post") as mp:
        mp.return_value = MagicMock(raise_for_status=MagicMock())
        results = n.send("t", "b")
    assert results == {"webhook": True}
    mp.assert_called_once()
    _, kw = mp.call_args
    assert kw["json"]["title"] == "t"


def test_webhook_failure_returns_false():
    cfg = ChannelConfig(webhook_url="https://example.test/hook")
    n = NotifyService(cfg)
    with patch("httpx.post", side_effect=RuntimeError("boom")):
        results = n.send("t", "b")
    assert results == {"webhook": False}


def test_email_dispatch_via_smtp_ssl():
    cfg = ChannelConfig(
        email_smtp_host="smtp.example.test", email_smtp_port=465,
        email_user="u@x", email_password="p", email_to="to@x",
        email_use_tls=True,
    )
    n = NotifyService(cfg)
    with patch("smtplib.SMTP_SSL") as smtp_cls:
        cm = MagicMock()
        smtp_cls.return_value.__enter__.return_value = cm
        results = n.send("title", "body")
    assert results == {"email": True}
    cm.login.assert_called_once_with("u@x", "p")
    cm.send_message.assert_called_once()


def test_email_failure_returns_false():
    cfg = ChannelConfig(
        email_smtp_host="smtp.example.test", email_smtp_port=465,
        email_user="u@x", email_password="p", email_to="to@x",
    )
    n = NotifyService(cfg)
    with patch("smtplib.SMTP_SSL", side_effect=RuntimeError("connection refused")):
        results = n.send("title", "body")
    assert results == {"email": False}


def test_both_channels_dispatched():
    cfg = ChannelConfig(
        webhook_url="https://example.test/hook",
        email_smtp_host="smtp.example.test", email_user="u@x",
        email_password="p", email_to="to@x",
    )
    n = NotifyService(cfg)
    with patch("httpx.post") as mp, patch("smtplib.SMTP_SSL") as smtp_cls:
        mp.return_value = MagicMock(raise_for_status=MagicMock())
        smtp_cls.return_value.__enter__.return_value = MagicMock()
        results = n.send("title", "body")
    assert set(results.keys()) == {"webhook", "email"}
    assert all(results.values())
