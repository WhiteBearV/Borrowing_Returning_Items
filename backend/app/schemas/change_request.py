import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ChangeRequestCreate(BaseModel):
    """ผู้ดูแลคลังยื่นคำขอให้ผู้ดูแลระบบสูงสุดแก้ข้อมูลให้"""
    target_table: str = Field(..., max_length=100)      # equipment / users / borrow_requests / อื่น ๆ
    target_id: uuid.UUID | None = None
    target_label: str | None = Field(None, max_length=255)  # ชื่อที่คนอ่านรู้เรื่อง เช่น "NB-001 โน้ตบุ๊ค Dell"
    reason: str = Field(..., min_length=1)              # ทำไมต้องแก้
    detail: str | None = None                           # อยากให้แก้เป็นอะไร (ข้อความล้วน ไม่ใช่คำสั่ง)


class ChangeRequestDecision(BaseModel):
    decision_note: str | None = None


class ChangeRequestResponse(BaseModel):
    id: uuid.UUID
    requester_id: uuid.UUID | None
    requester_name: str | None
    target_table: str
    target_id: uuid.UUID | None
    target_label: str | None
    reason: str
    detail: str | None
    status: str
    decided_by: uuid.UUID | None
    decided_by_name: str | None
    decided_at: datetime | None
    decision_note: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class PaginatedChangeRequests(BaseModel):
    items: list[ChangeRequestResponse]
    total: int
    page: int
    page_size: int
