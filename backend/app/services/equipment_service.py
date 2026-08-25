import os
import re
import uuid
from datetime import date, datetime, time

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.audit_log import AuditLog
from app.models.borrow_item import BorrowItem
from app.models.borrow_request import BorrowRequest
from app.models.bundle import BundleItem
from app.models.equipment import Equipment, equipment_category_links
from app.models.equipment_category import EquipmentCategory
from app.models.setting import Setting
from app.models.user import User
from app.schemas.equipment import (
    BulkDeleteFailure,
    BulkDeleteResult,
    BulkRetireResult,
    BulkUpdateResult,
    CategoryCreate,
    CategoryResponse,
    EquipmentBulkUpdate,
    EquipmentCreate,
    EquipmentGroupDetailResponse,
    EquipmentGroupResponse,
    EquipmentResponse,
    EquipmentUnitSummary,
    EquipmentUpdate,
    HolderInfo,
    LocationCount,
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


async def get_holders_map(
    db: AsyncSession, equipment_ids: list[uuid.UUID] | None = None
) -> dict[uuid.UUID, HolderInfo]:
    """หน่วยไหนกำลังถูกยืมอยู่จริงบ้าง (approved + ยังไม่คืน) พร้อมรายละเอียดคนถือ — equipment_ids=None คือทั้งระบบ

    คิวรีเดียวได้ทั้ง "ถูกยืมอยู่ไหม" (เดิมใช้ _borrowed_equipment_ids คืนแค่ set id) และ "ใครถือ" (เดิม
    get_holders แยกอีกคิวรี) รวมเป็นฟังก์ชันเดียว — ผู้เรียกที่ต้องการแค่ boolean เช็ค `id in map` ได้เลย
    ไม่ต้องยิง 2 คิวรีซ้อนกันเหมือนก่อน
    """
    query = (
        select(
            BorrowItem.equipment_id, User.full_name, User.student_id,
            BorrowItem.extended_due_date, BorrowRequest.due_date, BorrowItem.quantity,
        )
        .join(BorrowRequest, BorrowItem.borrow_request_id == BorrowRequest.id)
        .join(User, BorrowRequest.student_id == User.id)
        .where(BorrowRequest.status == "approved", BorrowItem.returned.is_(False))
    )
    if equipment_ids is not None:
        query = query.where(BorrowItem.equipment_id.in_(equipment_ids))
    result = await db.execute(query)
    return {
        eq_id: HolderInfo(holder_name=name, student_number=sid, due_date=ext or due, quantity=qty)
        for eq_id, name, sid, ext, due, qty in result.all()
    }


async def _apply_status_filter(db: AsyncSession, query, filter_status: str | None):
    """status ปกติ (available/damaged/...) filter ตรงคอลัมน์เดิม + เพิ่ม 2 filter พิเศษที่ derive จากตาราง/
    เกณฑ์อื่น ไม่ใช่ค่าจริงใน equipment.status — ใช้ในหน้าจัดการอุปกรณ์แทนการต้องกดเข้ามาจาก dashboard:
    - low_stock: เฉพาะ consumable ที่ต่ำกว่าเกณฑ์ (mirror สูตรเดียวกับ dashboard_service.get_summary)
    - borrowed: มีของออกไปจริงผ่าน BorrowItem ที่ยังไม่คืน (คนละอย่างกับ status="available" ที่กดลบไม่ได้
      สื่อว่า "ยืมได้" ไม่ใช่ "กำลังถูกยืม")

    ใช้กับ list_equipment (ไม่ยุบกลุ่ม) เท่านั้น — list_equipment_grouped ต้อง filter "borrowed" ที่ระดับกลุ่ม
    แยกต่างหาก (ดู comment ใน list_equipment_grouped) ไม่งั้นยอดรวมของการ์ดจะผิด เพราะกรองตัดหน่วยพี่น้อง
    ในกลุ่มเดียวกันที่ไม่ได้ถูกยืมออกไปจาก query ตั้งแต่ต้น
    """
    if filter_status == "low_stock":
        default_threshold = int((await db.execute(
            select(Setting.value).where(Setting.key == "low_stock_threshold_default")
        )).scalar_one())
        return query.where(
            Equipment.item_type == "consumable",
            Equipment.quantity_available <= func.coalesce(Equipment.low_stock_threshold, default_threshold),
        )
    if filter_status == "borrowed":
        return query.where(Equipment.id.in_((await get_holders_map(db)).keys()))
    if filter_status:
        return query.where(Equipment.status == filter_status)
    return query


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
    query = await _apply_status_filter(db, query, filter_status)
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
    holders_map = await get_holders_map(db)
    responses = [
        EquipmentResponse.model_validate(eq, from_attributes=True).model_copy(
            update={"is_currently_borrowed": eq.id in holders_map, "holder": holders_map.get(eq.id)}
        )
        for eq in items
    ]
    return PaginatedEquipment(items=responses, total=total, page=page, page_size=page_size)


def _is_eligible(eq: Equipment) -> bool:
    return eq.is_borrowable and eq.status == "available"


def _group_key(eq: Equipment) -> tuple:
    # consumable ไม่ยุบรวมแม้ชื่อซ้ำ (เป็นก้อนเดียวต่อแถวอยู่แล้ว) — คีย์เป็น id เดียวกันไม่ได้กับแถวอื่น
    return (eq.id,) if eq.item_type == "consumable" else (eq.name, eq.item_type)


def _location_breakdown(rows: list[Equipment]) -> list[LocationCount]:
    """สรุปจำนวนหน่วยแยกตามค่า location จริงของทุกแถวในกลุ่ม (ค่าว่าง/None รวมเป็น "ไม่ระบุสถานที่")

    ใช้ตอนแยกวัสดุเป็นรายชิ้นแล้วแอดมินย้ายบางชิ้นไปเก็บคนละที่ — การ์ดกลุ่มที่โชว์ location เดียว
    จากหน่วยรหัสต่ำสุดไม่พอ ต้องเห็นภาพรวมว่ากระจายอยู่ที่ไหนบ้าง
    """
    counts: dict[str, int] = {}
    for r in rows:
        key = r.location or "ไม่ระบุสถานที่"
        counts[key] = counts.get(key, 0) + 1
    return [LocationCount(location=loc, count=n) for loc, n in counts.items()]


def _build_group_response(
    rows: list[Equipment], holders_map: dict[uuid.UUID, HolderInfo]
) -> EquipmentGroupResponse:
    """ประกอบการ์ดยุบกลุ่ม — field แสดงผลอื่น ๆ ใช้ของหน่วยรหัสต่ำสุด (rows เรียงมาแล้ว)

    holder เจาะจงหน่วยตัวแทนเท่านั้น (มีความหมายจริงเฉพาะการ์ดหน่วยเดียว unit_count==1 — การ์ดหลายหน่วย
    ต้องกางดูรายหน่วยแทนเพราะแต่ละหน่วยอาจมีคนละคนถือ ไม่มี "คนเดียว" ให้โชว์ตรงนี้)
    """
    rep = rows[0]
    eligible = [r for r in rows if _is_eligible(r)]
    base = EquipmentResponse.model_validate(rep, from_attributes=True).model_dump()
    base["quantity_total"] = sum(r.quantity_total for r in rows)
    base["quantity_available"] = sum(r.quantity_available for r in eligible)
    base["is_currently_borrowed"] = rep.id in holders_map
    base["holder"] = holders_map.get(rep.id)
    # มีหน่วยว่างพร้อมยืมอย่างน้อย 1 ชิ้น = การ์ดนี้ "พร้อมให้ยืม" ไม่งั้น fallback ไปสถานะของตัวแทน
    if eligible:
        base["is_borrowable"] = True
        base["status"] = "available"
    return EquipmentGroupResponse(**base, unit_count=len(rows), locations=_location_breakdown(rows))


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
    # "borrowed" ต้อง filter ที่ "กลุ่มไหนมีหน่วยถูกยืมอยู่บ้าง" ไม่ใช่กรองที่ query แถวก่อน group —
    # ถ้ากรองที่แถวเลย จะดึงมาแค่หน่วยที่ถูกยืม แล้วเอาไปรวมยอด quantity_total/available เป็นยอดของกลุ่ม
    # ทำให้ผิด (เช่น Arduino-UNO-R3 มี 42 หน่วย ยืมอยู่ 1 → เห็น "0/1" แทนที่จะเป็น "41/42" ที่ถูกต้อง)
    # ต้องดึงทุกหน่วยของกลุ่มมาคำนวณยอดก่อน แล้วค่อยกรองว่าจะโชว์การ์ดไหนทีหลัง
    filter_borrowed_group = filter_status == "borrowed"
    query = await _apply_status_filter(db, query, None if filter_borrowed_group else filter_status)
    if search:
        kw = f"%{search.strip()}%"
        query = query.where(or_(Equipment.name.ilike(kw), Equipment.code.ilike(kw)))
    query = query.options(selectinload(Equipment.categories)).order_by(Equipment.code)

    rows = list((await db.execute(query)).scalars().all())

    groups: dict[tuple, list[Equipment]] = {}
    for eq in rows:
        groups.setdefault(_group_key(eq), []).append(eq)

    holders_map = await get_holders_map(db)
    if filter_borrowed_group:
        groups = {key: members for key, members in groups.items() if any(m.id in holders_map for m in members)}

    cards = [_build_group_response(members, holders_map) for members in groups.values()]
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
    holders_map = await get_holders_map(db, [m.id for m in members])
    group = _build_group_response(members, holders_map)
    unit_summaries = [
        EquipmentUnitSummary.model_validate(m, from_attributes=True).model_copy(
            update={"is_currently_borrowed": m.id in holders_map, "holder": holders_map.get(m.id)}
        )
        for m in members
    ]
    return EquipmentGroupDetailResponse(**group.model_dump(), holders=list(holders_map.values()), members=unit_summaries)


async def _resolve_categories(db: AsyncSession, category_ids: list[uuid.UUID]) -> list[EquipmentCategory]:
    """ดึง category objects ตาม id — เออเรอร์ถ้ามี id ที่ไม่มีจริง"""
    result = await db.execute(select(EquipmentCategory).where(EquipmentCategory.id.in_(category_ids)))
    cats = list(result.scalars().all())
    if len(cats) != len(set(category_ids)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid category id.")
    return cats


def _generate_consumable_code(name: str, existing_codes: set[str]) -> str:
    """สร้างรหัสจากชื่ออุปกรณ์ + เลขลำดับ เช่น "ตัวต้านทาน 220 โอห์ม" -> "ตัวต้านทาน 220 โอห์ม-001"

    ใช้เมื่อแอดมินไม่กรอกรหัสมาสำหรับวัสดุสิ้นเปลือง (รหัสไม่มีความหมายจริงสำหรับของแบบนี้ เช่น เซ็นเซอร์
    หลายแบบจำนวนมาก) — อ่านง่ายกว่ารหัสสุ่มล้วน ๆ เห็นชื่อในรหัสได้เลยไม่ต้องเปิดดูชื่อแยก
    ตัดชื่อให้เหลือพอสำหรับคอลัมน์ String(50) เผื่อเลขลำดับต่อท้าย (-001 = 4 ตัวอักษร)
    """
    slug = name.strip()[:44]
    n = 1
    while True:
        candidate = f"{slug}-{n:03d}"
        if candidate not in existing_codes:
            return candidate
        n += 1


async def create_equipment(db: AsyncSession, admin: User, body: EquipmentCreate) -> Equipment:
    code = body.code
    if not code:
        if body.item_type != "consumable":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail="จำเป็นต้องระบุรหัสอุปกรณ์ (เว้นว่างได้เฉพาะวัสดุสิ้นเปลือง)")
        existing_codes = set((await db.execute(select(Equipment.code))).scalars().all())
        code = _generate_consumable_code(body.name, existing_codes)

    existing = await db.execute(select(Equipment).where(Equipment.code == code))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Equipment code already exists.")
    if body.serial_number:
        dup_sn = await db.execute(select(Equipment).where(Equipment.serial_number == body.serial_number))
        if dup_sn.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Serial number already exists.")
    data = body.model_dump(exclude={"category_ids"})
    data["code"] = code
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
    """แก้ไขอุปกรณ์ — แก้ code/item_type ได้แม้เคยมีประวัติการยืม เพราะ BorrowItem เก็บ snapshot

    equipment_name/code/unit/item_type_snapshot เป็นคอลัมน์จริงบน BorrowItem ไม่ใช่ live join
    (ดู borrow_service.py create_request/approve_request) แก้ตรงนี้จึงไม่กระทบใบยืมเก่าเลย
    """
    eq = await get_equipment(db, equipment_id)
    changed = body.model_dump(exclude_none=True, exclude={"category_ids"})
    if "name" in changed:
        changed["name"] = _normalize_name(changed["name"])
    if "code" in changed and changed["code"] != eq.code:
        dup_code = await db.execute(
            select(Equipment).where(Equipment.code == changed["code"], Equipment.id != equipment_id)
        )
        if dup_code.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Equipment code already exists.")
    if "serial_number" in changed and changed["serial_number"] != eq.serial_number:
        dup_sn = await db.execute(
            select(Equipment).where(Equipment.serial_number == changed["serial_number"], Equipment.id != equipment_id)
        )
        if dup_sn.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Serial number already exists.")

    # เก็บ diff ก่อน/หลังไว้ทำ audit (ดู audit_service.diff_fields) — setattr loop ด้านล่างเขียนทับแล้ว
    # ย้อนดูค่าเดิมไม่ได้ ต้องอ่านจาก eq ก่อนแก้เท่านั้น
    field_diffs = audit_service.diff_fields(eq, changed)
    old_status, old_total, old_available = eq.status, eq.quantity_total, eq.quantity_available

    for field, value in changed.items():
        setattr(eq, field, value)
    # เพิ่มจำนวนรวม (แอดมินนับใหม่/เติมของเข้าคลัง) → ของที่เพิ่มมาต้องพร้อมให้ยืมด้วย ไม่งั้นค่าคงเหลือ
    # ค้างที่ตัวเลขเดิมตลอดไป เพราะฟอร์มนี้ไม่มีช่องแก้ quantity_available ตรง ๆ เลยสักที่ (เจอบั๊กจริง)
    if eq.quantity_total > old_total:
        eq.quantity_available = old_available + (eq.quantity_total - old_total)
    # ลดจำนวนรวมลงต่ำกว่าที่ว่างอยู่ = แอดมินตั้งใจตัดของออกจากคลัง ลดของว่างตามไปด้วย
    # ถ้าไม่ดักไว้จะไปชน CHECK constraint แล้วกลายเป็น 500 แทนที่จะทำสิ่งที่แอดมินตั้งใจ
    if eq.quantity_available > eq.quantity_total:
        eq.quantity_available = eq.quantity_total
    # หน่วยเดี่ยว (quantity_total==1) เปลี่ยนสถานะกลับเป็น "พร้อมให้ยืม" จากสถานะอื่น (เช่นของหายที่เพิ่งเจอ/
    # ซ่อมเสร็จ) → คืนของว่างให้ครบ เพราะ borrow_service.return_item ตอนของหาย/เสีย (lost/damaged) ปรับ status
    # ให้เป็น unavailable/damaged แต่ตั้งใจไม่คืนสต็อก (quantity_available ค้าง 0) — ถ้าไม่ทำตรงนี้ ไม่มีทางอื่น
    # เลยที่จะทำให้ยืมได้อีกหลังแก้ไข เพราะฟอร์มไม่มีช่องแก้ quantity_available ตรง ๆ
    if "status" in changed and old_status != "available" and eq.status == "available" and eq.quantity_total == 1:
        eq.quantity_available = eq.quantity_total
    if body.image_urls is not None:
        eq.image_url = body.image_urls[0] if body.image_urls else None  # sync cover
    if body.category_ids is not None:
        old_category_names = sorted(c.name for c in eq.categories)
        eq.categories = await _resolve_categories(db, body.category_ids)
        new_category_names = sorted(c.name for c in eq.categories)
        if old_category_names != new_category_names:
            field_diffs["category_ids"] = [old_category_names, new_category_names]

    detail = {"code": eq.code, "changes": field_diffs}
    await audit_service.log_action(db, admin, "update_equipment", "equipment", eq.id, detail)
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


async def bulk_retire_equipment(
    db: AsyncSession, admin: User, equipment_ids: list[uuid.UUID], reason: str | None
) -> BulkRetireResult:
    """ปลดระวางหลายรายการพร้อมกันแบบ best-effort — เรียก retire_equipment เดิมซ้ำทีละชิ้น (ใช้ guard/audit
    เดิมทุกอย่าง ไม่เขียนเงื่อนไขซ้ำ) เหตุผลเดียวกันใช้กับทุกชิ้นที่เลือก ชิ้นที่ปลดระวางไม่ได้ (เช่น id ไม่มีจริง)
    ไม่บล็อกชิ้นอื่นที่เหลือ เหมือน bulk_delete_equipment
    """
    retired: list[uuid.UUID] = []
    failed: list[BulkDeleteFailure] = []
    for eq_id in equipment_ids:
        try:
            await retire_equipment(db, admin, eq_id, reason)
            retired.append(eq_id)
        except HTTPException as e:
            failed.append(BulkDeleteFailure(equipment_id=eq_id, reason=str(e.detail)))
    return BulkRetireResult(retired=retired, failed=failed)


def _generate_split_codes(base_code: str, count: int, existing_codes: set[str]) -> list[str]:
    """สร้างรหัสใหม่ `count` รหัส ต่อจาก `base_code` — ตัดเลขท้ายรัน (trailing digits) มาบวกทีละ 1 คง zero-pad เดิม
    (`234001` → `234002`, `234003`, ...) ถ้ารหัสไม่มีเลขท้ายเลยให้ต่อท้ายด้วย `-2`, `-3`, ...

    ข้ามรหัสที่ชนกับที่มีอยู่แล้วในระบบ — คลัง ≤100 รายการ (CLAUDE.md) โหลด code ทั้งหมดมาเช็คในหน่วยความจำ
    พอ ไม่ต้อง query ทีละรหัสเหมือนคลังขนาดใหญ่
    """
    m = re.search(r"\d+$", base_code)
    if m:
        prefix, width, n = base_code[: m.start()], len(m.group()), int(m.group())
    else:
        prefix, width, n = f"{base_code}-", 0, 1

    taken = set(existing_codes) | {base_code}
    codes: list[str] = []
    while len(codes) < count:
        n += 1
        candidate = f"{prefix}{n:0{width}d}" if width else f"{prefix}{n}"
        if candidate in taken:
            continue
        codes.append(candidate)
        taken.add(candidate)
    return codes


async def split_equipment_into_units(
    db: AsyncSession, admin: User, equipment_id: uuid.UUID, dry: bool = False
) -> list[Equipment]:
    """แปลงแถวรวมของวัสดุ (`item_type=material`, `quantity_total=N`) เป็น N แถวเดี่ยว (`quantity_total=1`
    ทุกแถว) คนละรหัส — แก้บั๊กที่วัสดุนำเข้าเป็นก้อนเดียวจากชีต "วัสดุ" ทำให้ borrow_service.create_request
    (ซึ่งแยก BorrowItem อัตโนมัติเมื่อรุ่นเดียวกันมีหลายแถวใน DB อยู่แล้ว — ดู find_group_members) ไม่มีอะไรให้แยก

    เฉพาะ material เท่านั้น — durable แยกเป็นรายหน่วยจากทะเบียนคุมทรัพย์สินอยู่แล้ว (1 แถวต่อ 1 เลขครุภัณฑ์),
    consumable ต้องคงเป็นก้อนเดียวตามกฎธุรกิจ (CLAUDE.md ข้อ 5) ห้ามแยก

    dry=True ทำถึง flush() แล้วข้าม commit() — ใช้เฉพาะสคริปต์ dry-run ครั้งเดียว (scripts/split_material_equipment.py)
    endpoint จริง (POST /equipment/{id}/split) ต้องไม่ส่ง dry=True เด็ดขาด
    """
    # populate_existing บังคับให้ค่าที่อาจถูกโหลด/แคชไว้ในเซสชันนี้ก่อนหน้า (เช่นสคริปต์ที่ preload
    # ทุกแถวมาเช็คก่อนวนเรียก split ทีละแถว) ถูกเขียนทับด้วยค่าที่เพิ่งล็อกจริงจาก DB — ไม่งั้นเพราะ
    # AsyncSessionLocal ตั้ง expire_on_commit=False ค่าเดิมที่ค้างใน identity map จะเป็นค่า stale
    # แล้วเช็ค quantity_available != quantity_total (มีของยืมอยู่ไหม) จะพลาดได้ถ้ามีการอนุมัติคำขออื่น
    # แทรกมาระหว่างนั้น (แพทเทิร์นเดียวกับ borrow_service.approve_request)
    eq = (await db.execute(
        select(Equipment).where(Equipment.id == equipment_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )).scalar_one_or_none()
    if not eq:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Equipment not found.")
    if eq.item_type != "material":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="แยกเป็นรายชิ้นได้เฉพาะวัสดุใช้ซ้ำ (material) เท่านั้น")
    if eq.quantity_total <= 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="มีจำนวนแค่ 1 ชิ้น ไม่มีอะไรให้แยก")
    if eq.quantity_available != eq.quantity_total:
        borrowed = eq.quantity_total - eq.quantity_available
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"มีของถูกยืมอยู่ {borrowed} ชิ้น ต้องรอคืนครบทุกชิ้นก่อนจึงแยกเป็นรายชิ้นได้",
        )

    # with_for_update() ไม่พ่วง selectinload มาด้วย — ต้องโหลด categories ก่อนใช้ ไม่งั้น lazy-load
    # นอก async context แล้ว 500 (บั๊กแบบเดียวกับที่เจอใน find_group_members มาก่อน)
    await db.refresh(eq, attribute_names=["categories"])

    count = eq.quantity_total
    existing_codes = set((await db.execute(select(Equipment.code))).scalars().all())
    new_codes = _generate_split_codes(eq.code, count - 1, existing_codes)

    new_rows = [eq]
    for code in new_codes:
        clone = Equipment(
            id=uuid.uuid4(),
            code=code,
            name=eq.name,
            item_type=eq.item_type,
            description=eq.description,
            image_url=eq.image_url,
            image_urls=list(eq.image_urls),
            location=eq.location,
            unit=eq.unit,
            unit_value=eq.unit_value,
            quantity_total=1,
            quantity_available=1,
            low_stock_threshold=eq.low_stock_threshold,
            status=eq.status,
            is_borrowable=eq.is_borrowable,
        )
        clone.categories = list(eq.categories)
        db.add(clone)
        new_rows.append(clone)

    # แถวต้นฉบับหดเหลือ quantity_total=1 กลายเป็นหน่วยที่ 1 ของชุด — รหัสเดิมไม่เปลี่ยน ไม่มีแถวทิ้งขว้าง
    eq.quantity_total = 1
    eq.quantity_available = 1

    await audit_service.log_action(
        db, admin, "split_equipment", "equipment", eq.id,
        {"code": eq.code, "name": eq.name, "quantity": count, "split_into": [r.code for r in new_rows]},
    )
    await db.flush()
    if dry:
        return new_rows

    await db.commit()
    ids = [r.id for r in new_rows]
    result = await db.execute(
        select(Equipment).where(Equipment.id.in_(ids))
        .options(selectinload(Equipment.categories)).order_by(Equipment.code)
    )
    return list(result.scalars().all())


async def restock_equipment(
    db: AsyncSession, admin: User, equipment_id: uuid.UUID, count: int
) -> list[Equipment]:
    """เติมของเข้าคลัง (ซื้อเพิ่ม) — พิมพ์แค่ "จะเพิ่มกี่ชิ้น" ไม่ต้องคำนวณยอดรวมใหม่เอง (เดิมมีแต่ฟอร์มแก้ไขที่
    ต้องพิมพ์ยอดรวมใหม่ทั้งหมด พิมพ์ผิดแล้วต่ำกว่าเดิมจะโดน down-clamp ใน update_equipment ทำสต็อกหายจริง)

    แยกพฤติกรรมตามว่าแถวนี้นับเป็น "ก้อน" หรือ "รายชิ้น" อยู่แล้ว:
    - วัสดุสิ้นเปลือง หรือวัสดุก้อนที่ยังไม่แยกรายชิ้น (quantity_total > 1) → บวกเข้าที่แถวเดิมตรง ๆ
    - ครุภัณฑ์ หรือวัสดุที่แยกรายชิ้นแล้ว (quantity_total == 1 ต่อแถว = 1 หน่วยจริงต่อแถว) → สร้างแถวใหม่
      คนละรหัส count แถว เหมือนของเดิมที่แยกไว้ (ผูก serial number ทีละชิ้นทีหลังได้)
    """
    eq = (await db.execute(
        select(Equipment).where(Equipment.id == equipment_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )).scalar_one_or_none()
    if not eq:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Equipment not found.")

    if eq.item_type == "consumable" or eq.quantity_total > 1:
        eq.quantity_total += count
        eq.quantity_available += count
        await audit_service.log_action(
            db, admin, "restock_equipment", "equipment", eq.id,
            {"code": eq.code, "name": eq.name, "added": count, "quantity_total": eq.quantity_total},
        )
        await db.commit()
        return [await get_equipment(db, eq.id)]

    # ครุภัณฑ์ หรือวัสดุที่แยกรายชิ้นแล้ว — สร้างหน่วยใหม่แยกรหัส คนละแถวเหมือนของเดิม
    await db.refresh(eq, attribute_names=["categories"])
    existing_codes = set((await db.execute(select(Equipment.code))).scalars().all())
    new_codes = _generate_split_codes(eq.code, count, existing_codes)
    new_rows = []
    for code in new_codes:
        clone = Equipment(
            id=uuid.uuid4(), code=code, name=eq.name, item_type=eq.item_type,
            description=eq.description, image_url=eq.image_url, image_urls=list(eq.image_urls),
            location=eq.location, unit=eq.unit, unit_value=eq.unit_value,
            quantity_total=1, quantity_available=1,
            low_stock_threshold=eq.low_stock_threshold, status="available", is_borrowable=eq.is_borrowable,
        )
        clone.categories = list(eq.categories)
        db.add(clone)
        new_rows.append(clone)

    await audit_service.log_action(
        db, admin, "restock_equipment", "equipment", eq.id,
        {"code": eq.code, "name": eq.name, "added": count, "new_codes": new_codes},
    )
    await db.flush()
    await db.commit()
    ids = [r.id for r in new_rows]
    result = await db.execute(
        select(Equipment).where(Equipment.id.in_(ids))
        .options(selectinload(Equipment.categories)).order_by(Equipment.code)
    )
    return list(result.scalars().all())


async def delete_equipment(db: AsyncSession, admin: User, equipment_id: uuid.UUID) -> None:
    """ลบอุปกรณ์ออกจาก DB ถาวร — อนุญาตเฉพาะ retired และไม่มีการยืมที่ยังไม่คืน (pending/approved)

    ประวัติที่จบแล้ว (completed/rejected/cancelled) ไม่กันการลบอีกต่อไป — BorrowItem เก็บ
    equipment_name/code/unit เป็น snapshot คอลัมน์จริงแล้ว (ดู borrow_item.py) ไม่ต้องพึ่ง live join
    กับแถว equipment ที่กำลังจะถูกลบ ประวัติจึงไม่พังแม้ FK equipment_id จะถูก SET NULL (ดู migration 0020)

    เช็คด้วย returned==False เฉยๆ ไม่พอ: rejected/cancelled ไม่เคยเซ็ต returned=True เลย (ไม่มี flow
    คืนของสำหรับสถานะเหล่านี้) ต้อง join ไป BorrowRequest.status ด้วย ไม่งั้นของที่เคยอยู่ในคำขอที่ถูกปฏิเสธ/ยกเลิก
    จะติดล็อกลบไม่ได้ตลอดกาลเหมือนบั๊กเดิม
    """
    eq = await get_equipment(db, equipment_id)
    if eq.status != "retired":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ต้องปลดระวางก่อนลบ")

    active_count = (await db.execute(
        select(func.count(BorrowItem.id))
        .join(BorrowRequest, BorrowItem.borrow_request_id == BorrowRequest.id)
        .where(
            BorrowItem.equipment_id == equipment_id,
            BorrowItem.returned == False,  # noqa: E712
            BorrowRequest.status.in_(("pending", "approved")),
        )
    )).scalar() or 0
    if active_count:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ไม่สามารถลบได้ เนื่องจากยังมีรายการยืมที่ยังไม่คืน",
        )

    # อุปกรณ์ที่เป็นสมาชิกชุดอุปกรณ์ (bundle) ลบไม่ได้ — BundleItem.equipment_id ไม่มี ON DELETE SET NULL
    # ถ้าไม่เช็คก่อนจะโยน IntegrityError ดิบๆ กลายเป็น 500 แทนที่จะเป็น 400 อ่านเข้าใจ
    bundle_ref = (await db.execute(
        select(func.count(BundleItem.id)).where(BundleItem.equipment_id == equipment_id)
    )).scalar() or 0
    if bundle_ref:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ไม่สามารถลบได้ เนื่องจากเป็นสมาชิกของชุดอุปกรณ์อยู่",
        )

    # log ก่อนลบ เพราะหลัง delete จะอ้าง target_id ไม่ได้แล้ว
    await audit_service.log_action(db, admin, "delete_equipment", "equipment", eq.id,
                                   {"code": eq.code, "name": eq.name})
    await db.delete(eq)
    await db.commit()


async def bulk_delete_equipment(
    db: AsyncSession, admin: User, equipment_ids: list[uuid.UUID]
) -> BulkDeleteResult:
    """ลบถาวรหลายรายการพร้อมกันแบบ best-effort — เรียก delete_equipment เดิมซ้ำทีละชิ้น (ใช้ guard/audit
    เดิมทุกอย่าง ไม่เขียนเงื่อนไขซ้ำ) ชิ้นที่ guard ปฏิเสธได้อย่างชอบธรรม (เช่นยังไม่ปลดระวาง หรือผูกกับ
    ชุดอุปกรณ์อยู่) ไม่บล็อกชิ้นอื่นที่เหลือ — เก็บผลลัพธ์แยกสำเร็จ/ไม่สำเร็จพร้อมเหตุผล
    """
    deleted: list[uuid.UUID] = []
    failed: list[BulkDeleteFailure] = []
    for eq_id in equipment_ids:
        try:
            await delete_equipment(db, admin, eq_id)
            deleted.append(eq_id)
        except HTTPException as e:
            failed.append(BulkDeleteFailure(equipment_id=eq_id, reason=str(e.detail)))
    return BulkDeleteResult(deleted=deleted, failed=failed)


async def bulk_update_equipment(
    db: AsyncSession, admin: User, equipment_ids: list[uuid.UUID], body: EquipmentBulkUpdate
) -> BulkUpdateResult:
    """แก้ไขหลายหน่วยพร้อมกัน (เช่น ย้ายสถานที่ทั้ง 12 หน่วยของรุ่นเดียวกัน) — all-or-nothing ต่างจาก
    bulk_delete_equipment เพราะการแก้ location/status ไม่มีเหตุผลที่ควร "แก้ได้บางชิ้น" เซสชันเดียว
    commit ครั้งเดียว, audit เป็น 1 entry รวม (ไม่ log ทีละแถว)
    """
    changed = body.model_dump(exclude_none=True, exclude={"category_ids"})
    if not changed and body.category_ids is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ไม่มีอะไรจะแก้ไข")
    if "name" in changed:
        changed["name"] = _normalize_name(changed["name"])

    rows = [await get_equipment(db, eq_id) for eq_id in equipment_ids]  # 404 ถ้ามี id ที่ไม่มีจริง
    # resolve ครั้งเดียวใช้ร่วมกันทุกแถว — ตั้งหมวดหมู่ชุดเดียวกันให้ทุกหน่วยที่เลือก ไม่ต้อง query ซ้ำ
    new_categories = await _resolve_categories(db, body.category_ids) if body.category_ids is not None else None

    for eq in rows:
        for field, value in changed.items():
            setattr(eq, field, value)
        if "image_urls" in changed:
            eq.image_url = changed["image_urls"][0] if changed["image_urls"] else None  # sync cover
        if new_categories is not None:
            eq.categories = list(new_categories)

    # ไม่ใช่ before/after จริง เพราะ 1 การแก้ไขกระทบหลายแถวที่ค่าเดิมต่างกัน — log ฝั่ง "ตั้งเป็นอะไร" พอ
    audit_set = dict(changed)
    if new_categories is not None:
        audit_set["category_ids"] = sorted(c.name for c in new_categories)
    await audit_service.log_action(
        db, admin, "bulk_update_equipment", "equipment", rows[0].id,
        {"count": len(rows), "set": audit_set, "equipment_ids": [str(e.id) for e in rows]},
    )
    await db.commit()
    ids = [e.id for e in rows]
    result = await db.execute(
        select(Equipment).where(Equipment.id.in_(ids)).options(selectinload(Equipment.categories))
    )
    return BulkUpdateResult(updated=list(result.scalars().all()))


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
    return generate_qr_png(f"{settings.FRONTEND_URL}/equipment/{eq.id}")


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
