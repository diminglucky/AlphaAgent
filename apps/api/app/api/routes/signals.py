"""Signal snapshot endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.app.core.auth import AuthenticatedUser, get_current_user, require_trader
from apps.api.app.db.session import get_db
from apps.api.app.schemas.signals import SaveSignalRequest, SignalSnapshotResponse
from apps.api.app.services.signal_service import SignalService

router = APIRouter(prefix="/signals", tags=["signals"])


@router.get("", response_model=list[SignalSnapshotResponse])
def list_latest_signals(
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> list[SignalSnapshotResponse]:
    snaps = SignalService(db).list_latest()
    return [
        SignalSnapshotResponse(
            signal_id=s.signal_id,
            symbol=s.symbol,
            as_of_time=s.as_of_time,
            signal_type=s.signal_type,
            raw_score=s.raw_score,
            confidence=s.confidence,
            components=s.components,
            expected_horizon=s.expected_horizon,
            model_version=s.model_version,
        )
        for s in snaps
    ]


@router.post("", response_model=SignalSnapshotResponse, status_code=201)
def save_signal(
    req: SaveSignalRequest,
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(require_trader),
) -> SignalSnapshotResponse:
    snap = SignalService(db).save_snapshot(
        symbol=req.symbol,
        signal_type=req.signal_type,
        raw_score=req.raw_score,
        confidence=req.confidence,
        components=req.components,
        expected_horizon=req.expected_horizon,
    )
    return SignalSnapshotResponse(
        signal_id=snap.signal_id,
        symbol=snap.symbol,
        as_of_time=snap.as_of_time,
        signal_type=snap.signal_type,
        raw_score=snap.raw_score,
        confidence=snap.confidence,
        components=snap.components,
        expected_horizon=snap.expected_horizon,
        model_version=snap.model_version,
    )
