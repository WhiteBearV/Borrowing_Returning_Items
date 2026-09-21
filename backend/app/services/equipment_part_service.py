"""ชิ้นส่วน/การอัพเกรดของอุปกรณ์ — ติดตั้ง แก้ไข ถอดออก

แยกไฟล์จาก equipment_service.py (1000+ บรรทัดแล้ว) ตาม pattern เดียวกับ bundle_service.py
ที่เป็น domain ข้าง ๆ equipment เหมือนกัน

กฎเหล็ก: ทุกฟังก์ชันในไฟล์นี้ห้ามแตะ equipment.acquired_at / equipment.unit_value ของเครื่องหลัก
เพราะโจทย์คือ "อายุของเครื่องหลักกับของที่อัพเกรดต้องแยกจากกัน" — มูลค่ารวมคำนวณตอนอ่านแทน
"""
import uuid
from datetime import date

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.equipment_part import EquipmentPart
from app.models.user import User
from app.schemas.equipment import PartCreate, PartRemove, PartResponse, PartUpdate
from app.services import audit_service, equipment_service


async def _attach_replaced_names(db: AsyncSession, parts: list[EquipmentPart]) -> None:
    """เติมชื่อชิ้นที่ถูกแทนที่ (replaces_part_name) — หน้าเว็บเขียนไทม์ไลน์ "SSD 512GB (แทน SSD 256GB)"
    ได้โดยไม่ต้องรู้จัก id · ชิ้นที่อ้างถึงอาจถูกลบไปแล้ว (FK เป็น SET NULL) ก็แค่ไม่มีชื่อ
    """
    ids = {p.replaces_part_id for p in parts if p.replaces_part_id}
    if not ids:
        for p in parts:
            p.replaces_part_name = None
        return
    names = dict((await db.execute(
        select(EquipmentPart.id, EquipmentPart.name).where(EquipmentPart.id.in_(ids))
    )).all())
    for p in parts:
        p.replaces_part_name = names.get(p.replaces_part_id)


async def _attach_book_values(db: AsyncSession, parts: list[EquipmentPart]) -> None:
    """เติม book_value ให้ชิ้นส่วนด้วยสูตรเดียวกับเครื่องหลัก — EquipmentPart มี 3 attribute ที่
    equipment_service.book_value() ต้องใช้ (unit_value/acquired_at/useful_life_years) ครบอยู่แล้ว
    """
    if not parts:
        return
    years, salvage = await equipment_service._depreciation_settings(db)
    today = date.today()
    for p in parts:
        p.book_value = equipment_service.book_value(p, years, salvage, today)


async def list_parts(
    db: AsyncSession, equipment_id: uuid.UUID, include_removed: bool = True
) -> list[PartResponse]:
    """ชิ้นส่วนของอุปกรณ์ชิ้นนี้ — ที่ถอดออกแล้วยังคืนมาด้วยโดยค่าเริ่มต้น (เป็นประวัติการอัพเกรด)"""
    query = select(EquipmentPart).where(EquipmentPart.equipment_id == equipment_id)
    if not include_removed:
        query = query.where(EquipmentPart.removed_at.is_(None))
    # ชิ้นที่ยังติดตั้งอยู่ขึ้นก่อน แล้วเรียงตามวันที่ติดตั้งใหม่สุดไปเก่าสุด
    rows = list((await db.execute(query)).scalars().all())
    rows.sort(key=lambda p: (p.removed_at is not None, -(p.acquired_at or date.min).toordinal()))
    await _attach_book_values(db, rows)
    await _attach_replaced_names(db, rows)
    return [PartResponse.model_validate(p, from_attributes=True) for p in rows]


async def parts_summary(db: AsyncSession, equipment_id: uuid.UUID) -> dict[str, float | None]:
    """มูลค่ารวมของชิ้นส่วนที่ยังติดตั้งอยู่ — ใช้โชว์ "มูลค่ารวมทั้งเครื่อง" ในหน้ารายละเอียด
    ชิ้นที่ถอดออกแล้วไม่นับ เพราะไม่ได้อยู่กับเครื่องแล้ว
    """
    rows = [p for p in (await db.execute(
        select(EquipmentPart).where(
            EquipmentPart.equipment_id == equipment_id, EquipmentPart.removed_at.is_(None))
    )).scalars().all()]
    await _attach_book_values(db, rows)
    return {
        "parts_count": len(rows),
        "parts_value": float(sum(float(p.unit_value or 0) for p in rows)),
        "parts_book_value": float(sum(p.book_value or 0 for p in rows)),
    }


async def _get_part(db: AsyncSession, equipment_id: uuid.UUID, part_id: uuid.UUID) -> EquipmentPart:
    """อ่านชิ้นส่วนโดยยืนยันว่าอยู่กับอุปกรณ์ตัวที่ระบุจริง — กันแก้ชิ้นส่วนข้ามเครื่องผ่าน URL ที่เดาเอา"""
    part = (await db.execute(
        select(EquipmentPart).where(
            EquipmentPart.id == part_id, EquipmentPart.equipment_id == equipment_id)
    )).scalar_one_or_none()
    if not part:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Part not found.")
    return part


async def install_part(
    db: AsyncSession, admin: User, equipment_id: uuid.UUID, body: PartCreate
) -> PartResponse:
    """ติดตั้งชิ้นส่วนใหม่เข้ากับอุปกรณ์ — ไม่แตะอายุ/ราคาของเครื่องหลัก

    quality_after (ไม่บังคับ): ประเมินคุณภาพเครื่องหลักใหม่พร้อมกัน — จังหวะที่ 2 ของ 4 จังหวะที่ให้ประเมิน
    ใหม่ (ดู CLAUDE.md) มีผลเฉพาะเครื่องหลักที่เปิดติดตามคุณภาพอยู่ (quality_tracked) เท่านั้น
    """
    eq = await equipment_service.get_equipment(db, equipment_id, viewer=admin)  # 404 ถ้าไม่มีอุปกรณ์นี้
    # ชิ้นที่บอกว่า "มาแทน" ต้องเป็นชิ้นของเครื่องเดียวกัน — ไม่งั้นไทม์ไลน์ข้ามเครื่องกันมั่ว
    replaced = (await _get_part(db, equipment_id, body.replaces_part_id)
                if body.replaces_part_id else None)
    part_data = body.model_dump(exclude={"quality_after"})
    part = EquipmentPart(**part_data, equipment_id=equipment_id)
    db.add(part)
    await db.flush()
    # target_id เป็น "เครื่องหลัก" ไม่ใช่ part.id — ไม่งั้นเหตุการณ์นี้จะไม่โผล่ในไทม์ไลน์ประวัติของเครื่อง
    # ทั้งที่เป็นเหตุการณ์สำคัญที่สุดของมัน (ดู audit_service.list_logs)
    await audit_service.log_action(
        db, admin, "install_part", "equipment", equipment_id,
        {"code": eq.code, "part_id": str(part.id), "part_name": part.name,
         "unit_value": float(part.unit_value) if part.unit_value is not None else None,
         "acquired_at": part.acquired_at.isoformat() if part.acquired_at else None,
         **({"replaces_part": replaced.name} if replaced else {})},
    )
    await db.commit()
    await db.refresh(part)

    if body.quality_after is not None and eq.quality_tracked:
        await equipment_service.assess_quality(
            db, admin, equipment_id, body.quality_after,
            f"ติดตั้งชิ้นส่วน: {part.name}", event="install_part",
        )

    await _attach_book_values(db, [part])
    await _attach_replaced_names(db, [part])
    return PartResponse.model_validate(part, from_attributes=True)


async def update_part(
    db: AsyncSession, admin: User, equipment_id: uuid.UUID, part_id: uuid.UUID, body: PartUpdate
) -> PartResponse:
    """แก้ข้อมูลชิ้นส่วน (พิมพ์ผิด/เติมราคาทีหลัง) — diff ลง audit ด้วย helper ตัวเดียวกับอุปกรณ์"""
    eq = await equipment_service.get_equipment(db, equipment_id, viewer=admin)
    part = await _get_part(db, equipment_id, part_id)
    changed = body.model_dump(exclude_unset=True)
    field_diffs = audit_service.diff_fields(part, changed)
    for field, value in changed.items():
        setattr(part, field, value)
    await audit_service.log_action(
        db, admin, "update_part", "equipment", equipment_id,
        {"code": eq.code, "part_id": str(part.id), "part_name": part.name, "changes": field_diffs},
    )
    await db.commit()
    await db.refresh(part)
    await _attach_book_values(db, [part])
    await _attach_replaced_names(db, [part])
    return PartResponse.model_validate(part, from_attributes=True)


async def remove_part(
    db: AsyncSession, admin: User, equipment_id: uuid.UUID, part_id: uuid.UUID, body: PartRemove
) -> PartResponse:
    """ถอดชิ้นส่วนออก — บันทึกวันที่/เหตุผล ไม่ลบแถวทิ้ง (ประวัติการอัพเกรดต้องอยู่ตลอด)

    ไม่ตัด/คืนสต็อกในคลังใด ๆ — ระบบไม่รู้ว่าของที่ถอดออกถูกเก็บเข้าคลัง ทิ้ง หรือใส่เครื่องอื่นต่อ
    ถ้าจะเอาเข้าคลังให้แอดมินเพิ่มเป็นวัสดุแยกเองที่หน้าจัดการอุปกรณ์ (ตัดสินใจโดยคน ไม่ให้ระบบเดา)
    """
    eq = await equipment_service.get_equipment(db, equipment_id, viewer=admin)
    part = await _get_part(db, equipment_id, part_id)
    if part.removed_at is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ชิ้นส่วนนี้ถูกถอดออกไปแล้ว")
    part.removed_at = body.removed_at or date.today()
    part.removed_reason = body.reason
    await audit_service.log_action(
        db, admin, "remove_part", "equipment", equipment_id,
        {"code": eq.code, "part_id": str(part.id), "part_name": part.name,
         "removed_at": part.removed_at.isoformat(), "reason": body.reason},
    )
    await db.commit()
    await db.refresh(part)
    await _attach_book_values(db, [part])
    await _attach_replaced_names(db, [part])
    return PartResponse.model_validate(part, from_attributes=True)
