import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from apps.api.app.api.router import api_router
from apps.api.app.core.config import get_settings
from apps.api.app.db.bootstrap import ensure_database_initialized
from libs.infra.structured_logging import request_id_var, setup_logging


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-Id", str(uuid.uuid4()))
        request.state.request_id = request_id
        token = request_id_var.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-Id"] = request_id
        return response


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_database_initialized()
    # Start the realtime quote feed + advisor refresh loops
    from apps.api.app.api.routes.ws import ensure_background_running
    await ensure_background_running()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(
        level=os.getenv("QUANT_LOG_LEVEL", "INFO"),
        service=os.getenv("QUANT_SERVICE_NAME", "quant-api"),
    )
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="A-share intelligent quantitative trading platform scaffold",
        lifespan=lifespan,
    )

    app.add_middleware(RequestIdMiddleware)

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        rid = getattr(request.state, "request_id", None)
        return JSONResponse(
            status_code=400,
            content={"code": "BAD_REQUEST", "message": str(exc), "request_id": rid},
        )

    @app.exception_handler(Exception)
    async def generic_error_handler(request: Request, exc: Exception):
        rid = getattr(request.state, "request_id", None)
        return JSONResponse(
            status_code=500,
            content={"code": "INTERNAL_ERROR", "message": "An unexpected error occurred", "request_id": rid},
        )

    # When credentials are not used, allow_origins=* is safe.
    # If you need cookie-based auth, switch to an explicit list.
    cors_origins = os.getenv("QUANT_CORS_ORIGINS", "*").split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in cors_origins],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix=settings.api_v1_prefix)

    # Static frontend (Vue 3 build output) under /ui
    web_dist = Path(__file__).resolve().parents[2] / "web" / "dist"
    if web_dist.exists():
        app.mount(
            "/ui",
            StaticFiles(directory=str(web_dist), html=True),
            name="ui",
        )

        @app.get("/", include_in_schema=False)
        async def root_redirect():
            return RedirectResponse(url="/ui/")

    return app


app = create_app()
