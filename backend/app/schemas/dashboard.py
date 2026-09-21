import uuid
from datetime import date, datetime

from pydantic import BaseModel


class EquipmentCounts(BaseModel):
    durable: int
    material: int
    consumable: int
    total: int


class MajorUserCount(BaseModel):
    """จำนวนผู้ใช้แยกตามสาขา — major เป็น None ได้ (บัญชีเจ้าหน้าที่/ของเก่าที่ไม่ได้ระบุสาขา)"""
    major: str | None = None
    count: int


class YearLevelCount(BaseModel):
    """จำนวนผู้ใช้แยกตามชั้นปี (เฟส 10) — ป้ายภาษาไทยจาก app.utils.study_year (จุดเดียว)"""
    # คีย์แบบเครื่องอ่าน — "1".."4" / "retained" (ตกค้าง) / "staff" (บุคลากร) / "unknown" (นักศึกษาที่
    # enrollment_year เป็น None) หน้าเว็บใช้ค่านี้ต่อ URL query (?year_group=) แทนการแกะป้ายภาษาไทยเอง
    group: str
    label: str          # "ปีที่ 1" / "ตกค้าง" / "บุคลากร" / "ไม่ทราบชั้นปี"
    count: int


class DashboardSummaryResponse(BaseModel):
    pending_requests: int
    overdue_requests: int
    low_stock_items: int
    active_borrows: int
    equipment_borrowed_out: int
    equipment_counts: EquipmentCounts
    # มูลค่าอุปกรณ์ทุกประเภทที่ถูกยืมออก (ตามวันที่อนุมัติ, ราคา ณ วันอนุมัติ) — ไม่ใช่ต้นทุนที่เสียไป
    borrowed_value_this_month: float
    borrowed_value_this_year: float
    # ของที่ยังกรอกข้อมูลทะเบียนไม่ครบ — ใช้เป็นทางเข้าไล่เติมให้ครบ (ของทุกชิ้นต้องมีราคา/วันที่ได้มา)
    missing_price_items: int = 0
    missing_acquired_at_items: int = 0
    # ภาพรวมผู้ใช้ (8 ก.ย. 69) — แอดมินต้องตอบได้ว่าระบบมีคนใช้จริงกี่คน สาขาไหนบ้าง
    users_total: int = 0
    users_students: int = 0
    users_staff: int = 0
    users_pending_approval: int = 0
    users_by_major: list[MajorUserCount] = []
    # ภาพรวมชั้นปี (เฟส 10) — รวมกลุ่มตกค้างแยกจากปี 1-4
    users_by_year: list[YearLevelCount] = []
    # การ์ดคุณภาพอุปกรณ์ (เฟส 10) — เฉพาะรุ่นที่เปิดติดตาม (quality_tracked) เท่านั้น
    quality_low_count: int = 0          # ประเมินแล้วและต่ำกว่า quality_low_threshold
    quality_unassessed_count: int = 0   # เปิดติดตามแล้วแต่ยังไม่เคยประเมิน


class UtilizationRow(BaseModel):
    """สถิติความคุ้มค่าของอุปกรณ์ 1 หน่วย — ทุกค่าคำนวณสดจาก borrow_items ไม่มีคอลัมน์เก็บเพิ่ม"""
    equipment_id: uuid.UUID
    code: str
    name: str
    item_type: str
    status: str
    unit_value: float | None = None
    acquired_at: date | None = None
    borrow_count: int = 0             # สะสม = ยืมทั้งหมด · เลือกช่วง = ยืมใหม่ในช่วงนั้น
    days_borrowed: int = 0            # วันรวมที่ออกจากคลัง (นับขั้นต่ำ 1 วันต่อการยืม 1 ครั้ง)
    tracked_days: int = 1             # ช่วงที่วัดผล: ตั้งแต่ของเข้าระบบ (หรือวันที่ได้มาถ้าช้ากว่า) ถึงวันนี้
    utilization_rate: float | None = None  # days_borrowed ÷ tracked_days (0–1)
    # ค่าเสื่อมต่อวัน (ราคา − ซาก) ÷ อายุการใช้งาน = ต้นทุนจริงต่อวันถ้าถูกใช้ทุกวัน · None = ไม่มีราคา
    daily_depreciation: float | None = None
    # ค่าเสื่อมที่เกิดในช่วงวัด ÷ วันที่ถูกยืมจริง = ต้นทุนต่อวันใช้งาน (รวมต้นทุนวันที่จอดเฉย ๆ ด้วย)
    # เดิมเป็น "ราคาซื้อทั้งก้อน ÷ วันที่ยืม" (เครื่อง 3.8 แสนยืม 2 วัน = 190,888 บ./วัน) ผิดหลักเพราะเอามูลค่า
    # ตลอดอายุมาหารการใช้แค่ไม่กี่วัน — None เมื่อไม่เคยยืม/ไม่มีราคา
    cost_per_use_day: float | None = None
    rating: str                            # good / fair / low (เคยยืมแต่ใช้น้อย) / idle (ไม่เคยถูกยืม)


class UtilizationMonth(BaseModel):
    """สรุป 1 เดือนปฏิทิน — ใช้เทียบว่าเดือนไหนใช้ของเยอะ/น้อย"""
    month: str                  # "YYYY-MM"
    new_borrows: int = 0        # ยืมใหม่ (อนุมัติ) ในเดือนนั้น
    days_borrowed: int = 0      # วันที่ของออกจากคลังรวม ตัดเฉพาะส่วนที่อยู่ในเดือนนั้น
    borrowed_value: float = 0   # มูลค่าที่ถูกยืมออก — นิยามเดียวกับการ์ด Dashboard


class UtilizationResponse(BaseModel):
    rows: list[UtilizationRow]
    never_borrowed_count: int = 0
    never_borrowed_value: float = 0     # มูลค่ารวมของที่ซื้อมาแล้วไม่เคยถูกยืมเลย — ตัวเลขที่ใช้ต่อรองงบ
    total_days_borrowed: int = 0
    # ฐานที่ใช้คำนวณ — ส่งให้หน้าเว็บเขียนคำอธิบายสูตรจากค่าจริง (settings/เกณฑ์เปลี่ยนแล้วข้อความไม่ค้าง)
    depreciation_years_default: int = 5
    salvage_value: float = 1
    good_threshold: float = 0.30
    fair_threshold: float = 0.05
    date_from: date | None = None      # ช่วงที่เลือก (None = สะสมตั้งแต่เข้าระบบ)
    date_to: date | None = None
    monthly: list[UtilizationMonth] = []   # ทุกเดือนตั้งแต่มีการยืม ไม่ขึ้นกับช่วงที่เลือก


class FineRow(BaseModel):
    """ค่าปรับ 1 รายการ (= อุปกรณ์ 1 ชิ้นในคำขอ 1 ใบ) — ทุกตัวเลข freeze ไว้ตั้งแต่วันรับคืน"""
    item_id: uuid.UUID
    request_id: uuid.UUID
    request_code: str
    student_name: str | None = None
    student_identifier: str | None = None
    equipment_name: str | None = None
    equipment_code: str | None = None
    condition_on_return: str | None = None
    due_date: date | None = None
    returned_at: datetime | None = None
    days_late: int = 0
    late_amount: float = 0
    damage_amount: float = 0
    total: float = 0
    status: str                         # unpaid / paid / waived
    waived_by_name: str | None = None
    waived_reason: str | None = None
    basis: dict | None = None           # ที่มาของตัวเลข (อัตรา/ผ่อนผัน/เพดาน/มูลค่าตามบัญชี)


class FineSummaryResponse(BaseModel):
    rows: list[FineRow]
    unpaid_total: float = 0
    paid_total: float = 0
    waived_total: float = 0
    unpaid_count: int = 0
    paid_count: int = 0
    waived_count: int = 0
