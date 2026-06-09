from fastapi import APIRouter
from sqlalchemy import text

from apps.api.app.core.auth import is_auth_configured
from apps.api.app.core.config import get_feishu_webhook_url, get_settings
from apps.api.app.db.session import get_engine

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
        "auth_enabled": settings.auth_enabled,
        "auth_configured": (not settings.auth_enabled) or is_auth_configured(),
        "trading_mode": settings.trading_mode,
    }


def _check(
    check_id: str,
    label: str,
    status: str,
    message: str,
    *,
    next_action: str = "",
    blocks_local: bool = False,
    blocks_live: bool = False,
    details: dict | None = None,
) -> dict:
    return {
        "id": check_id,
        "label": label,
        "status": status,
        "message": message,
        "next_action": next_action,
        "blocks_local": blocks_local,
        "blocks_live": blocks_live,
        "details": details or {},
    }


def _database_kind(database_url: str) -> str:
    text_url = str(database_url or "").lower()
    if text_url.startswith("sqlite"):
        return "sqlite"
    if text_url.startswith("postgresql") or text_url.startswith("postgres"):
        return "postgresql"
    if text_url.startswith("mysql"):
        return "mysql"
    return "configured" if text_url else "missing"


@router.get("/health/readiness")
def readiness():
    """Return an operator-facing checklist for local and live-trading readiness."""
    settings = get_settings()
    mode = str(settings.trading_mode or "paper").strip().lower()
    checks: list[dict] = []

    auth_ready = (not settings.auth_enabled) or is_auth_configured()
    checks.append(_check(
        "auth_config",
        "API 鉴权",
        "pass" if auth_ready else "fail",
        "认证已关闭（仅适合本地单机）" if not settings.auth_enabled
        else ("API Key 已配置" if auth_ready else "认证已开启，但服务端没有配置任何 API Key"),
        next_action="" if auth_ready else "配置 QUANT_ADMIN_API_KEY / QUANT_TRADER_API_KEY / QUANT_VIEWER_API_KEY，或本地开发显式设置 QUANT_AUTH_ENABLED=false。",
        blocks_local=not auth_ready,
        blocks_live=(not auth_ready) or (not settings.auth_enabled),
        details={
            "auth_enabled": settings.auth_enabled,
            "auth_configured": auth_ready,
        },
    ))

    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
        db_msg = "数据库连接正常"
        db_error = ""
    except Exception as exc:
        db_ok = False
        db_msg = "数据库不可用"
        db_error = exc.__class__.__name__
    checks.append(_check(
        "database",
        "数据库",
        "pass" if db_ok else "fail",
        db_msg,
        next_action="" if db_ok else "检查 QUANT_DATABASE_URL、数据库权限和迁移状态。",
        blocks_local=not db_ok,
        blocks_live=not db_ok,
        details={"kind": _database_kind(settings.database_url), "error": db_error},
    ))

    from apps.api.app.services import market_service

    provider = getattr(market_service, "_provider_name", lambda: settings.market_data_provider)()
    provider = str(provider or "").strip().lower()
    is_mock = provider == "mock"
    quotes = market_service.get_all_quotes_snapshot()
    min_ready = 1 if is_mock else 1000
    cache_ready = len(quotes) >= min_ready
    checks.append(_check(
        "market_provider",
        "行情源",
        "warn" if is_mock else "pass",
        "当前使用 Mock 行情，只适合演示/测试" if is_mock else f"当前行情源：{provider or 'unknown'}",
        next_action="实盘前将 QUANT_MARKET_DATA_PROVIDER 切换为 akshare/真实行情源，并重新启动服务。" if is_mock else "",
        blocks_live=is_mock,
        details={"provider": provider, "mock": is_mock},
    ))
    checks.append(_check(
        "market_cache",
        "全市场缓存",
        "pass" if cache_ready else "warn",
        f"已加载 {len(quotes)} 条行情，要求至少 {min_ready} 条",
        next_action="" if cache_ready else "等待行情缓存完成，或检查行情源是否可访问。",
        blocks_live=False,
        details={"total": len(quotes), "min_ready": min_ready, "ready": cache_ready},
    ))

    paper_mode = mode == "paper"
    qmt_mode = mode == "qmt"
    checks.append(_check(
        "trading_mode",
        "交易模式",
        "pass" if qmt_mode else "warn",
        "当前是 QMT 模式" if qmt_mode else "当前是 paper 模拟盘模式，不会发送真实订单",
        next_action="" if qmt_mode else "实盘前设置 QUANT_TRADING_MODE=qmt，并连接 Windows QMT Gateway。",
        blocks_live=not qmt_mode,
        details={"mode": mode, "paper_mode": paper_mode},
    ))

    if qmt_mode:
        from apps.api.app.services import trading_service

        safe, reason, risk = trading_service._qmt_live_safety_check()
        checks.append(_check(
            "qmt_live_safety",
            "QMT 实盘门禁",
            "pass" if safe else "fail",
            "QMT 实盘门禁通过" if safe else reason,
            next_action="" if safe else "按阻断原因修复行情源、API 鉴权、Gateway API Key 或真实 xtquant backend。",
            blocks_live=not safe,
            details={"risk": risk},
        ))
    else:
        checks.append(_check(
            "qmt_live_safety",
            "QMT 实盘门禁",
            "warn",
            "未处于 QMT 模式，未执行 Gateway 实盘探测",
            next_action="切换到 QUANT_TRADING_MODE=qmt 后重新检查。",
            blocks_live=True,
        ))

    local_ready = not any(item["blocks_local"] and item["status"] == "fail" for item in checks)
    live_trading_ready = not any(item["blocks_live"] for item in checks if item["status"] in {"fail", "warn"})
    if not local_ready:
        status = "blocked"
    elif not live_trading_ready:
        status = "degraded"
    else:
        status = "ready"

    blockers = [item for item in checks if item["status"] == "fail"]
    warnings = [item for item in checks if item["status"] == "warn"]
    return {
        "status": status,
        "local_ready": local_ready,
        "live_trading_ready": live_trading_ready,
        "trading_mode": mode,
        "market_provider": provider,
        "checks": checks,
        "summary": {
            "passed": sum(1 for item in checks if item["status"] == "pass"),
            "warnings": len(warnings),
            "failures": len(blockers),
            "next_action": (
                blockers[0].get("next_action")
                if blockers else
                (warnings[0].get("next_action") if warnings else "系统已满足当前模式要求。")
            ),
        },
    }
