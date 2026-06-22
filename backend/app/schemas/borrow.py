import uuid
from datetime import date, datetime

from pydantic import BaseModel


class BorrowItemRequest(BaseModel):
    equipment_id: uuid.UUID
    quantity: int = 1


class BorrowRequestCreate(BaseModel):
    purpose: str | None = None
    items: list[BorrowItemRequest]


class BorrowItemResponse(BaseModel):
    id: uuid.UUID
    equipment_id: uuid.UUID
    item_type_snapshot: str
    quantity: int
    returned: bool
    returned_at: datetime | None
    condition_on_return: str | None
    damage_note: str | None
    renewed_count: int
    extended_due_date: date | None

    model_config = {"from_attributes": True}


class BorrowRequestResponse(BaseModel):
    id: uuid.UUID
    request_code: str
    student_id: uuid.UUID
    purpose: str | None
    status: str
    requested_at: datetime
    approved_by: uuid.UUID | None
    approved_at: datetime | None
    rejection_reason: str | None
    due_date: date | None
    is_overdue: bool
    returned_at: datetime | None
    items: list[BorrowItemResponse] = []

    model_config = {"from_attributes": True}


class RejectRequest(BaseModel):
    rejection_reason: str


class ReturnItemRequest(BaseModel):
    condition_on_return: str  # ok / damaged / lost
    damage_note: str | None = None


class PaginatedBorrowRequests(BaseModel):
    items: list[BorrowRequestResponse]
    total: int
    page: int
    page_size: int
