"""Portfolio-aware advisor route."""

from __future__ import annotations

from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from apps.api.app.api.routes.live_orders import get_current_user
from apps.api.app.api.routes.ws import get_cached_advisor_report
from apps.api.app.core.auth import AuthenticatedUser
from apps.api.app.db.session import get_db
from apps.api.app.services.advisor_service import AdvisorService

router = APIRouter(prefix="/advisor", tags=["advisor"])


@router.get(
    "/recommendations",
    summary="持仓感知的智能推荐：基于已持仓 + 自选股 给出买卖建议",
)
def get_advisor_recommendations(
    watchlist: Optional[str] = Query(None, description="逗号分隔的自选股代码，缺省使用默认列表"),
    fresh: bool = Query(False, description="强制重新计算，跳过缓存"),
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
):
    # Use cached version when available — the background task keeps it fresh.
    if not fresh and not watchlist:
        cached = get_cached_advisor_report()
        if cached:
            return cached

    parsed = [s.strip() for s in watchlist.split(",")] if watchlist else None
    svc = AdvisorService(db)
    report = svc.build(parsed)
    return {
        "generated_at": report.generated_at.isoformat(),
        "summary": report.summary,
        "items": [asdict(item) for item in report.items],
    }
