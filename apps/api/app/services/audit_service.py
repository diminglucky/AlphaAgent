"""Audit log query service."""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from apps.api.app.db.repositories import AuditLogRepository
from libs.quant_core.models import AuditLog


class AuditService:
    def __init__(self, session: Session) -> None:
        self._repo = AuditLogRepository(session)

    def list_recent(self, limit: int = 100, action: Optional[str] = None) -> list[AuditLog]:
        return self._repo.list_recent(limit=limit, action=action)
