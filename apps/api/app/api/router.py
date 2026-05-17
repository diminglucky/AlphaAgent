from fastapi import APIRouter
from apps.api.app.api.routes import health, market, watchlist, agent, alerts, positions, ws, notify, llm_config, scanner

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(market.router)
api_router.include_router(watchlist.router)
api_router.include_router(agent.router)
api_router.include_router(alerts.router)
api_router.include_router(positions.router)
api_router.include_router(notify.router)
api_router.include_router(llm_config.router)
api_router.include_router(scanner.router)
api_router.include_router(ws.router)
