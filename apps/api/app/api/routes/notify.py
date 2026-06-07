"""飞书通知测试路由"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from apps.api.app.core.auth import get_current_user, require_admin
from apps.api.app.core.config import get_feishu_webhook_url, get_settings
from apps.api.app.core.runtime_config import clear_runtime_section, get_runtime_config, update_runtime_section
from apps.api.app.services import feishu_service

router = APIRouter(prefix="/notify", tags=["notify"])


class TestReq(BaseModel):
    title: str = "测试消息"
    content: str = "飞书机器人配置成功！"


class FeishuConfigUpdate(BaseModel):
    webhook_url: str = ""


def _mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 12:
        return "***"
    return f"{value[:8]}...{value[-4:]}"


def _feishu_config_view() -> dict:
    settings = get_settings()
    runtime = (get_runtime_config().get("feishu") or {})
    runtime_url = str(runtime.get("webhook_url") or "").strip() if isinstance(runtime, dict) else ""
    effective = get_feishu_webhook_url()
    source = "runtime" if runtime_url else "env" if settings.feishu_webhook_url else "none"
    return {
        "configured": bool(effective),
        "source": source,
        "webhook_url_preview": _mask_secret(effective),
        "runtime_override": {
            "webhook_url_set": bool(runtime_url),
            "webhook_url_preview": _mask_secret(runtime_url),
        },
    }


@router.post("/test")
def test_notify(req: TestReq, _: object = Depends(require_admin)):
    ok = feishu_service.send_feishu(req.title, req.content, color="blue")
    return {"ok": ok, "message": "发送成功" if ok else "发送失败（请检查飞书 Webhook 配置）"}


@router.get("/status")
def notify_status(_: object = Depends(get_current_user)):
    settings = get_settings()
    return {
        "feishu_configured": bool(get_feishu_webhook_url()),
        "llm_configured": bool(settings.llm_api_key),
    }


@router.get("/config")
def get_notify_config(_: object = Depends(get_current_user)):
    return {"feishu": _feishu_config_view()}


@router.post("/config")
def update_notify_config(payload: FeishuConfigUpdate, _: object = Depends(require_admin)):
    update_runtime_section("feishu", {"webhook_url": payload.webhook_url.strip()})
    return {"feishu": _feishu_config_view()}


@router.delete("/config")
def reset_notify_config(_: object = Depends(require_admin)):
    clear_runtime_section("feishu")
    return {"feishu": _feishu_config_view()}
