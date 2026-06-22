import uuid
from datetime import datetime

from pydantic import BaseModel


class NotificationResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    borrow_request_id: uuid.UUID | None
    type: str
    channel: str
    message: str
    sent_at: datetime
    is_read: bool

    model_config = {"from_attributes": True}


class PaginatedNotifications(BaseModel):
    items: list[NotificationResponse]
    total: int
    page: int
    page_size: int
