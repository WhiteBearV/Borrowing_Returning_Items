import uuid
from datetime import datetime

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
    category_id: uuid.UUID
    item_type: str
    description: str | None
    image_url: str | None
    location: str | None
    unit: str | None
    quantity_total: int
    quantity_available: int
    low_stock_threshold: int | None
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class EquipmentCreate(BaseModel):
    code: str
    name: str
    category_id: uuid.UUID
    item_type: str  # durable / consumable
    description: str | None = None
    image_url: str | None = None
    location: str | None = None
    unit: str | None = None
    quantity_total: int = 1
    low_stock_threshold: int | None = None


class EquipmentUpdate(BaseModel):
    name: str | None = None
    category_id: uuid.UUID | None = None
    description: str | None = None
    image_url: str | None = None
    location: str | None = None
    unit: str | None = None
    quantity_total: int | None = None
    low_stock_threshold: int | None = None
    status: str | None = None


class PaginatedEquipment(BaseModel):
    items: list[EquipmentResponse]
    total: int
    page: int
    page_size: int
