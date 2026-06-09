"""模型进化与预测验证 API"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from apps.api.app.core.auth import get_current_user, require_admin
from apps.api.app.core.runtime_config import clear_runtime_section, get_runtime_config, update_runtime_section
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


class BackfillReq(BaseModel):
    symbols: Optional[list[str]] = None
    symbol_limit: int = Field(default=10, ge=1, le=100)
    bars_count: int = Field(default=260, ge=80, le=1000)
    samples_per_symbol: int = Field(default=6, ge=1, le=50)
    horizon_days: Optional[int] = Field(default=None, ge=1, le=60)
    min_gap_days: int = Field(default=5, ge=1, le=120)


class EvolutionConfigUpdate(BaseModel):
    validate_interval_seconds: Optional[int] = Field(default=None, ge=0, le=604800)
    validate_initial_delay_seconds: Optional[int] = Field(default=None, ge=0, le=86400)
    validate_limit: Optional[int] = Field(default=None, ge=1, le=5000)
    validate_time: Optional[str] = Field(default=None, max_length=16)
    failure_alert_enabled: Optional[bool] = None
    failure_alert_cooldown_seconds: Optional[int] = Field(default=None, ge=0, le=604800)
    auto_scan_enabled: Optional[bool] = None
    auto_scan_interval_seconds: Optional[int] = Field(default=None, ge=0, le=604800)
    auto_scan_top_n: Optional[int] = Field(default=None, ge=1, le=200)
    auto_scan_min_score: Optional[int] = Field(default=None, ge=0, le=100)
    auto_scan_candidate_pool: Optional[int] = Field(default=None, ge=1, le=1000)
    auto_scan_enable_fundamental: Optional[bool] = None
    auto_scan_enable_llm: Optional[bool] = None
    auto_scan_llm_top_n: Optional[int] = Field(default=None, ge=1, le=50)
    auto_scan_target_horizon_days: Optional[int] = Field(default=None, ge=0, le=60)
    auto_evolve_enabled: Optional[bool] = None
    auto_evolve_min_samples: Optional[int] = Field(default=None, ge=1, le=100000)
    auto_evolve_min_live_samples: Optional[int] = Field(default=None, ge=0, le=100000)
    auto_promote_min_success_rate: Optional[float] = Field(default=None, ge=0, le=1)
    auto_promote_min_avg_return_pct: Optional[float] = Field(default=None, ge=-100, le=100)
    auto_promote_max_brier_score: Optional[float] = Field(default=None, ge=0, le=1)
    auto_promote_max_calibration_error: Optional[float] = Field(default=None, ge=0, le=1)
    auto_walk_forward_min_samples: Optional[int] = Field(default=None, ge=1, le=100000)
    auto_walk_forward_min_dates: Optional[int] = Field(default=None, ge=1, le=100000)
    auto_walk_forward_min_profitable_folds: Optional[float] = Field(default=None, ge=0, le=1)
    auto_walk_forward_return_tolerance: Optional[float] = Field(default=None, ge=0, le=1)
    auto_walk_forward_consistency_tolerance: Optional[float] = Field(default=None, ge=0, le=1)
    auto_walk_forward_drawdown_tolerance: Optional[float] = Field(default=None, ge=0, le=1)
    auto_rollback_enabled: Optional[bool] = None
    auto_rollback_min_samples: Optional[int] = Field(default=None, ge=1, le=100000)
    auto_rollback_min_success_rate: Optional[float] = Field(default=None, ge=0, le=1)
    auto_rollback_min_avg_return_pct: Optional[float] = Field(default=None, ge=-100, le=100)
    auto_rollback_max_brier_score: Optional[float] = Field(default=None, ge=0, le=1)

    @field_validator("validate_time")
    @classmethod
    def _validate_time(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        raw = str(value).strip()
        if not raw:
            return ""
        parts = raw.split(":")
        if len(parts) != 2:
            raise ValueError("validate_time must be HH:MM")
        try:
            hour = int(parts[0])
            minute = int(parts[1])
        except ValueError as exc:
            raise ValueError("validate_time must be HH:MM") from exc
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("validate_time must be HH:MM")
        return f"{hour:02d}:{minute:02d}"


_CONFIG_KEY_MAP = {
    "validate_interval_seconds": "evolution_validate_interval_seconds",
    "validate_initial_delay_seconds": "evolution_validate_initial_delay_seconds",
    "validate_limit": "evolution_validate_limit",
    "validate_time": "evolution_validate_time",
    "failure_alert_enabled": "evolution_failure_alert_enabled",
    "failure_alert_cooldown_seconds": "evolution_failure_alert_cooldown_seconds",
    "auto_scan_enabled": "evolution_auto_scan_enabled",
    "auto_scan_interval_seconds": "evolution_auto_scan_interval_seconds",
    "auto_scan_top_n": "evolution_auto_scan_top_n",
    "auto_scan_min_score": "evolution_auto_scan_min_score",
    "auto_scan_candidate_pool": "evolution_auto_scan_candidate_pool",
    "auto_scan_enable_fundamental": "evolution_auto_scan_enable_fundamental",
    "auto_scan_enable_llm": "evolution_auto_scan_enable_llm",
    "auto_scan_llm_top_n": "evolution_auto_scan_llm_top_n",
    "auto_scan_target_horizon_days": "evolution_auto_scan_target_horizon_days",
    "auto_evolve_enabled": "evolution_auto_evolve_enabled",
    "auto_evolve_min_samples": "evolution_auto_evolve_min_samples",
    "auto_evolve_min_live_samples": "evolution_auto_evolve_min_live_samples",
    "auto_promote_min_success_rate": "evolution_auto_promote_min_success_rate",
    "auto_promote_min_avg_return_pct": "evolution_auto_promote_min_avg_return_pct",
    "auto_promote_max_brier_score": "evolution_auto_promote_max_brier_score",
    "auto_promote_max_calibration_error": "evolution_auto_promote_max_calibration_error",
    "auto_walk_forward_min_samples": "evolution_auto_walk_forward_min_samples",
    "auto_walk_forward_min_dates": "evolution_auto_walk_forward_min_dates",
    "auto_walk_forward_min_profitable_folds": "evolution_auto_walk_forward_min_profitable_folds",
    "auto_walk_forward_return_tolerance": "evolution_auto_walk_forward_return_tolerance",
    "auto_walk_forward_consistency_tolerance": "evolution_auto_walk_forward_consistency_tolerance",
    "auto_walk_forward_drawdown_tolerance": "evolution_auto_walk_forward_drawdown_tolerance",
    "auto_rollback_enabled": "evolution_auto_rollback_enabled",
    "auto_rollback_min_samples": "evolution_auto_rollback_min_samples",
    "auto_rollback_min_success_rate": "evolution_auto_rollback_min_success_rate",
    "auto_rollback_min_avg_return_pct": "evolution_auto_rollback_min_avg_return_pct",
    "auto_rollback_max_brier_score": "evolution_auto_rollback_max_brier_score",
}


def _config_view() -> dict:
    raw_runtime = get_runtime_config().get("evolution") or {}
    runtime = raw_runtime if isinstance(raw_runtime, dict) else {}
    short_runtime = {
        short_key: runtime[settings_key]
        for short_key, settings_key in _CONFIG_KEY_MAP.items()
        if settings_key in runtime
    }
    return {
        "effective": evolution_service.validation_loop_status(),
        "runtime_override": short_runtime,
    }


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


@router.get("/diagnostics")
def diagnostics(
    limit: int = 100,
    model_version_id: Optional[int] = None,
    _: object = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """预测复盘聚合：错误类型、根因、模型反馈和高置信失败样本。"""
    return evolution_service.get_diagnostics(
        limit=limit,
        model_version_id=model_version_id,
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


@router.post("/auto-scan")
async def auto_scan(_: object = Depends(require_admin)):
    """手动触发一次自动采样扫描，用于生成新的待验证预测样本。"""
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=1) as pool:
        return await loop.run_in_executor(pool, evolution_service.run_auto_scan_once)


@router.post("/backfill")
async def backfill(req: Optional[BackfillReq] = Body(default=None), _: object = Depends(require_admin)):
    """用历史 K 线回放生成已验证预测样本，帮助模型先获得可复盘训练数据。"""
    if req is None:
        req = BackfillReq()
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=1) as pool:
        return await loop.run_in_executor(
            pool,
            lambda: evolution_service.backfill_historical_predictions(
                symbols=req.symbols,
                symbol_limit=req.symbol_limit,
                bars_count=req.bars_count,
                samples_per_symbol=req.samples_per_symbol,
                horizon_days=req.horizon_days,
                min_gap_days=req.min_gap_days,
            ),
        )


@router.get("/config")
def get_config(_: object = Depends(get_current_user)):
    """查看自动验证/自动进化当前生效配置。"""
    return _config_view()


@router.post("/config")
async def update_config(payload: EvolutionConfigUpdate, _: object = Depends(require_admin)):
    """更新自动进化配置并重启后台循环，使调度参数立即生效。"""
    values = payload.model_dump(exclude_none=True)
    update_runtime_section(
        "evolution",
        {_CONFIG_KEY_MAP[key]: value for key, value in values.items()},
    )
    await evolution_service.restart_background_loops()
    return _config_view()


@router.delete("/config")
async def reset_config(_: object = Depends(require_admin)):
    clear_runtime_section("evolution")
    await evolution_service.restart_background_loops()
    return _config_view()
