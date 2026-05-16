"""提醒管理路由"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session

from apps.api.app.db.session import get_db
from apps.api.app.db.models import AlertORM

router = APIRouter(prefix="/alerts", tags=["alerts"])


class CreateAlertReq(BaseModel):
    symbol: str
    name: str = ""
    alert_type: str  # price_above / price_below
    target_price: float
    message: str = ""


@router.get("/")
def list_alerts(db: Session = Depends(get_db), triggered: Optional[bool] = None):
    q = db.query(AlertORM)
    if triggered is not None:
        q = q.filter(AlertORM.triggered == triggered)
    alerts = q.order_by(AlertORM.id.desc()).limit(100).all()
    return [
        {
            "id": a.id,
            "symbol": a.symbol,
            "name": a.name,
            "alert_type": a.alert_type,
            "target_price": a.target_price,
            "message": a.message,
            "triggered": a.triggered,
            "feishu_sent": a.feishu_sent,
            "created_at": a.created_at.isoformat(),
            "triggered_at": a.triggered_at.isoformat() if a.triggered_at else None,
        }
        for a in alerts
    ]


@router.post("/")
def create_alert(req: CreateAlertReq, db: Session = Depends(get_db)):
    if req.alert_type not in ("price_above", "price_below"):
        raise HTTPException(status_code=400, detail="alert_type 只支持 price_above / price_below")

    alert = AlertORM(
        symbol=req.symbol,
        name=req.name,
        alert_type=req.alert_type,
        target_price=req.target_price,
        message=req.message,
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return {"id": alert.id, "symbol": alert.symbol, "alert_type": alert.alert_type}


@router.delete("/{alert_id}")
def delete_alert(alert_id: int, db: Session = Depends(get_db)):
    alert = db.query(AlertORM).filter(AlertORM.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="提醒不存在")
    db.delete(alert)
    db.commit()
    return {"ok": True}
