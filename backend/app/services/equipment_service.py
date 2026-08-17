import os
import uuid
from datetime import date, datetime, time

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.audit_log import AuditLog
from app.models.borrow_item import BorrowItem
from app.models.borrow_request import BorrowRequest
from app.models.equipment import Equipment, equipment_category_links
from app.models.equipment_category import EquipmentCategory
from app.models.user import User
from app.schemas.equipment import (
    CategoryCreate,
    CategoryResponse,
    EquipmentCreate,
    EquipmentGroupDetailResponse,
    EquipmentGroupResponse,
    EquipmentResponse,
    EquipmentUnitSummary,
    EquipmentUpdate,
    HolderInfo,
    PaginatedEquipment,
    PaginatedEquipmentGroup,
)
from app.core.config import TZ, settings
from app.services import audit_service
from app.utils.qrcode_gen import generate_qr_png

ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024


def _normalize_name(name: str) -> str:
    """ตัด whitespace/ขึ้นบรรทัดหัวท้าย+ซ้ำ — เหมือน import_service._clean() เพื่อให้ทุกจุดที่เขียน name

    ผ่าน key เดียวกันเป๊ะ (ไฟล์นำเข้า clean ให้แล้ว แต่ฟอร์มแอดมินพิมพ์เองไม่เคย normalize)
    ป้องกันการยุบกลุ่มอุปกรณ์รุ่นเดียวกัน (ดู find_group_members) พลาดเพราะช่องว่างเกิน/เว้นวรรคไม่ตรงกัน
    """
    return " ".join(name.split())


async def find_group_members(db: AsyncSession, name: str, item_type: str) -> list[Equipment]:
    """คืนทุกแถวที่เป็นรุ่นเดียวกัน (name+item_type ตรงกันเป๊ะ) เรียงตาม code จากน้อยไปมาก

    ใช้เลือกหน่วยที่ว่างเลขต่ำสุดตอนยืม/อนุมัติ และยุบแสดงเป็นชิ้นเดียวตอน list —
    ผู้เรียกต้องเว้น consumable เอง (วัสดุสิ้นเปลืองเป็นก้อนเดียวต่อแถวอยู่แล้ว ไม่ควรยุบรวม)
    """
    result = await db.execute(
        select(Equipment)
        .where(Equipment.name == name, Equipment.item_type == item_type)
        .options(selectinload(Equipment.categories))
        .order_by(Equipment.code)
    )
    return list(result.scalars().all())


async def save_image(file: UploadFile) -> str:
    """บันทึกไฟล์รูปอุปกรณ์ลง UPLOAD_DIR แล้วคืน path relative (/uploads/<uuid>.<ext>) สำหรับเก็บใน image_url"""
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_IMAGE_EXT:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported image type.")
    # ต้องเช็คขนาดก่อน read() — endpoint อัปโหลดรูปโปรไฟล์เปิดให้นักศึกษาทุกคนยิงได้
    # ถ้าเช็คหลัง read() ไฟล์ขนาดกี่ GB ก็ถูกโหลดเข้า RAM จนหมดก่อนถึงบรรทัดตรวจ = worker ตาย
    if file.size is not None and file.size > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Image too large (max 5MB).")
    contents = await file.read()
    if len(contents) > MAX_IMAGE_BYTES:  # เผื่อกรณี .size เป็น None
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
        # ค้นได้ทั้งชื่อและรหัส (รหัสวัสดุ/เลขครุภัณฑ์) — พิมพ์บางส่วนก็เจอ
        kw = f"%{search.strip()}%"
        query = query.where(or_(Equipment.name.ilike(kw), Equipment.code.ilike(kw)))

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar() or 0

    # เรียงของที่ยืมได้ (status=available และยังเหลือ) ไว้หน้า ที่เหลือกองท้าย แล้วเรียงตามชื่อ
    borrowable = (
        Equipment.is_borrowable
        & (Equipment.status == "available")
        & (Equipment.quantity_available > 0)
    )
    query = query.order_by(borrowable.desc(), Equipment.name)

    query = query.options(selectinload(Equipment.categories))
    result = await db.execute(query.offset((page - 1) * page_size).limit(page_size))
    items = list(result.scalars().all())
    return PaginatedEquipment(items=items, total=total, page=page, page_size=page_size)  # type: ignore


def _is_eligible(eq: Equipment) -> bool:
    return eq.is_borrowable and eq.status == "available"


def _group_key(eq: Equipment) -> tuple:
    # consumable ไม่ยุบรวมแม้ชื่อซ้ำ (เป็นก้อนเดียวต่อแถวอยู่แล้ว) — คีย์เป็น id เดียวกันไม่ได้กับแถวอื่น
    return (eq.id,) if eq.item_type == "consumable" else (eq.name, eq.item_type)


def _build_group_response(rows: list[Equipment]) -> EquipmentGroupResponse:
    """ประกอบการ์ดยุบกลุ่ม — field แสดงผลอื่น ๆ ใช้ของหน่วยรหัสต่ำสุด (rows เรียงมาแล้ว)"""
    rep = rows[0]
    eligible = [r for r in rows if _is_eligible(r)]
    base = EquipmentResponse.model_validate(rep, from_attributes=True).model_dump()
    base["quantity_total"] = sum(r.quantity_total for r in rows)
    base["quantity_available"] = sum(r.quantity_available for r in eligible)
    # มีหน่วยว่างพร้อมยืมอย่างน้อย 1 ชิ้น = การ์ดนี้ "พร้อมให้ยืม" ไม่งั้น fallback ไปสถานะของตัวแทน
    if eligible:
        base["is_borrowable"] = True
        base["status"] = "available"
    return EquipmentGroupResponse(**base, unit_count=len(rows))


async def list_equipment_grouped(
    db: AsyncSession,
    page: int,
    page_size: int,
    category_id: uuid.UUID | None,
    item_type: str | None,
    filter_status: str | None,
    search: str | None,
) -> PaginatedEquipmentGroup:
    """เหมือน list_equipment แต่ยุบอุปกรณ์รุ่นเดียวกันหลายหน่วยเป็นการ์ดเดียว

    สเกลคลัง ≤100 รายการตาม CLAUDE.md — ดึงมาทั้งหมดแล้ว group/sort/paginate ด้วย Python พอ
    ไม่ต้องใช้ window function ให้ซับซ้อนเกินจำเป็น
    """
    query = select(Equipment)
    if category_id:
        query = query.where(Equipment.categories.any(EquipmentCategory.id == category_id))
    if item_type:
        query = query.where(Equipment.item_type == item_type)
    if filter_status:
        query = query.where(Equipment.status == filter_status)
    if search:
        kw = f"%{search.strip()}%"
        query = query.where(or_(Equipment.name.ilike(kw), Equipment.code.ilike(kw)))
    query = query.options(selectinload(Equipment.categories)).order_by(Equipment.code)

    rows = list((await db.execute(query)).scalars().all())

    groups: dict[tuple, list[Equipment]] = {}
    for eq in rows:
        groups.setdefault(_group_key(eq), []).append(eq)

    cards = [_build_group_response(members) for members in groups.values()]
    cards.sort(key=lambda c: (not (c.is_borrowable and c.status == "available" and c.quantity_available > 0), c.name))

    total = len(cards)
    start = (page - 1) * page_size
    page_items = cards[start:start + page_size]
    return PaginatedEquipmentGroup(items=page_items, total=total, page=page, page_size=page_size)


async def get_equipment(db: AsyncSession, equipment_id: uuid.UUID) -> Equipment:
    result = await db.execute(
        select(Equipment).where(Equipment.id == equipment_id).options(selectinload(Equipment.categories))
    )
    eq = result.scalar_one_or_none()
    if not eq:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Equipment not found.")
    return eq


async def get_equipment_group_detail(db: AsyncSession, equipment_id: uuid.UUID) -> EquipmentGroupDetailResponse:
    """รายละเอียดอุปกรณ์แบบยุบกลุ่ม + ผู้ครอบครองทั้งกลุ่ม

    equipment_id เป็นหน่วยไหนในกลุ่มก็ได้ (หน้าเว็บส่งมาจากการ์ดที่โชว์ = หน่วยรหัสต่ำสุดอยู่แล้ว)
    """
    eq = await get_equipment(db, equipment_id)
    members = [eq] if eq.item_type == "consumable" else await find_group_members(db, eq.name, eq.item_type)
    group = _build_group_response(members)
    holders = await get_holders(db, [m.id for m in members])
    unit_summaries = [EquipmentUnitSummary.model_validate(m, from_attributes=True) for m in members]
    return EquipmentGroupDetailResponse(**group.model_dump(), holders=holders, members=unit_summaries)


async def get_holders(db: AsyncSession, equipment_ids: list[uuid.UUID]) -> list[HolderInfo]:
    """คืนรายชื่อผู้ที่ยืมอุปกรณ์กลุ่มนี้อยู่แต่ยังไม่คืน เพื่อให้นักศึกษาเห็นผู้ครอบครองในขณะนั้น

    รับเป็นลิสต์ id เพราะรุ่นที่มีหลายหน่วย (ดู find_group_members) ต้องรวมผู้ครอบครองทั้งกลุ่ม
    ไม่ใช่แค่หน่วยตัวแทนที่โชว์เป็นการ์ดเดียว — ผู้เรียกที่มีแค่ 1 ชิ้นส่ง list ค่าเดียวได้ตามปกติ
    """
    result = await db.execute(
        select(User.full_name, BorrowItem.extended_due_date, BorrowRequest.due_date, BorrowItem.quantity)
        .join(BorrowRequest, BorrowItem.borrow_request_id == BorrowRequest.id)
        .join(User, BorrowRequest.student_id == User.id)
        .where(
            BorrowItem.equipment_id.in_(equipment_ids),
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


async def create_equipment(db: AsyncSession, admin: User, body: EquipmentCreate) -> Equipment:
    existing = await db.execute(select(Equipment).where(Equipment.code == body.code))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Equipment code already exists.")
    data = body.model_dump(exclude={"category_ids"})
    data["name"] = _normalize_name(data["name"])
    data["image_url"] = data["image_urls"][0] if data.get("image_urls") else None  # cover = รูปแรก
    eq = Equipment(**data)
    eq.categories = await _resolve_categories(db, body.category_ids)
    eq.quantity_available = body.quantity_total
    db.add(eq)
    await db.flush()  # ได้ eq.id ก่อนบันทึก audit
    # เก็บ quantity/item_type ลง detail ด้วย เพื่อให้ใบรับเข้า (ร่างเข้า) ดึงจำนวนมาโชว์ได้
    await audit_service.log_action(db, admin, "create_equipment", "equipment", eq.id,
                                   {"code": eq.code, "name": eq.name,
                                    "quantity": eq.quantity_total, "item_type": eq.item_type})
    await db.commit()
    return await get_equipment(db, eq.id)


async def update_equipment(db: AsyncSession, admin: User, equipment_id: uuid.UUID, body: EquipmentUpdate) -> Equipment:
    eq = await get_equipment(db, equipment_id)
    changed = body.model_dump(exclude_none=True, exclude={"category_ids"})
    if "name" in changed:
        changed["name"] = _normalize_name(changed["name"])
    for field, value in changed.items():
        setattr(eq, field, value)
    # ลดจำนวนรวมลงต่ำกว่าที่ว่างอยู่ = แอดมินตั้งใจตัดของออกจากคลัง ลดของว่างตามไปด้วย
    # ถ้าไม่ดักไว้จะไปชน CHECK constraint แล้วกลายเป็น 500 แทนที่จะทำสิ่งที่แอดมินตั้งใจ
    if eq.quantity_available > eq.quantity_total:
        eq.quantity_available = eq.quantity_total
    if body.image_urls is not None:
        eq.image_url = body.image_urls[0] if body.image_urls else None  # sync cover
    if body.category_ids is not None:
        eq.categories = await _resolve_categories(db, body.category_ids)
    await audit_service.log_action(db, admin, "update_equipment", "equipment", eq.id,
                                   {"code": eq.code, "fields": sorted(changed.keys())})
    await db.commit()
    return await get_equipment(db, equipment_id)


async def retire_equipment(
    db: AsyncSession, admin: User, equipment_id: uuid.UUID, reason: str | None = None
) -> None:
    """ปลดระวางอุปกรณ์ + บันทึกเหตุผลลง audit เพื่อออกใบปลดระวาง (ร่างออก) ภายหลัง"""
    eq = await get_equipment(db, equipment_id)
    eq.status = "retired"
    await audit_service.log_action(db, admin, "retire_equipment", "equipment", eq.id,
                                   {"code": eq.code, "name": eq.name,
                                    "quantity": eq.quantity_total, "item_type": eq.item_type,
                                    "reason": (reason or "").strip() or None})
    await db.commit()


async def delete_equipment(db: AsyncSession, admin: User, equipment_id: uuid.UUID) -> None:
    """ลบอุปกรณ์ออกจาก DB ถาวร — อนุญาตเฉพาะ retired และไม่มีประวัติการยืม"""
    eq = await get_equipment(db, equipment_id)
    if eq.status != "retired":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ต้องปลดระวางก่อนลบ")
    has_history = (await db.execute(
        select(func.count(BorrowItem.id)).where(BorrowItem.equipment_id == equipment_id)
    )).scalar() or 0
    if has_history:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ไม่สามารถลบได้ เนื่องจากมีประวัติการยืม")
    # log ก่อนลบ เพราะหลัง delete จะอ้าง target_id ไม่ได้แล้ว
    await audit_service.log_action(db, admin, "delete_equipment", "equipment", eq.id,
                                   {"code": eq.code, "name": eq.name})
    await db.delete(eq)
    await db.commit()


_STOCK_ACTIONS = {"receipt": "create_equipment", "disposal": "retire_equipment"}


REPAIR_STATUSES = ("damaged", "under_repair")


async def build_repair_document(db: AsyncSession, admin: User) -> bytes:
    """สร้าง PDF บันทึกขออนุมัติซ่อมแซมครุภัณฑ์ จากครุภัณฑ์ที่สถานะชำรุด/กำลังซ่อมทั้งหมด

    ลักษณะที่ชำรุดดึงจาก damage_note ของครั้งที่รับคืนล่าสุดที่สรุปว่าเสียหาย — แอดมินไม่ต้องพิมพ์ซ้ำ
    (ยังไม่มีตัวเลือกส่งซ่อมเฉพาะบางชิ้น — ออกทั้งหมดที่ชำรุดอยู่ ณ ตอนนี้)
    """
    from app.utils import pdf

    result = await db.execute(
        select(Equipment)
        .where(Equipment.item_type == "durable", Equipment.status.in_(REPAIR_STATUSES))
        .order_by(Equipment.code)
    )
    equipment = list(result.scalars().all())
    if not equipment:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="ไม่มีครุภัณฑ์ที่สถานะชำรุด/กำลังซ่อม")

    # damage_note ล่าสุดของแต่ละชิ้น (รับคืนล่าสุดที่สรุปว่าเสียหาย/สูญหาย)
    notes = await db.execute(
        select(BorrowItem.equipment_id, BorrowItem.damage_note, BorrowItem.returned_at)
        .where(BorrowItem.equipment_id.in_([e.id for e in equipment]),
               BorrowItem.damage_note.isnot(None))
        .order_by(BorrowItem.returned_at.desc())
    )
    latest: dict = {}
    for eq_id, note, _ in notes:
        latest.setdefault(eq_id, note)

    rows = [
        {"name": eq.name, "code": eq.code,
         "damage": latest.get(eq.id) or ("อยู่ระหว่างซ่อม" if eq.status == "under_repair" else "ชำรุด"),
         "note": "ส่งซ่อมแล้ว" if eq.status == "under_repair" else ""}
        for eq in equipment
    ]
    return pdf.generate_repair_pdf(rows, admin.full_name)


async def build_stock_document(
    db: AsyncSession, admin: User, kind: str, date_from: date, date_to: date
) -> bytes:
    """สร้าง PDF ใบรับเข้าคลัง (receipt) / ใบปลดระวาง (disposal) จาก audit log ในช่วงวันที่

    ดึงจาก audit log เพื่อให้เห็นว่านำอะไรเข้า/ออกบ้าง ใครทำ เมื่อไร พร้อมเหตุผล (ปลดระวาง)
    — เป็นหลักฐานที่ลบไม่ได้อยู่แล้ว จึงใช้เป็นแหล่งข้อมูลเอกสาร
    """
    from app.utils import pdf

    action = _STOCK_ACTIONS.get(kind)
    if action is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid document kind.")
    if date_from > date_to:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="date_from must be <= date_to.")

    # ครอบทั้งวันของ date_to (ถึง 23:59:59.999999) เพื่อให้ inclusive
    # ตีความเป็นวันตามเวลาไทย แล้วเทียบกับ created_at ที่เก็บเป็น UTC — ไม่งั้นของที่ทำตอนเช้าจะหล่นไปวันก่อนหน้า
    start = datetime.combine(date_from, time.min, tzinfo=TZ)
    end = datetime.combine(date_to, time.max, tzinfo=TZ)
    result = await db.execute(
        select(AuditLog)
        .where(AuditLog.action == action,
               AuditLog.created_at >= start, AuditLog.created_at <= end)
        .order_by(AuditLog.created_at)
    )
    logs = result.scalars().all()
    rows = [
        {
            "code": (log.detail or {}).get("code"),
            "name": (log.detail or {}).get("name"),
            "item_type": (log.detail or {}).get("item_type"),
            "quantity": (log.detail or {}).get("quantity"),
            "reason": (log.detail or {}).get("reason"),
            "actor": log.actor_name,
            "date": log.created_at,
        }
        for log in logs
    ]
    return pdf.generate_stock_document_pdf(
        kind, date_from.strftime("%d/%m/%Y"), date_to.strftime("%d/%m/%Y"),
        admin.full_name, rows,
    )


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
