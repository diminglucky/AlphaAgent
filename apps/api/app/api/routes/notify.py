"""飞书通知测试路由"""
from fastapi import APIRouter
from pydantic import BaseModel
from apps.api.app.services import feishu_service

router = APIRouter(prefix="/notify", tags=["notify"])


class TestReq(BaseModel):
    title: str = "测试消息"
    content: str = "飞书机器人配置成功！"


@router.post("/test")
def test_notify(req: TestReq):
    ok = feishu_service.send_feishu(req.title, req.content, color="blue")
    return {"ok": ok, "message": "发送成功" if ok else "发送失败（请检查 QUANT_FEISHU_WEBHOOK_URL 配置）"}


@router.get("/status")
def notify_status():
    from apps.api.app.core.config import get_settings
    settings = get_settings()
    return {
        "feishu_configured": bool(settings.feishu_webhook_url),
        "llm_configured": bool(settings.llm_api_key),
    }
