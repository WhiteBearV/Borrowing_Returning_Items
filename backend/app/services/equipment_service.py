import os
import uuid

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.borrow_item import BorrowItem
from app.models.borrow_request import BorrowRequest
from app.models.equipment import Equipment, equipment_category_links
from app.models.equipment_category import EquipmentCategory
from app.models.user import User
from app.schemas.equipment import (
    CategoryCreate,
    CategoryResponse,
    EquipmentCreate,
    EquipmentResponse,
    EquipmentUpdate,
    HolderInfo,
    PaginatedEquipment,
)
from app.core.config import settings
from app.utils.qrcode_gen import generate_qr_png

ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


async def save_image(file: UploadFile) -> str:
    """บันทึกไฟล์รูปอุปกรณ์ลง UPLOAD_DIR แล้วคืน path relative (/uploads/<uuid>.<ext>) สำหรับเก็บใน image_url"""
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_IMAGE_EXT:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported image type.")
    contents = await file.read()
    if len(contents) > 5 * 1024 * 1024:  # จำกัด 5MB กันไฟล์ใหญ่เกิน
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Image too large (max 5MB).")
    filename = f"{uuid.uuid4().hex}{ext}"
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    with open(os.path.join(settings.UPLOAD_DIR, filename), "wb") as f:
        f.write(contents)
    return f"/uploads/{filename}"


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
        query = query.where(Equipment.categories.any(EquipmentCategory.id == category_id))
    if item_type:
        query = query.where(Equipment.item_type == item_type)
    if filter_status:
        query = query.where(Equipment.status == filter_status)
    if search:
        query = query.where(Equipment.name.ilike(f"%{search}%"))

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar() or 0

    # เรียงของที่ยืมได้ (status=available และยังเหลือ) ไว้หน้า ที่เหลือกองท้าย แล้วเรียงตามชื่อ
    borrowable = ((Equipment.status == "available") & (Equipment.quantity_available > 0))
    query = query.order_by(borrowable.desc(), Equipment.name)

    query = query.options(selectinload(Equipment.categories))
    result = await db.execute(query.offset((page - 1) * page_size).limit(page_size))
    items = list(result.scalars().all())
    return PaginatedEquipment(items=items, total=total, page=page, page_size=page_size)  # type: ignore


async def get_equipment(db: AsyncSession, equipment_id: uuid.UUID) -> Equipment:
    result = await db.execute(
        select(Equipment).where(Equipment.id == equipment_id).options(selectinload(Equipment.categories))
    )
    eq = result.scalar_one_or_none()
    if not eq:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Equipment not found.")
    return eq


async def get_holders(db: AsyncSession, equipment_id: uuid.UUID) -> list[HolderInfo]:
    """คืนรายชื่อผู้ที่ยืมอุปกรณ์ชิ้นนี้อยู่แต่ยังไม่คืน เพื่อให้นักศึกษาเห็นผู้ครอบครองในขณะนั้น"""
    result = await db.execute(
        select(User.full_name, BorrowItem.extended_due_date, BorrowRequest.due_date, BorrowItem.quantity)
        .join(BorrowRequest, BorrowItem.borrow_request_id == BorrowRequest.id)
        .join(User, BorrowRequest.student_id == User.id)
        .where(
            BorrowItem.equipment_id == equipment_id,
            BorrowItem.returned.is_(False),
            BorrowRequest.status == "approved",
        )
    )
    return [
        HolderInfo(holder_name=name, due_date=ext or due, quantity=qty)
        for name, ext, due, qty in result.all()
    ]


async def _resolve_categories(db: AsyncSession, category_ids: list[uuid.UUID]) -> list[EquipmentCategory]:
    """ดึง category objects ตาม id — เออเรอร์ถ้ามี id ที่ไม่มีจริง"""
    result = await db.execute(select(EquipmentCategory).where(EquipmentCategory.id.in_(category_ids)))
    cats = list(result.scalars().all())
    if len(cats) != len(set(category_ids)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid category id.")
    return cats


async def create_equipment(db: AsyncSession, body: EquipmentCreate) -> Equipment:
    existing = await db.execute(select(Equipment).where(Equipment.code == body.code))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Equipment code already exists.")
    data = body.model_dump(exclude={"category_ids"})
    data["image_url"] = data["image_urls"][0] if data.get("image_urls") else None  # cover = รูปแรก
    eq = Equipment(**data)
    eq.categories = await _resolve_categories(db, body.category_ids)
    eq.quantity_available = body.quantity_total
    db.add(eq)
    await db.commit()
    return await get_equipment(db, eq.id)


async def update_equipment(db: AsyncSession, equipment_id: uuid.UUID, body: EquipmentUpdate) -> Equipment:
    eq = await get_equipment(db, equipment_id)
    for field, value in body.model_dump(exclude_none=True, exclude={"category_ids"}).items():
        setattr(eq, field, value)
    if body.image_urls is not None:
        eq.image_url = body.image_urls[0] if body.image_urls else None  # sync cover
    if body.category_ids is not None:
        eq.categories = await _resolve_categories(db, body.category_ids)
    await db.commit()
    return await get_equipment(db, equipment_id)


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


async def update_category(db: AsyncSession, category_id: uuid.UUID, body: CategoryCreate) -> EquipmentCategory:
    """เปลี่ยนชื่อหมวดหมู่ — กันชื่อซ้ำกับหมวดอื่น"""
    cat = (await db.execute(select(EquipmentCategory).where(EquipmentCategory.id == category_id))).scalar_one_or_none()
    if not cat:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found.")
    dup = (await db.execute(
        select(EquipmentCategory).where(EquipmentCategory.name == body.name, EquipmentCategory.id != category_id)
    )).scalar_one_or_none()
    if dup:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Category already exists.")
    cat.name = body.name
    await db.commit()
    await db.refresh(cat)
    return cat


async def delete_category(db: AsyncSession, category_id: uuid.UUID) -> None:
    """ลบหมวดหมู่ — ห้ามลบถ้ายังมีอุปกรณ์ผูกอยู่ (ต้องย้ายอุปกรณ์ออกก่อน)"""
    cat = (await db.execute(select(EquipmentCategory).where(EquipmentCategory.id == category_id))).scalar_one_or_none()
    if not cat:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found.")
    count = (await db.execute(
        select(func.count()).select_from(equipment_category_links).where(equipment_category_links.c.category_id == category_id)
    )).scalar() or 0
    if count > 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"ยังมีอุปกรณ์ {count} ชิ้นในหมวดนี้ ย้ายออกก่อนลบ")
    await db.delete(cat)
    await db.commit()
