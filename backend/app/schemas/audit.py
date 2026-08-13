import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuditLogResponse(BaseModel):
    id: uuid.UUID
    actor_id: uuid.UUID | None
    actor_name: str | None = None
    actor_identifier: str | None = None
    action: str
    target_table: str
    target_id: uuid.UUID
    detail: dict[str, Any] | None
    created_at: datetime

    model_config = {"from_attributes": True}


class PaginatedAuditLogs(BaseModel):
    items: list[AuditLogResponse]
    total: int
    page: int
    page_size: int
