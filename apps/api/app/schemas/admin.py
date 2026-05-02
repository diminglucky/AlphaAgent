from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class AuditLogResponse(BaseModel):
    log_id: str
    action: str
    actor: str
    resource_type: str
    resource_id: Optional[str]
    details: dict
    created_at: datetime
