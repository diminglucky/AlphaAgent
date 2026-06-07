from fastapi import APIRouter
from apps.api.app.core.config import get_feishu_webhook_url, get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    settings = get_settings()
    return {
        "status": "ok",
        "app": settings.app_name,
        "llm_configured": bool(settings.llm_api_key),
        "feishu_configured": bool(get_feishu_webhook_url()),
        "market_provider": settings.market_data_provider,
    }
