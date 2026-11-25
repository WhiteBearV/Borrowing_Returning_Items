import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.auth import NonBlank


class StocktakeLocation(BaseModel):
    location: str
    count: int  # ครุภัณฑ์/วัสดุใช้ซ้ำที่ทะเบียนบอกว่าอยู่ห้องนี้ (ไม่รวมปลดระวาง)
    open_round_id: uuid.UUID | None = None


class RoomItem(BaseModel):
    """ของที่ทะเบียนบอกว่าอยู่ห้องนี้ — ดูคร่าว ๆ ก่อนตรวจจริง (ไม่เปิดรอบ ไม่เขียนอะไร)"""
    id: uuid.UUID
    code: str
    name: str
    asset_number: str | None
    serial_number: str | None
    location_detail: str | None = None
    status: str
    holder_name: str | None = None  # ถูกยืมอยู่ = ชื่อผู้ยืม
    due_date: date | None = None


class StocktakeRoundCreate(BaseModel):
    location: NonBlank


class StocktakeScanRequest(BaseModel):
    """สิ่งที่สแกนได้ — QR ของระบบให้ equipment_id · บาร์โค้ด/พิมพ์เอง ให้ code (รหัสอุปกรณ์หรือเลขครุภัณฑ์)"""
    equipment_id: uuid.UUID | None = None
    code: str | None = Field(None, max_length=100)

    @model_validator(mode="after")
    def _one_of(self) -> "StocktakeScanRequest":
        if not self.equipment_id and not (self.code and self.code.strip()):
            raise ValueError("equipment_id or code is required")
        return self


# สภาพตามแบบรายงานทะเบียนคุมทรัพย์สิน — ลำดับเดียวกับคอลัมน์ในเอกสาร
CONDITIONS = ("normal", "damaged", "deteriorated", "lost", "wrong_category")
Condition = Literal["normal", "damaged", "deteriorated", "lost", "wrong_category"]


class StocktakeConditionRequest(BaseModel):
    """ติ๊กสภาพ 1 ชิ้น (หลังสแกน หรือกดจากรายการ) — ไม่ใช่ "ปกติ" ต้องมีหมายเหตุเสมอ"""
    condition: Condition
    note: str | None = Field(None, max_length=2000)

    @model_validator(mode="after")
    def _note_required(self) -> "StocktakeConditionRequest":
        self.note = (self.note or "").strip() or None
        if self.condition != "normal" and not self.note:
            raise ValueError("กรุณาใส่หมายเหตุเมื่อสภาพไม่ใช่ปกติ")
        return self


class StocktakeFinishRequest(BaseModel):
    note: str | None = Field(None, max_length=2000)


class StocktakeItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    equipment_id: uuid.UUID | None
    equipment_code: str
    equipment_name: str
    asset_number: str | None
    asset_name: str | None = None  # ชื่อตามบัญชี — ใบตรวจพิมพ์ช่องนี้ (0059)
    result: str
    from_location: str | None
    location_detail: str | None = None  # ตำแหน่งในห้องปัจจุบัน (ตู้/ชั้น)
    condition: str | None = None  # ว่าง = ยังไม่ได้ติ๊กสภาพ
    note: str | None = None
    unit_value: float | None = None
    acquired_at: date | None = None
    scanned_at: datetime | None


class StocktakeRoundSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    location: str
    started_at: datetime
    finished_at: datetime | None
    started_by_name: str | None = None
    counts: dict[str, int] = {}


class StocktakeRoundResponse(StocktakeRoundSummary):
    note: str | None
    items: list[StocktakeItemResponse]


class StocktakeScanResponse(BaseModel):
    outcome: str  # found / moved_here / already
    item: StocktakeItemResponse
    round: StocktakeRoundResponse
