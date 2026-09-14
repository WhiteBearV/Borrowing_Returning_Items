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


class DashboardSummaryResponse(BaseModel):
    pending_requests: int
    overdue_requests: int
    low_stock_items: int
    active_borrows: int
    equipment_borrowed_out: int
    equipment_counts: EquipmentCounts
    consumed_value_this_month: float
    consumed_value_this_year: float
    # ของที่ยังกรอกข้อมูลทะเบียนไม่ครบ — ใช้เป็นทางเข้าไล่เติมให้ครบ (ของทุกชิ้นต้องมีราคา/วันที่ได้มา)
    missing_price_items: int = 0
    missing_acquired_at_items: int = 0
    # ภาพรวมผู้ใช้ (8 ก.ย. 69) — แอดมินต้องตอบได้ว่าระบบมีคนใช้จริงกี่คน สาขาไหนบ้าง
    users_total: int = 0
    users_students: int = 0
    users_staff: int = 0
    users_pending_approval: int = 0
    users_by_major: list[MajorUserCount] = []


class UtilizationRow(BaseModel):
    """สถิติความคุ้มค่าของอุปกรณ์ 1 หน่วย — ทุกค่าคำนวณสดจาก borrow_items ไม่มีคอลัมน์เก็บเพิ่ม"""
    equipment_id: uuid.UUID
    code: str
    name: str
    item_type: str
    status: str
    unit_value: float | None = None
    acquired_at: date | None = None
    borrow_count: int = 0
    days_borrowed: int = 0            # วันรวมที่ออกจากคลัง (นับขั้นต่ำ 1 วันต่อการยืม 1 ครั้ง)
    owned_days: int | None = None     # วันที่ครอบครองตั้งแต่ acquired_at (None = ยังไม่กรอกวันที่ได้มา)
    utilization_rate: float | None = None  # days_borrowed ÷ owned_days (0–1) — None เมื่อไม่รู้วันที่ได้มา
    cost_per_day: float | None = None      # unit_value ÷ days_borrowed — None เมื่อไม่เคยยืม/ไม่มีราคา
    rating: str                            # good / fair / idle


class UtilizationResponse(BaseModel):
    rows: list[UtilizationRow]
    never_borrowed_count: int = 0
    never_borrowed_value: float = 0     # มูลค่ารวมของที่ซื้อมาแล้วไม่เคยถูกยืมเลย — ตัวเลขที่ใช้ต่อรองงบ
    total_days_borrowed: int = 0


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
