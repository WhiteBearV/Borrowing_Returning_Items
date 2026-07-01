import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.borrow_item import BorrowItem
from app.models.equipment import Equipment
from app.models.equipment_category import EquipmentCategory
from app.schemas.equipment import (
    CategoryCreate,
    CategoryResponse,
    EquipmentCreate,
    EquipmentResponse,
    EquipmentUpdate,
    PaginatedEquipment,
)
from app.utils.qrcode_gen import generate_qr_png


async def list_equipment(
    db: AsyncSession,
    page: int,
    page_size: int,
    category_id: uuid.UUID | None,
    item_type: str | None,
    filter_status: str | None,
    search: str | None,
) -> PaginatedEquipment:
    query = select(Equipment)
    if category_id:
        query = query.where(Equipment.category_id == category_id)
    if item_type:
        query = query.where(Equipment.item_type == item_type)
    if filter_status:
        query = query.where(Equipment.status == filter_status)
    if search:
        query = query.where(Equipment.name.ilike(f"%{search}%"))

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar() or 0

    result = await db.execute(query.offset((page - 1) * page_size).limit(page_size))
    items = list(result.scalars().all())
    return PaginatedEquipment(items=items, total=total, page=page, page_size=page_size)  # type: ignore


async def get_equipment(db: AsyncSession, equipment_id: uuid.UUID) -> Equipment:
    result = await db.execute(select(Equipment).where(Equipment.id == equipment_id))
    eq = result.scalar_one_or_none()
    if not eq:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Equipment not found.")
    return eq


async def create_equipment(db: AsyncSession, body: EquipmentCreate) -> Equipment:
    existing = await db.execute(select(Equipment).where(Equipment.code == body.code))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Equipment code already exists.")
    eq = Equipment(**body.model_dump())
    eq.quantity_available = body.quantity_total
    db.add(eq)
    await db.commit()
    await db.refresh(eq)
    return eq


async def update_equipment(db: AsyncSession, equipment_id: uuid.UUID, body: EquipmentUpdate) -> Equipment:
    eq = await get_equipment(db, equipment_id)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(eq, field, value)
    await db.commit()
    await db.refresh(eq)
    return eq


async def retire_equipment(db: AsyncSession, equipment_id: uuid.UUID) -> None:
    eq = await get_equipment(db, equipment_id)
    eq.status = "retired"
    await db.commit()


async def delete_equipment(db: AsyncSession, equipment_id: uuid.UUID) -> None:
    """ลบอุปกรณ์ออกจาก DB ถาวร — อนุญาตเฉพาะ retired และไม่มีประวัติการยืม"""
    eq = await get_equipment(db, equipment_id)
    if eq.status != "retired":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ต้องปลดระวางก่อนลบ")
    has_history = (await db.execute(
        select(func.count(BorrowItem.id)).where(BorrowItem.equipment_id == equipment_id)
    )).scalar() or 0
    if has_history:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ไม่สามารถลบได้ เนื่องจากมีประวัติการยืม")
    await db.delete(eq)
    await db.commit()


async def generate_qr(db: AsyncSession, equipment_id: uuid.UUID) -> bytes:
    eq = await get_equipment(db, equipment_id)
    return generate_qr_png(eq.code)


async def list_categories(db: AsyncSession) -> list[EquipmentCategory]:
    result = await db.execute(select(EquipmentCategory).order_by(EquipmentCategory.name))
    return list(result.scalars().all())


async def create_category(db: AsyncSession, body: CategoryCreate) -> EquipmentCategory:
    existing = await db.execute(select(EquipmentCategory).where(EquipmentCategory.name == body.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Category already exists.")
    cat = EquipmentCategory(name=body.name)
    db.add(cat)
    await db.commit()
    await db.refresh(cat)
    return cat
