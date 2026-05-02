"""Risk rule and event endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from apps.api.app.core.auth import AuthenticatedUser, get_current_user, require_admin
from apps.api.app.db.session import get_db
from apps.api.app.schemas.risk import (
    CreateRiskRuleRequest,
    RiskEventResponse,
    RiskRuleResponse,
    UpdateRiskRuleRequest,
)
from apps.api.app.services.risk_service import RiskService

router = APIRouter(prefix="/risk", tags=["risk"])


def _rule_to_resp(rule) -> RiskRuleResponse:
    return RiskRuleResponse(
        rule_id=rule.rule_id,
        rule_type=rule.rule_type,
        scope=rule.scope,
        threshold=rule.threshold,
        action_on_breach=rule.action_on_breach,
        enabled=rule.enabled,
        description=rule.description,
        updated_at=rule.updated_at,
    )


@router.get("/rules", response_model=list[RiskRuleResponse])
def list_rules(
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> list[RiskRuleResponse]:
    return [_rule_to_resp(r) for r in RiskService(db).list_rules()]


@router.post("/rules", response_model=RiskRuleResponse, status_code=201)
def create_rule(
    req: CreateRiskRuleRequest,
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(require_admin),
) -> RiskRuleResponse:
    rule = RiskService(db).create_rule(
        rule_type=req.rule_type,
        scope=req.scope,
        threshold=req.threshold,
        action_on_breach=req.action_on_breach,
        description=req.description,
        actor=user.api_key,
    )
    return _rule_to_resp(rule)


@router.get("/rules/{rule_id}", response_model=RiskRuleResponse)
def get_rule(
    rule_id: str,
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> RiskRuleResponse:
    try:
        return _rule_to_resp(RiskService(db).get_rule(rule_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/rules/{rule_id}", response_model=RiskRuleResponse)
def update_rule(
    rule_id: str,
    req: UpdateRiskRuleRequest,
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(require_admin),
) -> RiskRuleResponse:
    try:
        rule = RiskService(db).update_rule(
            rule_id=rule_id,
            threshold=req.threshold,
            enabled=req.enabled,
            description=req.description,
            actor=user.api_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _rule_to_resp(rule)


@router.delete("/rules/{rule_id}", status_code=204)
def delete_rule(
    rule_id: str,
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(require_admin),
) -> None:
    try:
        RiskService(db).delete_rule(rule_id, actor=user.api_key)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/events", response_model=list[RiskEventResponse])
def list_events(
    limit: int = 50,
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> list[RiskEventResponse]:
    events = RiskService(db).list_recent_events(limit=limit)
    return [
        RiskEventResponse(
            event_id=e.event_id,
            rule_id=e.rule_id,
            symbol=e.symbol,
            severity=e.severity,
            message=e.message,
            decision=e.decision,
            details=e.details,
            created_at=e.created_at,
        )
        for e in events
    ]
