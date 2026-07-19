import uuid
from datetime import date, datetime

from pydantic import BaseModel


class CategoryResponse(BaseModel):
    id: uuid.UUID
    name: str
    created_at: datetime

    model_config = {"from_attributes": True}


class CategoryCreate(BaseModel):
    name: str


class EquipmentResponse(BaseModel):
    id: uuid.UUID
    code: str
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

    model_config = {"from_attributes": True}


class HolderInfo(BaseModel):
    """ผู้ที่กำลังครอบครองอุปกรณ์ชิ้นนี้อยู่ (ยืมแล้วยังไม่คืน)"""
    holder_name: str
    due_date: date | None
    quantity: int


class EquipmentDetailResponse(EquipmentResponse):
    holders: list[HolderInfo]


class EquipmentCreate(BaseModel):
    code: str
    name: str
    category_ids: list[uuid.UUID]
    item_type: str  # durable / consumable
    description: str | None = None
    image_urls: list[str] = []
    location: str | None = None
    unit: str | None = None
    unit_value: float | None = None
    quantity_total: int = 1
    low_stock_threshold: int | None = None
    is_borrowable: bool = True


class EquipmentUpdate(BaseModel):
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


class ImportRowIn(BaseModel):
    """หนึ่งบรรทัดในร่างนำเข้าที่แอดมินตรวจ/แก้แล้ว — ส่งกลับมาเฉพาะบรรทัดที่เลือกบันทึกจริง

    แก้ได้ทุกช่องเหมือนฟอร์มเพิ่มอุปกรณ์ทีละชิ้น (หมวดหมู่/รูป/คำอธิบาย/ประเภท/จำนวน)
    เพราะไฟล์ทะเบียนมีแค่ชื่อ-เลข-สถานะ ที่เหลือแอดมินต้องเติมเองในร่าง
    """
    code: str
    action: str  # new / update / retire
    name: str
    location: str | None = None
    status: str
    item_type: str = "durable"  # durable / material / consumable
    quantity: int = 1
    unit: str | None = None
    categories: list[str] = []  # ชื่อหมวดหมู่ (สร้างให้ถ้ายังไม่มี) — ว่าง = ใช้ที่ระบบเดาจากชื่อ
    description: str | None = None
    image_urls: list[str] = []
    reason: str | None = None  # เหตุผลปลดระวาง (เฉพาะ action=retire)


class ImportCommitRequest(BaseModel):
    filename: str | None = None
    rows: list[ImportRowIn]


class PaginatedEquipment(BaseModel):
    items: list[EquipmentResponse]
    total: int
    page: int
    page_size: int
