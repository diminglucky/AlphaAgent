"""模型进化与预测验证 API"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api.app.core.auth import get_current_user, require_admin
from apps.api.app.db.session import get_db
from apps.api.app.services import evolution_service

router = APIRouter(prefix="/evolution", tags=["evolution"])


class ValidateReq(BaseModel):
    horizon_days: Optional[int] = None
    limit: int = Field(default=200, ge=1, le=1000)
    force: bool = False


class EvolveReq(BaseModel):
    min_samples: Optional[int] = Field(default=None, ge=1, le=10000)
    promote: bool = False


@router.get("/summary")
def summary(_: object = Depends(get_current_user), db: Session = Depends(get_db)):
    """模型进化总览：样本量、待验证数量、当前模型指标。"""
    return evolution_service.get_summary(db=db)


@router.get("/predictions")
def predictions(
    status: Optional[str] = None,
    horizon_days: Optional[int] = None,
    limit: int = 100,
    _: object = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """预测样本列表，可按状态/周期过滤。"""
    return evolution_service.list_predictions(
        status=status,
        horizon_days=horizon_days,
        limit=limit,
        db=db,
    )


@router.get("/models")
def models(_: object = Depends(get_current_user), db: Session = Depends(get_db)):
    """模型版本列表。"""
    return evolution_service.list_models(db=db)


@router.get("/scan-runs")
def scan_runs(limit: int = 20, _: object = Depends(get_current_user), db: Session = Depends(get_db)):
    """历史扫描批次，包含每次扫描推荐过的股票列表。"""
    return evolution_service.list_scan_runs(limit=limit, db=db)


@router.get("/compare")
def compare(
    base_run_id: Optional[int] = None,
    compare_run_id: Optional[int] = None,
    _: object = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """比较两次扫描：新增、重合、掉队。默认比较最近两次。"""
    return evolution_service.compare_scan_runs(
        base_run_id=base_run_id,
        compare_run_id=compare_run_id,
        db=db,
    )


@router.post("/validate")
async def validate(req: Optional[ValidateReq] = Body(default=None), _: object = Depends(require_admin)):
    """验证到期预测，force=true 可用于回放/测试未到期样本。"""
    if req is None:
        req = ValidateReq()
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=1) as pool:
        return await loop.run_in_executor(
            pool,
            lambda: evolution_service.validate_predictions(
                horizon_days=req.horizon_days,
                limit=req.limit,
                force=req.force,
            ),
        )


@router.post("/evolve")
def evolve(
    req: Optional[EvolveReq] = Body(default=None),
    _: object = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """基于已验证样本生成候选模型；promote=true 时立即切为 active。"""
    if req is None:
        req = EvolveReq()
    return evolution_service.evolve_model(
        min_samples=req.min_samples,
        promote=req.promote,
        db=db,
    )


@router.post("/auto-cycle")
def auto_cycle(_: object = Depends(require_admin), db: Session = Depends(get_db)):
    """手动触发一次受控自动进化周期：质量门槛达标才晋升，变差可回滚。"""
    return evolution_service.auto_evolve_cycle(db=db)
