import uuid

from pydantic import BaseModel, Field


class BundleItemRequest(BaseModel):
    equipment_id: uuid.UUID
    quantity: int = Field(1, gt=0)


class BundleCreate(BaseModel):
    name: str
    description: str | None = None
    is_active: bool = True
    trigger_equipment_id: uuid.UUID | None = None
    items: list[BundleItemRequest] = Field(..., min_length=1)


class BundleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    is_active: bool | None = None
    trigger_equipment_id: uuid.UUID | None = None
    # ส่ง items มาเมื่อไหร่ = แทนที่รายการทั้งชุด (แก้ทีละชิ้นไม่คุ้มกับความซับซ้อน)
    items: list[BundleItemRequest] | None = None


class BundleItemResponse(BaseModel):
    equipment_id: uuid.UUID
    quantity: int
    equipment_name: str | None = None
    equipment_code: str | None = None
    item_type: str | None = None
    unit: str | None = None
    quantity_available: int | None = None
    is_borrowable: bool | None = None

    model_config = {"from_attributes": True}


class BundleResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    is_active: bool
    trigger_equipment_id: uuid.UUID | None = None
    trigger_equipment_name: str | None = None
    items: list[BundleItemResponse] = []

    model_config = {"from_attributes": True}
