"""Multi-channel notification dispatcher.

Channels (each independently enabled via env vars):
- Browser: WebSocket (always on, handled in ws.py)
- Webhook: generic POST hook for 飞书 / 钉钉 / Slack / 自建机器人
- Email:  SMTP

Disabled channels are simply skipped; failures are logged but never raise
into the trading hot path.
"""

from __future__ import annotations

import logging
import os
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Optional

log = logging.getLogger("quant.notify")


@dataclass
class ChannelConfig:
    webhook_url: str = ""
    webhook_format: str = "generic"   # generic / feishu / dingtalk / slack
    email_smtp_host: str = ""
    email_smtp_port: int = 465
    email_user: str = ""
    email_password: str = ""
    email_to: str = ""
    email_use_tls: bool = True


def _load_config() -> ChannelConfig:
    return ChannelConfig(
        webhook_url=os.getenv("QUANT_NOTIFY_WEBHOOK_URL", ""),
        webhook_format=os.getenv("QUANT_NOTIFY_WEBHOOK_FORMAT", "generic"),
        email_smtp_host=os.getenv("QUANT_NOTIFY_SMTP_HOST", ""),
        email_smtp_port=int(os.getenv("QUANT_NOTIFY_SMTP_PORT", "465")),
        email_user=os.getenv("QUANT_NOTIFY_SMTP_USER", ""),
        email_password=os.getenv("QUANT_NOTIFY_SMTP_PASSWORD", ""),
        email_to=os.getenv("QUANT_NOTIFY_EMAIL_TO", ""),
        email_use_tls=os.getenv("QUANT_NOTIFY_SMTP_TLS", "true").lower() in ("1", "true", "yes"),
    )


class NotifyService:
    """Fan-out alerts to all configured external channels."""

    def __init__(self, config: Optional[ChannelConfig] = None) -> None:
        self._cfg = config or _load_config()

    # ------------------------------------------------------------------
    def send(self, title: str, body: str, level: str = "info") -> dict[str, bool]:
        """Send to every enabled channel; return per-channel success status."""
        results = {}
        if self._cfg.webhook_url:
            results["webhook"] = self._send_webhook(title, body, level)
        if self._cfg.email_smtp_host and self._cfg.email_to:
            results["email"] = self._send_email(title, body)
        return results

    # ------------------------------------------------------------------
    def _send_webhook(self, title: str, body: str, level: str) -> bool:
        try:
            import httpx
        except ImportError:
            log.warning("notify-webhook: httpx not installed")
            return False

        payload = self._format_webhook(title, body, level)
        try:
            resp = httpx.post(self._cfg.webhook_url, json=payload, timeout=10)
            resp.raise_for_status()
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("notify-webhook: failed: %s", exc)
            return False

    def _format_webhook(self, title: str, body: str, level: str) -> dict:
        fmt = self._cfg.webhook_format.lower()
        text = f"{title}\n{body}"

        if fmt == "feishu":
            return {"msg_type": "text", "content": {"text": text}}
        if fmt == "dingtalk":
            return {"msgtype": "text", "text": {"content": text}}
        if fmt == "slack":
            return {"text": text}
        # generic: pass through full structured payload
        return {"title": title, "body": body, "level": level}

    # ------------------------------------------------------------------
    def _send_email(self, title: str, body: str) -> bool:
        try:
            msg = EmailMessage()
            msg["Subject"] = title
            msg["From"] = self._cfg.email_user
            msg["To"] = self._cfg.email_to
            msg.set_content(body)

            if self._cfg.email_use_tls:
                with smtplib.SMTP_SSL(self._cfg.email_smtp_host, self._cfg.email_smtp_port, timeout=15) as s:
                    s.login(self._cfg.email_user, self._cfg.email_password)
                    s.send_message(msg)
            else:
                with smtplib.SMTP(self._cfg.email_smtp_host, self._cfg.email_smtp_port, timeout=15) as s:
                    s.login(self._cfg.email_user, self._cfg.email_password)
                    s.send_message(msg)
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("notify-email: failed: %s", exc)
            return False


# ---------------------------------------------------------------------------
# Singleton (cheap to construct, but keep one instance)
# ---------------------------------------------------------------------------

_singleton: Optional[NotifyService] = None


def get_notifier() -> NotifyService:
    global _singleton
    if _singleton is None:
        _singleton = NotifyService()
    return _singleton
