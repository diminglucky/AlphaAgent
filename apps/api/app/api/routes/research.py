"""Research-tracing endpoints — inspect factor snapshots & model runs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from apps.api.app.db.repositories import (
    FactorSnapshotRepository,
    ModelRunRepository,
)
from apps.api.app.db.session import get_db

router = APIRouter(prefix="/research", tags=["research"])


@router.get("/factors/{symbol}")
def list_factor_snapshots(
    symbol: str,
    feature_set_version: str | None = Query(None),
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """List recent factor snapshots for trace-back of a symbol's features."""
    rows = FactorSnapshotRepository(db).list_for_symbol(
        symbol=symbol, feature_set_version=feature_set_version, limit=limit,
    )
    return {
        "symbol": symbol,
        "count": len(rows),
        "feature_set_version": feature_set_version,
        "snapshots": [
            {
                "as_of_time": r["as_of_time"].isoformat(),
                "factor_name": r["factor_name"],
                "factor_value": r["factor_value"],
                "feature_set_version": r["feature_set_version"],
                "data_source": r["data_source"],
            }
            for r in rows
        ],
    }


@router.get("/runs")
def list_model_runs(
    model_name: str | None = Query(None),
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """List recent model train / backtest / inference runs."""
    rows = ModelRunRepository(db).list_recent(limit=limit, model_name=model_name)
    return {"count": len(rows), "runs": rows}
