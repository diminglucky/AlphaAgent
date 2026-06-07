import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from apps.api.app.api.router import api_router
from apps.api.app.core.config import get_settings
from apps.api.app.db.session import init_db


@asynccontextmanager
async def lifespan(_: FastAPI):
    # 配置日志
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    # 建表
    init_db()
    # 启动全市场行情缓存后台线程
    from apps.api.app.services.market_service import ensure_cache_running
    ensure_cache_running()
    # 启动 WebSocket 后台循环
    from apps.api.app.api.routes.ws import ensure_running
    await ensure_running()
    # 启动预测到期自动验证循环（默认每天一次，可用环境变量关闭）
    from apps.api.app.services import evolution_service
    evolution_service.ensure_validation_loop_running()
    evolution_service.ensure_auto_scan_loop_running()
    yield
    # 优雅关闭
    # 1. 停止 WS quote_loop
    from apps.api.app.api.routes.ws import stop as ws_stop
    try:
        await ws_stop()
    except Exception as e:
        logging.getLogger("quant.main").warning("WebSocket stop failed: %s", e)
    # 2. 停止模型进化验证循环
    try:
        await evolution_service.stop_auto_scan_loop()
        await evolution_service.stop_validation_loop()
    except Exception as e:
        logging.getLogger("quant.main").warning("Evolution background stop failed: %s", e)
    # 3. 关闭飞书线程池
    from apps.api.app.services.feishu_service import shutdown as feishu_shutdown
    try:
        feishu_shutdown()
    except Exception as e:
        logging.getLogger("quant.main").warning("Feishu pool shutdown failed: %s", e)



def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="2.0.0",
        description="AlphaAgent — 实时行情 + AI Agent分析 + 飞书提醒",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix=settings.api_v1_prefix)

    # 挂载 Vue3 前端
    web_dist = Path(__file__).resolve().parents[2] / "web" / "dist"
    if web_dist.exists():
        app.mount("/ui", StaticFiles(directory=str(web_dist), html=True), name="ui")

        @app.get("/", include_in_schema=False)
        async def root():
            return RedirectResponse(url="/ui/")

    return app


app = create_app()
