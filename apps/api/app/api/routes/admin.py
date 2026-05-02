"""Admin endpoints: audit logs."""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from apps.api.app.core.auth import AuthenticatedUser, require_admin
from apps.api.app.db.session import get_db
from apps.api.app.schemas.admin import AuditLogResponse
from apps.api.app.services.audit_service import AuditService

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/audit-logs", response_model=list[AuditLogResponse])
def list_audit_logs(
    limit: int = Query(default=100, ge=1, le=500),
    action: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(require_admin),
) -> list[AuditLogResponse]:
    logs = AuditService(db).list_recent(limit=limit, action=action)
    return [
        AuditLogResponse(
            log_id=log.log_id,
            action=log.action,
            actor=log.actor,
            resource_type=log.resource_type,
            resource_id=log.resource_id,
            details=log.details,
            created_at=log.created_at,
        )
        for log in logs
    ]
