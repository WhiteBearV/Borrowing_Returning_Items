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
    manufacturer: str | None = None
    model_number: str | None = None
    categories: list[CategoryResponse]
    item_type: str
    description: str | None
    image_url: str | None
    image_urls: list[str] = []
    location: str | None
    unit: str | None
    unit_value: float | None  # มูลค่าแท้จริง (ราคาที่ซื้อมา) — ชื่อฟิลด์เดิม ความหมายเดิม
    # วันที่ได้มา/รับเข้าทะเบียน — คนละอย่างกับ created_at (วันที่แถวถูกสร้างในระบบ) ใช้คำนวณอายุจริง
    acquired_at: date | None = None
    useful_life_years: int | None = None
    book_value_override: float | None = None
    # มูลค่าตามบัญชี — คำนวณสดจาก equipment_service.book_value() ไม่ใช่คอลัมน์ใน DB
    # (attach_book_values เติมเป็น attribute ให้ก่อน model_validate) None = ยังไม่มีราคาหรือยังไม่มีวันที่ได้มา
    book_value: float | None = None
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

    # ค่าคุณภาพ (เฟส 10) — **เฉพาะเจ้าหน้าที่เห็น** (equipment_service.attach_quality_info เติมให้เฉพาะ
    # viewer ที่ is_staff เท่านั้น) นักศึกษาได้ None ทุกฟิลด์เสมอ ไม่มีข้อยกเว้น
    quality_tracked: bool | None = None
    quality_life_years: int | None = None
    quality_baseline: float | None = None       # ว่าง = ยังไม่เคยประเมิน (ห้ามตีความเป็น 0)
    quality_baseline_at: datetime | None = None
    current_quality: float | None = None        # คำนวณสดจาก equipment_service.current_quality()
    quality_age_drop: float | None = None        # ส่วนที่หักจากอายุ (จุดเปอร์เซ็นต์) — ใช้โชว์ที่มาของตัวเลข
    quality_usage_drop: float | None = None      # ส่วนที่หักจากการถูกยืม (จุดเปอร์เซ็นต์)
    quality_needs_inspection: bool | None = None  # ต่ำกว่าเกณฑ์ quality_low_threshold — ยังยืมได้ตามปกติ
    quality_remaining_life_years: float | None = None  # อายุที่เหลือ (ปี) = คุณภาพ% × อายุการใช้งาน

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


class EquipmentTypeSummary(BaseModel):
    """สรุปของประเภทหนึ่งในผลการค้นหาปัจจุบัน"""
    item_type: str
    groups: int      # จำนวน "รุ่น" (การ์ดที่ยุบกลุ่มแล้ว)
    pieces: int      # จำนวนชิ้นจริง (รวม quantity_total ของทุกหน่วยในกลุ่ม)
    available: int   # ชิ้นที่ยังว่างให้ยืม


class EquipmentListSummary(BaseModel):
    """สรุปทั้งผลการค้นหา ไม่ใช่แค่หน้าที่กำลังดู — หน้าจัดการอุปกรณ์ยุบรุ่นเดียวกันเป็นการ์ดเดียว
    ตัวเลข total (จำนวนการ์ด) จึงน้อยกว่าของจริงมาก ("187 รายการ" ทั้งที่ในคลังมีพันกว่าชิ้น)
    """
    groups: int
    pieces: int
    available: int
    by_type: list[EquipmentTypeSummary] = []


class PaginatedEquipmentGroup(BaseModel):
    items: list[EquipmentGroupResponse]
    total: int
    page: int
    page_size: int
    summary: EquipmentListSummary | None = None


class EquipmentUnitSummary(BaseModel):
    """หน่วยเดียวในกลุ่ม — ให้หน้าจัดการอุปกรณ์กางดูและแก้ไข/ปลดระวางทีละหน่วยได้"""
    id: uuid.UUID
    code: str
    serial_number: str | None = None
    location: str | None = None
    status: str
    acquired_at: date | None = None
    unit_value: float | None = None
    book_value: float | None = None
    quantity_total: int
    quantity_available: int
    is_borrowable: bool
    is_currently_borrowed: bool = False
    holder: HolderInfo | None = None  # ใครถือหน่วยนี้อยู่ (มีค่าก็ต่อเมื่อ is_currently_borrowed)
    # วันรวมที่หน่วยนี้เคยถูกยืมออกไป — เกณฑ์ที่ระบบใช้เลือกหน่วยจ่ายของ (น้อยสุดก่อน)
    # แอดมินเห็นตัวเลขนี้ตอนอนุมัติ จะได้รู้ว่าทำไมระบบเลือกชิ้นนี้ และตัดสินใจเลือกทับเองได้
    days_borrowed: int = 0

    # ค่าคุณภาพ (เฟส 10) — เฉพาะเจ้าหน้าที่เห็น (เหมือน EquipmentResponse ดู attach_quality_info)
    quality_tracked: bool | None = None
    quality_life_years: int | None = None
    quality_baseline: float | None = None
    quality_baseline_at: datetime | None = None
    current_quality: float | None = None
    quality_age_drop: float | None = None
    quality_usage_drop: float | None = None
    quality_needs_inspection: bool | None = None
    quality_remaining_life_years: float | None = None

    model_config = {"from_attributes": True}


class PartResponse(BaseModel):
    """ชิ้นส่วนที่ติดตั้ง/เคยติดตั้งกับอุปกรณ์ชิ้นหนึ่ง — อายุและมูลค่าแยกจากเครื่องหลักโดยสิ้นเชิง"""
    id: uuid.UUID
    equipment_id: uuid.UUID
    name: str
    serial_number: str | None = None
    unit_value: float | None = None
    acquired_at: date | None = None
    useful_life_years: int | None = None
    removed_at: date | None = None
    removed_reason: str | None = None
    note: str | None = None
    # ชิ้นนี้มาแทนชิ้นไหน (เฟส 8) — ชื่อชิ้นเดิมส่งมาด้วยเพื่อให้หน้าเว็บเขียนไทม์ไลน์ได้โดยไม่ต้อง join เอง
    replaces_part_id: uuid.UUID | None = None
    replaces_part_name: str | None = None
    is_installed: bool = True
    book_value: float | None = None  # คำนวณสดด้วยสูตรเดียวกับเครื่องหลัก (ดู equipment_service.book_value)
    created_at: datetime

    model_config = {"from_attributes": True}


class PartCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    serial_number: str | None = None
    unit_value: float | None = Field(None, gt=0)
    acquired_at: date  # วันที่ติดตั้ง — บังคับ เพราะเป็นจุดเริ่มนับอายุของชิ้นส่วน
    useful_life_years: int | None = Field(None, gt=0)
    note: str | None = None
    # ชิ้นเดิมที่ถูกแทนที่ (ต้องอยู่กับอุปกรณ์ตัวเดียวกัน — ตรวจใน equipment_part_service.install_part)
    replaces_part_id: uuid.UUID | None = None
    # ประเมินคุณภาพเครื่องหลักใหม่ (ไม่บังคับ) — มีผลก็ต่อเมื่อเครื่องหลักเปิดติดตามคุณภาพอยู่ (quality_tracked)
    # หน้าเว็บเสนอ "ปัจจุบัน −2" (quality_repair_default_drop) เป็นค่าเริ่มต้นให้แก้ก่อนส่ง
    quality_after: float | None = Field(None, ge=0, le=100)

    _normalize_serial_number = field_validator("serial_number", mode="before")(_blank_sn_to_none)


class PartUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    serial_number: str | None = None
    unit_value: float | None = Field(None, gt=0)
    acquired_at: date | None = None
    useful_life_years: int | None = Field(None, gt=0)
    note: str | None = None

    _normalize_serial_number = field_validator("serial_number", mode="before")(_blank_sn_to_none)


class PartRemove(BaseModel):
    """ถอดชิ้นส่วนออก — ไม่ลบแถว บันทึกวันที่+เหตุผลไว้เป็นประวัติการอัพเกรด"""
    removed_at: date | None = None  # ไม่ส่ง = วันนี้
    reason: str = Field(..., min_length=1)


class EquipmentGroupDetailResponse(EquipmentGroupResponse):
    holders: list[HolderInfo]
    members: list[EquipmentUnitSummary] = []
    # หน่วยที่ dispatch_order() แนะนำให้จ่ายกับผู้ยืมที่ระบุผ่าน query param recommend_for (เฉพาะเจ้าหน้าที่)
    # None = ไม่ได้ขอคำแนะนำ หรือไม่มีหน่วยว่างให้เลือกเลย — UnitPickerModal ใช้ขึ้นป้าย "แนะนำสำหรับผู้ยืมนี้"
    recommended_unit_id: uuid.UUID | None = None


class EquipmentQualityAssessRequest(BaseModel):
    """ปุ่ม "ประเมินคุณภาพ" ในหน้าอุปกรณ์ — บังคับเหตุผลเสมอ (ต่างจาก 3 จังหวะอัตโนมัติอื่นที่ไม่บังคับ)"""
    quality_after: float = Field(..., ge=0, le=100)
    reason: str = Field(..., min_length=1)

    # min_length=1 เฉยๆ ยอมรับ " " (ช่องว่างล้วน) ผ่านได้ — บังคับ strip แล้วต้องไม่ว่างจริง (พบตอนรีวิวรอบ 2)
    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("กรุณาระบุเหตุผลที่ประเมินคุณภาพ")
        return v


class EquipmentCreate(BaseModel):
    # เว้นว่างได้เฉพาะวัสดุสิ้นเปลือง (consumable) — สร้าง.equipment_service.create_equipment จะออกรหัสให้อัตโนมัติ
    # จากชื่อ+เลขลำดับ เพราะรหัสไม่มีความหมายจริงสำหรับของแบบนี้ (เช่น เซ็นเซอร์หลายแบบจำนวนมาก)
    code: str | None = None
    serial_number: str | None = None
    name: str
    # ผู้ผลิต/รุ่น (เฟส 8) — ไม่บังคับ แต่ฟอร์มมี helper แนะนำให้แยกชื่อรุ่นออกจากชื่ออุปกรณ์
    manufacturer: str | None = None
    model_number: str | None = None
    category_ids: list[uuid.UUID]
    item_type: str  # durable / consumable
    description: str | None = None
    # บังคับรูปอย่างน้อย 1 เฉพาะตอนสร้างใหม่ — ของเดิมจากทะเบียน 704 แถวยังไม่มีรูป
    # ถ้าไปบังคับใน EquipmentUpdate ด้วยจะแก้ข้อมูลของเดิมไม่ได้เลย
    image_urls: list[str] = Field(..., min_length=1)
    location: str | None = None
    unit: str | None = None
    # บังคับกรอกตอนสร้างใหม่ (ของทุกชิ้นต้องมีราคา) — ของเดิมในคลังที่ยังว่างไม่โดนบังคับย้อนหลัง
    # เพราะ EquipmentUpdate ยังปล่อยเป็น optional ไม่งั้นแก้ฟิลด์อื่นของแถวเดิม 128 แถวไม่ได้เลย
    unit_value: float = Field(..., gt=0)
    acquired_at: date  # วันที่ได้มา — บังคับเช่นกัน ฟอร์มใส่ค่าเริ่มต้นเป็นวันนี้ให้
    useful_life_years: int | None = Field(None, gt=0)
    book_value_override: float | None = Field(None, ge=0)
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
    manufacturer: str | None = None
    model_number: str | None = None
    category_ids: list[uuid.UUID] | None = None
    description: str | None = None
    image_urls: list[str] | None = None
    location: str | None = None
    unit: str | None = None
    # ส่งมาเป็น null = "ไม่แก้ราคา" ไม่ใช่ "ล้างราคาทิ้ง" (ดู update_equipment) — ของทุกชิ้นต้องมีราคา
    unit_value: float | None = Field(None, gt=0)
    acquired_at: date | None = None
    useful_life_years: int | None = Field(None, gt=0)
    # ส่ง null ที่นี่ล้างค่าได้จริง = กลับไปใช้ค่าที่ระบบคำนวณ (ต่างจาก unit_value ด้านบนโดยตั้งใจ)
    book_value_override: float | None = Field(None, ge=0)
    quantity_total: int | None = None
    low_stock_threshold: int | None = None
    status: str | None = None
    is_borrowable: bool | None = None
    # เปลี่ยนสถานะเป็น action ที่ต้องอธิบายได้ (เฟส 8) — บังคับเฉพาะเมื่อ status เปลี่ยนจริง
    # ("ทำไมเครื่องนี้ถึงกลายเป็นซ่อมอยู่" ต้องตอบได้จาก audit ไม่ใช่เดาจากวันที่)
    status_reason: str | None = None
    # ค่าคุณภาพ (เฟส 10) — เปิด/ปิดติดตามและอายุการใช้งานที่ใช้คิด ใช้กับทั้งรุ่นเสมอ (ดู
    # equipment_service.update_equipment ที่ propagate ให้หน่วยอื่นในรุ่นเดียวกันด้วย find_group_members)
    quality_tracked: bool | None = None
    quality_life_years: int | None = Field(None, gt=0)
    # ประเมินคุณภาพใหม่ (ไม่บังคับ) เฉพาะตอนสถานะเปลี่ยนกลับเป็น available (ซ่อมเสร็จ) — เหตุผลไม่บังคับ
    # ต่างจากปุ่ม "ประเมินคุณภาพ" เดี่ยว ๆ ที่บังคับเหตุผลเสมอ
    quality_after: float | None = Field(None, ge=0, le=100)
    quality_reason: str | None = None

    _normalize_serial_number = field_validator("serial_number", mode="before")(_blank_sn_to_none)
    _normalize_code = field_validator("code", mode="before")(_blank_sn_to_none)

    # quality_tracked ลง Equipment.quality_tracked ซึ่งเป็นคอลัมน์ NOT NULL — ส่ง `null` มาตรง ๆ จะหลุด
    # exclude_unset (นับว่า "ส่งมา") แล้วไปตั้งค่า None ทับคอลัมน์นี้ตอน setattr กลายเป็น 500 IntegrityError
    # แทนที่จะเป็น 422 ที่อ่านเข้าใจ — "ไม่ต้องการแก้ค่านี้" ต้องไม่ส่ง field มาเลย (ค่า default None ของฟิลด์
    # นี้จึงไม่ถูกกระทบ เพราะ validator ทำงานเฉพาะตอน field ถูกส่งมาจริงเท่านั้น ไม่ทำงานตอนใช้ default)
    # แก้ตามรีวิวรอบ 4, M-g
    @field_validator("quality_tracked")
    @classmethod
    def _quality_tracked_not_null(cls, v: bool | None) -> bool:
        if v is None:
            raise ValueError(
                "quality_tracked ต้องเป็น true หรือ false เท่านั้น (ไม่ต้องการแก้ค่านี้ ไม่ต้องส่ง field นี้มา)"
            )
        return v


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
    # ราคา/วันที่ได้มาจากไฟล์ทะเบียน — แอดมินแก้ในร่างได้ ไหลเข้าเฉพาะแถวที่ยังว่างใน DB (ดู commit_import)
    unit_value: float | None = None
    acquired_at: date | None = None
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
    manufacturer: str | None = None
    model_number: str | None = None
    item_type: str | None = None
    category_ids: list[uuid.UUID] | None = None
    location: str | None = None
    description: str | None = None
    image_urls: list[str] | None = None
    unit: str | None = None
    # ทะเบียน/การเงิน — superadmin เท่านั้น (bulk_update_equipment เช็ค FINANCE_FIELDS) · validator เดียวกับ
    # EquipmentUpdate · 21 ก.ย. 69 เพิ่ม 3 ฟิลด์หลัง: หน้าเว็บส่งมาตลอดแต่ schema ไม่มี pydantic เลยทิ้งเงียบ ๆ
    # (แก้วันที่ได้มา/อายุการใช้งานหลายรายการแล้ว "บันทึกสำเร็จ" ทั้งที่ไม่มีอะไรเปลี่ยน)
    unit_value: float | None = Field(None, gt=0)
    acquired_at: date | None = None
    useful_life_years: int | None = Field(None, gt=0)
    book_value_override: float | None = Field(None, ge=0)
    low_stock_threshold: int | None = None
    status: str | None = None
    is_borrowable: bool | None = None
    # ค่าคุณภาพ (เฟส 10) — เปิด/ปิดติดตามคุณภาพหรือแก้อายุการใช้งานพร้อมกันหลายหน่วยได้ ปลอดภัยเหมือนฟิลด์อื่น
    # ด้านบน (ไม่มี unique constraint) การประเมินค่าจริง (quality_baseline) แยกไปอยู่ใน BulkUpdateRequest
    # เพราะต้องบังคับเหตุผลคู่กัน (เหมือน status_reason) ไม่ใช่ฟิลด์ "แก้แล้วจบ" ธรรมดา
    quality_tracked: bool | None = None
    quality_life_years: int | None = Field(None, gt=0)


class BulkUpdateRequest(BaseModel):
    equipment_ids: list[uuid.UUID] = Field(..., min_length=1)
    update: EquipmentBulkUpdate
    # บังคับเมื่อ update.status ถูกส่งมา (เฟส 8) — เหตุผลเดียวใช้กับทุกแถวที่เลือก เหมือน bulk_retire
    status_reason: str | None = None
    # ประเมินคุณภาพทั้งชุดพร้อมกัน (ไม่บังคับ) — ข้ามแถวที่ไม่ได้เปิด quality_tracked อย่างเงียบ ๆ
    # quality_reason บังคับก็ต่อเมื่อส่ง quality_baseline มา (ดู equipment_service.bulk_update_equipment)
    quality_baseline: float | None = Field(None, ge=0, le=100)
    quality_reason: str | None = None


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
