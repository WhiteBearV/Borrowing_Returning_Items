import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field


class BorrowItemRequest(BaseModel):
    equipment_id: uuid.UUID
    # gt=0 สำคัญ: จำนวนติดลบทำให้ approve ไป "ลบด้วยค่าลบ" = สต็อกเพิ่มเอง และผ่านด่านเช็คสต็อกด้วย
    quantity: int = Field(1, gt=0)


class BorrowRequestCreate(BaseModel):
    purpose: str | None = None
    items: list[BorrowItemRequest]


class BorrowItemResponse(BaseModel):
    id: uuid.UUID
    equipment_id: uuid.UUID
    equipment_name: str | None = None
    equipment_code: str | None = None
    equipment_unit: str | None = None
    equipment_value: float | None = None
    item_type_snapshot: str
    quantity: int
    returned: bool
    returned_at: datetime | None
    condition_on_return: str | None
    damage_note: str | None
    damage_photo_urls: list[str] | None = None
    renewed_count: int
    extended_due_date: date | None

    model_config = {"from_attributes": True}


class BorrowRequestResponse(BaseModel):
    id: uuid.UUID
    request_code: str
    student_id: uuid.UUID
    student_name: str | None = None
    student_email: str | None = None
    student_number: str | None = None
    purpose: str | None
    status: str
    requested_at: datetime
    approved_by: uuid.UUID | None
    approver_name: str | None = None
    approved_at: datetime | None
    rejection_reason: str | None
    due_date: date | None
    is_overdue: bool
    returned_at: datetime | None
    receiver_name: str | None = None
    items: list[BorrowItemResponse] = []

    model_config = {"from_attributes": True}


class RejectRequest(BaseModel):
    rejection_reason: str


class ReturnItemRequest(BaseModel):
    # durable: ok / damaged / lost ; consumable: returned_full / used_up / discarded
    condition_on_return: str
    damage_note: str | None = None
    damage_photo_urls: list[str] | None = None


class PaginatedBorrowRequests(BaseModel):
    items: list[BorrowRequestResponse]
    total: int
    page: int
    page_size: int
