import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.auth import NonBlank


class FineRateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    amount_per_day: float
    is_default: bool
    model_count: int = 0  # จำนวนรุ่นที่ใช้ป้ายนี้ (ชื่อ+ประเภทเดียวกัน = รุ่นเดียว)


class FineRateCreate(BaseModel):
    name: NonBlank = Field(..., max_length=100)
    amount_per_day: Decimal = Field(..., ge=0, max_digits=10, decimal_places=2)
    is_default: bool = False


class FineRateUpdate(BaseModel):
    name: NonBlank | None = Field(None, max_length=100)
    amount_per_day: Decimal | None = Field(None, ge=0, max_digits=10, decimal_places=2)
    is_default: bool | None = None  # ส่ง true = ตั้งเป็นค่าเริ่มต้น (ป้ายเดิมถูกปลดอัตโนมัติ) · ปลดค่าเริ่มต้นตรง ๆ ไม่ได้
