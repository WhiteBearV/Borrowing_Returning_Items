import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.bundle import Bundle, BundleItem
from app.models.equipment import Equipment
from app.models.user import User
from app.schemas.bundle import BundleCreate, BundleResponse, BundleUpdate
from app.services import audit_service


async def _load(db: AsyncSession, bundle_id: uuid.UUID) -> Bundle:
    result = await db.execute(
        select(Bundle)
        # eager-load อุปกรณ์ในชุด — response ใช้ชื่อ/หน่วย/ของคงเหลือ ถ้า lazy-load จะพังใต้ async
        .options(
            selectinload(Bundle.items).selectinload(BundleItem.equipment),
            selectinload(Bundle.trigger_equipment),
        )
        .where(Bundle.id == bundle_id)
    )
    bundle = result.scalar_one_or_none()
    if not bundle:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bundle not found.")
    return bundle


async def _replace_items(db: AsyncSession, bundle: Bundle, items: list) -> None:
    """แทนที่รายการในชุดทั้งหมด พร้อมตรวจว่าอุปกรณ์มีจริงและยืมออกได้

    ไม่เช็คสต็อกตรงนี้ — ชุดเป็นแค่แม่แบบ ของอาจหมดชั่วคราวแล้วกลับมามีได้
    สต็อกจริงถูกเช็คตอนสร้างคำขอยืมใน borrow_service อยู่แล้ว
    """
    eq_ids = [i.equipment_id for i in items]
    if len(set(eq_ids)) != len(eq_ids):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Duplicate equipment in bundle.")
    if bundle.trigger_equipment_id in eq_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Trigger equipment cannot also be a bundle item.",
        )

    found = (await db.execute(select(Equipment).where(Equipment.id.in_(eq_ids)))).scalars().all()
    found_map = {e.id: e for e in found}
    for eq_id in eq_ids:
        eq = found_map.get(eq_id)
        if not eq:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Equipment {eq_id} not found.")
        if not eq.is_borrowable:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Equipment '{eq.name}' is not lendable.",
            )

    bundle.items.clear()
    for i in items:
        bundle.items.append(BundleItem(equipment_id=i.equipment_id, quantity=i.quantity))


async def list_bundles(db: AsyncSession, active_only: bool) -> list[BundleResponse]:
    """รายชุดทั้งหมด — นักศึกษาเห็นเฉพาะชุดที่เปิดใช้งาน"""
    query = select(Bundle).options(
        selectinload(Bundle.items).selectinload(BundleItem.equipment),
        selectinload(Bundle.trigger_equipment),
    )
    if active_only:
        query = query.where(Bundle.is_active == True)  # noqa: E712
    result = await db.execute(query.order_by(Bundle.name))
    return [BundleResponse.model_validate(b) for b in result.scalars().all()]


async def create_bundle(db: AsyncSession, admin: User, body: BundleCreate) -> BundleResponse:
    """สร้างชุดอุปกรณ์ใหม่ (admin)"""
    bundle = Bundle(name=body.name, description=body.description, is_active=body.is_active,
                    trigger_equipment_id=body.trigger_equipment_id)
    await _replace_items(db, bundle, body.items)
    db.add(bundle)
    await db.flush()
    await audit_service.log_action(db, admin, "create_bundle", "bundles", bundle.id,
                                   {"name": bundle.name, "items": len(body.items)})
    await db.commit()
    return BundleResponse.model_validate(await _load(db, bundle.id))


async def update_bundle(
    db: AsyncSession, admin: User, bundle_id: uuid.UUID, body: BundleUpdate
) -> BundleResponse:
    """แก้ไขชุด — ส่ง items มาเมื่อไหร่ถือว่าแทนที่รายการทั้งชุด"""
    bundle = await _load(db, bundle_id)
    for field in ("name", "description", "is_active"):
        value = getattr(body, field)
        if value is not None:
            setattr(bundle, field, value)
    # ponytail: ฟอร์มแอดมินส่งค่าเต็มทุกครั้ง จึง set ตรง ๆ ให้ยกเลิกตัวกระตุ้น (null) ได้ด้วย
    bundle.trigger_equipment_id = body.trigger_equipment_id
    if body.items is not None:
        if not body.items:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Bundle must have at least 1 item.")
        await _replace_items(db, bundle, body.items)

    await audit_service.log_action(db, admin, "update_bundle", "bundles", bundle.id, {"name": bundle.name})
    await db.commit()
    return BundleResponse.model_validate(await _load(db, bundle_id))


async def delete_bundle(db: AsyncSession, admin: User, bundle_id: uuid.UUID) -> None:
    """ลบชุด — ลบได้เลยเพราะชุดไม่ผูกกับคำขอยืมที่เกิดขึ้นแล้ว"""
    bundle = await _load(db, bundle_id)
    name = bundle.name
    await db.delete(bundle)
    await audit_service.log_action(db, admin, "delete_bundle", "bundles", bundle_id, {"name": name})
    await db.commit()
