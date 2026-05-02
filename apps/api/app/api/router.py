from fastapi import APIRouter

from apps.api.app.api.routes import (
    admin,
    advisor,
    agents,
    analysis,
    backtest,
    calendar,
    health,
    live_orders,
    llm_config,
    market,
    metrics,
    news,
    notify,
    orders,
    portfolio,
    recommendations,
    reports,
    research,
    risk,
    scanner,
    signals,
    watchlist,
    ws,
)


api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(market.router)
api_router.include_router(portfolio.router)
api_router.include_router(recommendations.router)
api_router.include_router(orders.router)
api_router.include_router(live_orders.router)
api_router.include_router(risk.router)
api_router.include_router(news.router)
api_router.include_router(signals.router)
api_router.include_router(admin.router)
api_router.include_router(analysis.router)
api_router.include_router(advisor.router)
api_router.include_router(watchlist.router)
api_router.include_router(reports.router)
api_router.include_router(calendar.router)
api_router.include_router(backtest.router)
api_router.include_router(metrics.router)
api_router.include_router(scanner.router)
api_router.include_router(research.router)
api_router.include_router(agents.router)
api_router.include_router(llm_config.router)
api_router.include_router(notify.router)
api_router.include_router(ws.router)

