"""Notification channel status & manual test (Design Doc §5.6)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from apps.api.app.core.auth import AuthenticatedUser, require_admin
from apps.api.app.services.notify_service import _load_config, get_notifier

router = APIRouter(prefix="/notify", tags=["notify"])


class TestNotifyRequest(BaseModel):
    title: str = Field("[Quant] notification test")
    body: str = Field("This is a test message from the quant platform.")
    level: str = Field("info")


@router.get("/status")
def notify_status(user: AuthenticatedUser = Depends(require_admin)) -> dict:
    """Show which channels are configured (no secrets exposed)."""
    cfg = _load_config()
    return {
        "webhook": {
            "enabled": bool(cfg.webhook_url),
            "format": cfg.webhook_format,
            "url_set": bool(cfg.webhook_url),
        },
        "email": {
            "enabled": bool(cfg.email_smtp_host and cfg.email_to),
            "smtp_host": cfg.email_smtp_host or None,
            "smtp_port": cfg.email_smtp_port,
            "user": cfg.email_user or None,
            "to": cfg.email_to or None,
            "use_tls": cfg.email_use_tls,
            "password_set": bool(cfg.email_password),
        },
    }


@router.post("/test")
def notify_test(
    req: TestNotifyRequest,
    user: AuthenticatedUser = Depends(require_admin),
) -> dict:
    """Send a test notification through every configured channel."""
    results = get_notifier().send(req.title, req.body, req.level)
    return {
        "title": req.title,
        "results": results,
        "n_channels_attempted": len(results),
        "n_succeeded": sum(1 for ok in results.values() if ok),
    }
