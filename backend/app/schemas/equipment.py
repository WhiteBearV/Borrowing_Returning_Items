import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator


def _blank_sn_to_none(v: str | None) -> str | None:
    """เว้นว่าง/เว้นวรรคล้วนถือว่า "ไม่ได้กรอก SN" → normalize เป็น None เสมอ

    Partial unique index (ix_equipment_serial_number_unique) กัน SN ซ้ำด้วย `WHERE serial_number IS NOT NULL`
    เท่านั้น — string ว่าง `''` ไม่ใช่ NULL จึงยังนับเป็นค่าจริงที่ชนกันได้ ถ้าปล่อยให้ `''` หลุดถึง DB
    ตัวแรกที่สร้างด้วย SN ว่างจะ "จอง" ค่า `''` ไว้ แล้วตัวถัดไปที่ส่ง SN ว่างมาจะชน UniqueViolation
    กลายเป็น 500 (ไม่ใช่ 409 ที่จับไว้) — ต้องตัดที่ต้นทางระดับ schema ก่อนถึง service/DB เสมอ
    """
    if v is None:
        return None
    if not isinstance(v, str):
        return v  # ปล่อยให้ pydantic ตัดสินเอง (int/list/bool → 422 string_type ตามเดิม)
    v = v.strip()
    return v or None


class CategoryResponse(BaseModel):
    id: uuid.UUID
    name: str
    created_at: datetime

    model_config = {"from_attributes": True}


class CategoryCreate(BaseModel):
    name: str


class HolderInfo(BaseModel):
    """ผู้ที่กำลังครอบครองอุปกรณ์ชิ้นนี้อยู่ (ยืมแล้วยังไม่คืน)"""
    holder_name: str
    student_number: str | None = None
    due_date: date | None
    quantity: int


class EquipmentResponse(BaseModel):
    id: uuid.UUID
    code: str
    serial_number: str | None = None
    name: str
    categories: list[CategoryResponse]
    item_type: str
    description: str | None
    image_url: str | None
    image_urls: list[str] = []
    location: str | None
    unit: str | None
    unit_value: float | None
    quantity_total: int
    quantity_available: int
    low_stock_threshold: int | None
    status: str
    is_borrowable: bool
    created_at: datetime
    updated_at: datetime
    # หน่วยนี้มีคำขอ approved ที่ยังไม่คืนอยู่จริงไหม — คำนวณจาก borrow_items ไม่ใช่ column บน equipment
    # (status="available" แปลว่า "ยืมได้" เฉยๆ ไม่ใช่ "ไม่มีใครถือ" ดู equipment_service._apply_status_filter)
    # ต้องแยกจาก quantity_available < quantity_total เพราะช่องว่างนั้นเกิดจากของเสีย/สูญหายที่คืนไปแล้วได้ด้วย
    # ไม่ได้แปลว่ามีคนถือของอยู่จริงเสมอไป — ปล่อยให้ derive ผิดจากตัวเลขจะเห็น "ถูกยืม" ทั้งที่ไม่มีใครยืมจริง
    is_currently_borrowed: bool = False
    holder: HolderInfo | None = None  # ใครถือหน่วยนี้อยู่ (มีความหมายเฉพาะแถวหน่วยเดียว ดู _build_group_response)
    # ผู้ถือทุกคน (ไม่ใช่แค่คนแรก) — มีความหมายจริงเฉพาะ consumable ที่แถวเดียวยืมพร้อมกันได้หลายคนคนละจำนวน
    # (ดู get_holders_map) ส่งมาเสมอทุก response ไม่ใช่แค่ตอน detail เพื่อให้ตารางจัดการอุปกรณ์โชว์ได้ตรง ๆ
    holders: list[HolderInfo] = []

    model_config = {"from_attributes": True}


class EquipmentDetailResponse(EquipmentResponse):
    holders: list[HolderInfo]


class LocationCount(BaseModel):
    """จำนวนหน่วยแยกตามสถานที่จริงในกลุ่ม — ค่าว่าง/ไม่ระบุถูกจัดเป็น "ไม่ระบุสถานที่" """
    location: str
    count: int


class EquipmentGroupResponse(EquipmentResponse):
    """อุปกรณ์รุ่นเดียวกันหลายหน่วย (name+item_type ตรงกัน) ยุบเป็นการ์ดเดียว

    id/code/รูป/คำอธิบาย ฯลฯ มาจากหน่วยรหัสต่ำสุด — quantity_* เป็นผลรวมทั้งกลุ่ม
    unit_count = จำนวนหน่วยจริงในรุ่นนี้ (ใช้รู้ว่าต้องมีช่องกรอกจำนวน >1 ไหม)
    locations = สรุปจำนวนหน่วยแยกตามสถานที่จริงของทุกหน่วยในกลุ่ม (การ์ดตัวแทนโชว์ location เดียวไม่พอ
    ถ้าหน่วยในกลุ่มกระจายอยู่คนละที่ — เช่นหลังแยกเป็นรายชิ้นแล้วย้ายบางชิ้นไปตู้อื่น)
    """
    unit_count: int
    locations: list[LocationCount] = []


class PaginatedEquipmentGroup(BaseModel):
    items: list[EquipmentGroupResponse]
    total: int
    page: int
    page_size: int


class EquipmentUnitSummary(BaseModel):
    """หน่วยเดียวในกลุ่ม — ให้หน้าจัดการอุปกรณ์กางดูและแก้ไข/ปลดระวางทีละหน่วยได้"""
    id: uuid.UUID
    code: str
    serial_number: str | None = None
    location: str | None = None
    status: str
    quantity_total: int
    quantity_available: int
    is_borrowable: bool
    is_currently_borrowed: bool = False
    holder: HolderInfo | None = None  # ใครถือหน่วยนี้อยู่ (มีค่าก็ต่อเมื่อ is_currently_borrowed)

    model_config = {"from_attributes": True}


class EquipmentGroupDetailResponse(EquipmentGroupResponse):
    holders: list[HolderInfo]
    members: list[EquipmentUnitSummary] = []


class EquipmentCreate(BaseModel):
    # เว้นว่างได้เฉพาะวัสดุสิ้นเปลือง (consumable) — สร้าง.equipment_service.create_equipment จะออกรหัสให้อัตโนมัติ
    # จากชื่อ+เลขลำดับ เพราะรหัสไม่มีความหมายจริงสำหรับของแบบนี้ (เช่น เซ็นเซอร์หลายแบบจำนวนมาก)
    code: str | None = None
    serial_number: str | None = None
    name: str
    category_ids: list[uuid.UUID]
    item_type: str  # durable / consumable
    description: str | None = None
    # บังคับรูปอย่างน้อย 1 เฉพาะตอนสร้างใหม่ — ของเดิมจากทะเบียน 704 แถวยังไม่มีรูป
    # ถ้าไปบังคับใน EquipmentUpdate ด้วยจะแก้ข้อมูลของเดิมไม่ได้เลย
    image_urls: list[str] = Field(..., min_length=1)
    location: str | None = None
    unit: str | None = None
    unit_value: float | None = None
    quantity_total: int = 1
    low_stock_threshold: int | None = None
    is_borrowable: bool = True

    _normalize_serial_number = field_validator("serial_number", mode="before")(_blank_sn_to_none)
    _normalize_code = field_validator("code", mode="before")(_blank_sn_to_none)  # ชื่อ generic ใช้กับ code ได้เหมือนกัน


class RestockRequest(BaseModel):
    count: int = Field(..., gt=0)


class AdjustStockRequest(BaseModel):
    """ปรับ quantity_available ให้ตรงกับที่นับได้จริง (ต่างจาก restock ที่บวกเพิ่ม — อันนี้ SET ตรง ๆ)"""
    new_available: int = Field(..., ge=0)
    reason: str = Field(..., min_length=1)
    photo_urls: list[str] = []


class EquipmentUpdate(BaseModel):
    code: str | None = None
    item_type: str | None = None
    serial_number: str | None = None
    name: str | None = None
    category_ids: list[uuid.UUID] | None = None
    description: str | None = None
    image_urls: list[str] | None = None
    location: str | None = None
    unit: str | None = None
    unit_value: float | None = None
    quantity_total: int | None = None
    low_stock_threshold: int | None = None
    status: str | None = None
    is_borrowable: bool | None = None

    _normalize_serial_number = field_validator("serial_number", mode="before")(_blank_sn_to_none)
    _normalize_code = field_validator("code", mode="before")(_blank_sn_to_none)


class ImportRowIn(BaseModel):
    """หนึ่งบรรทัดในร่างนำเข้าที่แอดมินตรวจ/แก้แล้ว — ส่งกลับมาเฉพาะบรรทัดที่เลือกบันทึกจริง

    แก้ได้ทุกช่องเหมือนฟอร์มเพิ่มอุปกรณ์ทีละชิ้น (หมวดหมู่/รูป/คำอธิบาย/ประเภท/จำนวน)
    เพราะไฟล์ทะเบียนมีแค่ชื่อ-เลข-สถานะ ที่เหลือแอดมินต้องเติมเองในร่าง
    """
    code: str
    action: str  # new / update / retire
    name: str
    serial_number: str | None = None
    location: str | None = None
    status: str
    item_type: str = "durable"  # durable / material / consumable
    quantity: int = 1
    unit: str | None = None
    categories: list[str] = []  # ชื่อหมวดหมู่ (สร้างให้ถ้ายังไม่มี) — ว่าง = ใช้ที่ระบบเดาจากชื่อ
    description: str | None = None
    image_urls: list[str] = []
    reason: str | None = None  # เหตุผลปลดระวาง (เฉพาะ action=retire)

    _normalize_serial_number = field_validator("serial_number", mode="before")(_blank_sn_to_none)


class ImportCommitRequest(BaseModel):
    filename: str | None = None
    rows: list[ImportRowIn]


class PaginatedEquipment(BaseModel):
    items: list[EquipmentResponse]
    total: int
    page: int
    page_size: int


class BulkDeleteRequest(BaseModel):
    equipment_ids: list[uuid.UUID] = Field(..., min_length=1)


class BulkDeleteFailure(BaseModel):
    equipment_id: uuid.UUID
    reason: str


class BulkDeleteResult(BaseModel):
    deleted: list[uuid.UUID]
    failed: list[BulkDeleteFailure]


class BulkRetireRequest(BaseModel):
    equipment_ids: list[uuid.UUID] = Field(..., min_length=1)
    reason: str | None = None


class BulkRetireResult(BaseModel):
    retired: list[uuid.UUID]
    failed: list[BulkDeleteFailure]


class EquipmentBulkUpdate(BaseModel):
    """ฟิลด์ที่แก้พร้อมกันหลายหน่วยได้อย่างปลอดภัยเท่านั้น — ไม่รวม code/serial_number เพราะ unique ต่อหน่วย
    (ตั้งค่าเดียวกันให้หลายแถวพร้อมกันจะชน DB constraint ทันทีตั้งแต่แถวที่ 2), quantity_total/quantity_available
    (ตัวนับสต็อกต่อหน่วย ตั้งเลขเดียวกันทับทุกแถวไม่มีความหมาย) — name/item_type/category_ids ปลอดภัยเพราะไม่มี
    unique constraint และ update_equipment (แก้ทีละหน่วย) ก็แก้ 2 ฟิลด์แรกได้อยู่แล้วโดยไม่กระทบประวัติการยืมเก่า
    (BorrowItem เก็บ snapshot แยก) จึงใช้ตรรกะเดียวกันได้กับหลายแถวพร้อมกัน
    """
    name: str | None = None
    item_type: str | None = None
    category_ids: list[uuid.UUID] | None = None
    location: str | None = None
    description: str | None = None
    image_urls: list[str] | None = None
    unit: str | None = None
    unit_value: float | None = None
    low_stock_threshold: int | None = None
    status: str | None = None
    is_borrowable: bool | None = None


class BulkUpdateRequest(BaseModel):
    equipment_ids: list[uuid.UUID] = Field(..., min_length=1)
    update: EquipmentBulkUpdate


class BulkUpdateResult(BaseModel):
    updated: list[EquipmentResponse]
    # แถวที่เปลี่ยนเข้า durable แต่รหัสไม่ครบ 15 หลัก (ดู equipment_service._validate_durable_code) ถูกข้ามแบบ
    # best-effort ไม่ทำให้ทั้ง batch ล้ม — ต่างจากฟิลด์อื่นที่ยังคง all-or-nothing เหมือนเดิม
    failed: list[BulkDeleteFailure] = []


class BulkAdjustStockRequest(BaseModel):
    """ปรับยอดคงเหลือหลายรายการพร้อมกันแบบ delta (บวก/ลบเท่ากันทุกแถว) — ต่างจาก AdjustStockRequest เดี่ยวที่
    SET ค่า absolute เพราะแต่ละแถวที่เลือก quantity_total ไม่เท่ากัน ตั้งเลขเดียวทับทุกแถวไม่มีความหมาย
    แต่ละแถว clamp ไม่ให้เกิน quantity_total ลบจำนวนที่ถูกยืมออกไปจริง หรือต่ำกว่า 0 ของแถวนั้นเอง
    (ดู docstring equipment_service.bulk_adjust_stock)
    """
    equipment_ids: list[uuid.UUID] = Field(..., min_length=1)
    delta: int
    reason: str = Field(..., min_length=1)


class BulkAdjustStockResult(BaseModel):
    updated: list[EquipmentResponse]
    # id ที่ไม่มีจริงถูกข้ามแบบ best-effort ไม่ทำให้ทั้ง batch ล้ม (mirror BulkUpdateResult.failed) —
    # ดู equipment_service.bulk_adjust_stock
    failed: list[BulkDeleteFailure] = []
