import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field


class BorrowItemRequest(BaseModel):
    equipment_id: uuid.UUID
    # gt=0 สำคัญ: จำนวนติดลบทำให้ approve ไป "ลบด้วยค่าลบ" = สต็อกเพิ่มเอง และผ่านด่านเช็คสต็อกด้วย
    quantity: int = Field(1, gt=0)


class BorrowRequestCreate(BaseModel):
    purpose: str | None = None
    requested_due_date: date
    items: list[BorrowItemRequest]


class BorrowItemResponse(BaseModel):
    id: uuid.UUID
    # อุปกรณ์ที่ปลดระวาง+ไม่มีการยืมค้าง ลบถาวรได้แล้ว (ดู equipment_service.delete_equipment) —
    # FK เป็น ON DELETE SET NULL ประวัติเก่าจึงมี equipment_id เป็น None ได้ ต้อง Optional ตาม
    equipment_id: uuid.UUID | None
    equipment_name: str | None = None
    equipment_code: str | None = None
    equipment_unit: str | None = None
    equipment_serial_number: str | None = None
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
    return_requested: bool
    return_requested_at: datetime | None
    renew_requested: bool = False
    renew_requested_at: datetime | None = None
    renew_requested_date: date | None = None
    renew_reason: str | None = None
    renew_rejected_reason: str | None = None

    model_config = {"from_attributes": True}


class BorrowRequestResponse(BaseModel):
    id: uuid.UUID
    request_code: str
    student_id: uuid.UUID
    student_name: str | None = None
    student_email: str | None = None
    student_number: str | None = None
    student_major: str | None = None
    purpose: str | None
    status: str
    requested_at: datetime
    approved_by: uuid.UUID | None
    approver_name: str | None = None
    approved_at: datetime | None
    rejection_reason: str | None
    requested_due_date: date
    due_date: date | None
    is_overdue: bool
    returned_at: datetime | None
    receiver_name: str | None = None
    items: list[BorrowItemResponse] = []

    model_config = {"from_attributes": True}


class RejectRequest(BaseModel):
    rejection_reason: str


class RenewRequestCreate(BaseModel):
    requested_date: date
    reason: str = Field(..., min_length=1)


class RenewRejectRequest(BaseModel):
    rejection_reason: str = Field(..., min_length=1)


class ReturnItemRequest(BaseModel):
    # durable: ok / damaged / lost ; consumable: returned_full / used_up / discarded
    condition_on_return: str
    damage_note: str | None = None
    damage_photo_urls: list[str] | None = None


class RequestReturnRequest(BaseModel):
    """นักศึกษาแจ้งขอคืน — เลือกได้ทีละชิ้น/หลายชิ้น/ทั้งหมดในลิสต์เดียว ไม่ใช่การคืนจริง"""
    item_ids: list[uuid.UUID] = Field(min_length=1)


class PaginatedBorrowRequests(BaseModel):
    items: list[BorrowRequestResponse]
    total: int
    page: int
    page_size: int
