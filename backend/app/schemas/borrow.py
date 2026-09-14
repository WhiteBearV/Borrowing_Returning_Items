import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator


class BorrowItemRequest(BaseModel):
    equipment_id: uuid.UUID
    # gt=0 สำคัญ: จำนวนติดลบทำให้ approve ไป "ลบด้วยค่าลบ" = สต็อกเพิ่มเอง และผ่านด่านเช็คสต็อกด้วย
    quantity: int = Field(1, gt=0)
    # วันคืนเฉพาะชิ้นนี้ (เฟส 3) — ไม่ส่ง = ใช้วันเดียวกับทั้งใบตามเดิม
    requested_due_date: date | None = None


class BorrowRequestCreate(BaseModel):
    # บังคับกรอกตั้งแต่ 5 ก.ย. 69 (feedback อาจารย์) — เดิม optional ทำให้คำขอจำนวนมากไม่มีวัตถุประสงค์เลย
    # หน้าเว็บมีปุ่มวัตถุประสงค์สำเร็จรูปให้กดแล้ว การบังคับกรอกจึงไม่เพิ่มภาระผู้ใช้
    # (คำขอเก่าใน DB ยังเป็น NULL ได้ตามเดิม — คอลัมน์ไม่ได้เปลี่ยน เปลี่ยนแค่ทางเข้าใหม่)
    purpose: str = Field(..., min_length=1, max_length=500)
    requested_due_date: date
    items: list[BorrowItemRequest]

    @field_validator("purpose")
    @classmethod
    def _strip_purpose(cls, v: str) -> str:
        """ตัดช่องว่างหัวท้าย — min_length ปล่อยสตริงที่มีแต่ช่องว่างผ่านได้"""
        v = v.strip()
        if not v:
            raise ValueError("purpose must not be blank")
        return v


class BorrowItemResponse(BaseModel):
    id: uuid.UUID
    # อุปกรณ์ที่ปลดระวาง+ไม่มีการยืมค้าง ลบถาวรได้แล้ว (ดู equipment_service.delete_equipment) —
    # FK เป็น ON DELETE SET NULL ประวัติเก่าจึงมี equipment_id เป็น None ได้ ต้อง Optional ตาม
    equipment_id: uuid.UUID | None
    equipment_name: str | None = None
    equipment_code: str | None = None
    equipment_unit: str | None = None
    equipment_serial_number: str | None = None
    # ชิ้นส่วนที่ติดตั้งอยู่ ณ ตอนออกเอกสาร (เฟส 8) — เติมโดย borrow_service._attach_equipment_specs
    # เฉพาะตอนสร้าง PDF ใบยืม ไม่ใช่คอลัมน์ใน DB (สเปกเปลี่ยนได้ตลอด อ่านสดตอนพิมพ์)
    equipment_specs: str | None = None
    equipment_value: float | None = None  # มูลค่าแท้จริง ณ วันอนุมัติ
    book_value: float | None = None       # มูลค่าตามบัญชี ณ วันอนุมัติ (ใบยืมเลือกโชว์ค่าใดค่าหนึ่ง)
    item_type_snapshot: str
    quantity: int
    requested_due_date: date | None = None
    due_date: date | None = None
    item_status: str = "pending"          # pending / approved / rejected
    rejection_reason: str | None = None   # เหตุผลที่ไม่อนุมัติเฉพาะชิ้นนี้
    returned: bool
    returned_at: datetime | None
    condition_on_return: str | None
    damage_note: str | None
    damage_photo_urls: list[str] | None = None
    renewed_count: int
    extended_due_date: date | None
    return_requested: bool
    return_requested_at: datetime | None
    return_appoint_at: datetime | None = None
    return_appoint_location: str | None = None
    renew_requested: bool = False
    renew_requested_at: datetime | None = None
    renew_requested_date: date | None = None
    renew_reason: str | None = None
    renew_rejected_reason: str | None = None
    # ค่าปรับ (เฟส 6) — ค่าที่ freeze ไว้ตอนรับคืน ผู้ยืมต้องเห็นยอดของตัวเองพร้อมที่มา
    fine_days_late: int | None = None
    fine_late_amount: float | None = None
    fine_damage_amount: float | None = None
    fine_total: float = 0
    fine_basis: dict | None = None
    fine_status: str = "none"           # none / unpaid / paid / waived
    fine_waived_reason: str | None = None
    fine_waiver_name: str | None = None

    model_config = {"from_attributes": True}


class BorrowRequestResponse(BaseModel):
    id: uuid.UUID
    request_code: str
    student_id: uuid.UUID
    student_name: str | None = None
    student_email: str | None = None
    student_number: str | None = None
    borrower_identifier: str | None = None  # รหัส นศ. หรือรหัสอาจารย์ แล้วแต่ว่าใครยืม
    borrower_is_student: bool = True
    student_major: str | None = None
    purpose: str | None
    status: str
    requested_at: datetime
    approved_by: uuid.UUID | None
    approver_name: str | None = None
    approved_at: datetime | None
    rejection_reason: str | None
    cancel_reason: str | None = None
    requested_due_date: date
    due_date: date | None
    is_overdue: bool
    returned_at: datetime | None
    receiver_name: str | None = None
    pickup_at: datetime | None = None
    pickup_location: str | None = None
    pickup_note: str | None = None
    # ชื่อไฟล์ใบยืมที่เซ็นแล้ว — ใช้เป็นแค่ "มีไฟล์แล้วหรือยัง" ฝั่งหน้าเว็บ
    # ตัวไฟล์ต้องโหลดผ่าน GET /borrow-requests/{id}/signed-form ที่ตรวจสิทธิ์ ไม่มี URL ตรงให้แปะ
    signed_form_file: str | None = None
    signed_form_at: datetime | None = None
    items: list[BorrowItemResponse] = []

    model_config = {"from_attributes": True}


class RejectRequest(BaseModel):
    rejection_reason: str


class CancelRequest(BaseModel):
    """ผู้ยืมยกเลิกคำขอเอง — บังคับเหตุผลเหมือนตอนแอดมินปฏิเสธ (8 ก.ย. 69)
    ของที่ถูกกันไว้ให้แล้วถูกปล่อยคืน คนอื่นรอคิวอยู่ ต้องตอบได้ว่าทำไมถึงยกเลิก"""
    reason: str = Field(..., min_length=1, max_length=500)


class ApproveItemDecision(BaseModel):
    """คำตัดสินรายชิ้นตอนอนุมัติ — approved=False ต้องมีเหตุผล (บังคับใน borrow_service)"""
    item_id: uuid.UUID
    approved: bool = True
    due_date: date | None = None          # แอดมินปรับวันคืนของชิ้นนี้ได้ ไม่ส่ง = ใช้วันที่นักศึกษาขอ
    # หน่วยที่จะจ่ายจริง (ต้องอยู่ในรุ่นเดียวกับที่ขอ) — ไม่ส่ง = ระบบเลือกหน่วยที่ถูกใช้น้อยสุดให้
    equipment_id: uuid.UUID | None = None
    rejection_reason: str | None = None


class ApproveRequest(BaseModel):
    """body ของ PATCH /approve — ไม่ส่งเลย = อนุมัติทั้งใบเหมือนเดิม (พฤติกรรมเดิมไม่เปลี่ยน)"""
    items: list[ApproveItemDecision] = []
    # นัดรับของ (เฟส 4) — เว้นว่างได้ = จ่ายทันทีหน้าเคาน์เตอร์ ไม่ได้นัดล่วงหน้า
    # เวลาที่ส่งมาไม่มี timezone ถือเป็นเวลาไทย (ผู้ใช้กรอกจากหน้าเว็บ) แปลงเป็น UTC ใน service
    pickup_at: datetime | None = None
    pickup_location: str | None = Field(None, max_length=255)
    pickup_note: str | None = None


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
    # ค่าปรับคิดอัตโนมัติจาก settings ตอนรับคืน — ส่ง 2 ช่องนี้มาเมื่ออยากใช้ยอดอื่นแทนที่ระบบคิดให้
    # (เช่น เจรจาลดหย่อน หรือของเสียหายแค่บางส่วนไม่เต็มมูลค่า) ไม่ส่ง = ใช้ยอดที่คำนวณได้
    fine_late_amount_override: float | None = Field(None, ge=0)
    fine_damage_amount_override: float | None = Field(None, ge=0)


class FineEditRequest(BaseModel):
    """แก้ยอดค่าปรับหลังบันทึกไปแล้ว — ส่งยอดใหม่ทั้งคู่เสมอ (แทนที่ของเดิม) พร้อมเหตุผล"""
    late_amount: float = Field(..., ge=0)
    damage_amount: float = Field(..., ge=0)
    reason: str = Field(..., min_length=1, max_length=500)


class FineWaiveRequest(BaseModel):
    """ยกเว้นค่าปรับ (superadmin) — บังคับเหตุผลเพราะเป็นการยกหนี้ ต้องตรวจสอบย้อนหลังได้"""
    reason: str = Field(..., min_length=1, max_length=500)


class RequestReturnRequest(BaseModel):
    """นักศึกษาแจ้งขอคืน — เลือกได้ทีละชิ้น/หลายชิ้น/ทั้งหมดในลิสต์เดียว ไม่ใช่การคืนจริง

    ตั้งแต่เฟส 4 บังคับนัดวัน-เวลา-สถานที่ (feedback อาจารย์ ข้อ 12) — เดิมส่งมาแค่ item_ids
    แอดมินจึงไม่รู้ว่าจะมีใครมาคืนตอนไหน ต้องเฝ้าหน้าเคาน์เตอร์เอง
    """
    item_ids: list[uuid.UUID] = Field(min_length=1)
    return_appoint_at: datetime
    return_appoint_location: str = Field(..., min_length=1, max_length=255)

    @field_validator("return_appoint_location")
    @classmethod
    def _strip_location(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("return_appoint_location must not be blank")
        return v


class PaginatedBorrowRequests(BaseModel):
    items: list[BorrowRequestResponse]
    total: int
    page: int
    page_size: int
