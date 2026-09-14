import os
import re
import uuid
from datetime import date, datetime, time
from decimal import Decimal

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
    BulkAdjustStockResult,
    EquipmentListSummary,
    EquipmentTypeSummary,
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
from app.utils.roles import is_superadmin

ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024

# ลายเซ็นไบต์ต้นไฟล์ของแต่ละชนิด — นามสกุลอย่างเดียวเชื่อไม่ได้ ใครก็เปลี่ยนชื่อไฟล์ .html เป็น .jpg ได้
# แล้วไฟล์นั้นจะถูกเสิร์ฟจาก /uploads ที่เป็น static สาธารณะ = stored XSS บนโดเมนเดียวกับแอป
# ponytail: เช็คแค่ magic bytes ไม่ต้องพึ่ง libmagic/python-magic (คนละ dependency ต่อ OS)
_MAGIC_BYTES: dict[str, tuple[bytes, ...]] = {
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".gif": (b"GIF87a", b"GIF89a"),
    ".webp": (b"RIFF",),   # ตรวจ "WEBP" ที่ offset 8 เพิ่มด้านล่าง
    ".pdf": (b"%PDF",),
}


async def _depreciation_settings(db: AsyncSession) -> tuple[int, float]:
    """อ่านค่ากลางที่ใช้คำนวณค่าเสื่อม (อายุการใช้งาน, มูลค่าซาก) ครั้งเดียวต่อ request
    แล้วส่งต่อให้ book_value() ทุกแถว — ไม่ query ซ้ำต่ออุปกรณ์ 1 ชิ้น
    """
    rows = dict((await db.execute(
        select(Setting.key, Setting.value).where(
            Setting.key.in_(("depreciation_years_default", "depreciation_salvage_value"))
        )
    )).all())
    return int(rows.get("depreciation_years_default", 5)), float(rows.get("depreciation_salvage_value", 1))


def book_value(eq: Equipment, years_default: int, salvage: float, today: date | None = None) -> float | None:
    """มูลค่าตามบัญชี = ราคาทุน − ค่าเสื่อมสะสมแบบเส้นตรง โดยไม่ต่ำกว่ามูลค่าซาก

    ค่าที่แอดมินกรอกทับ (book_value_override) ชนะสูตรเสมอ — งานพัสดุจริงมีเคสตีราคาใหม่/ปรับปรุงบัญชี
    ที่สูตรกลางตามไม่ทัน คำนวณสดทุกครั้งที่อ่าน ไม่เก็บเป็นคอลัมน์เพราะค่าเดินทุกวัน
    (ค่า ณ วันอนุมัติถูก snapshot ไว้ที่ borrow_items.book_value_snapshot แยกต่างหากแล้ว)
    """
    # getattr — ฟังก์ชันนี้ใช้กับ EquipmentPart ด้วย (duck-typing บน unit_value/acquired_at/useful_life_years)
    # ซึ่งไม่มีช่องกรอกทับ ราคาชิ้นส่วนคำนวณตามสูตรอย่างเดียว
    override = getattr(eq, "book_value_override", None)
    if override is not None:
        return float(override)
    if eq.unit_value is None or eq.acquired_at is None:
        return None
    cost = float(eq.unit_value)
    # ของที่ราคาต่ำกว่ามูลค่าซากอยู่แล้ว (วัสดุชิ้นละไม่กี่บาท) ไม่มีอะไรให้เสื่อม
    if cost <= salvage:
        return cost
    life_days = max(eq.useful_life_years or years_default, 1) * 365.25
    age_days = ((today or date.today()) - eq.acquired_at).days
    # clamp 0..1 — ของที่ลงวันที่ได้มาไว้ในอนาคตยังไม่เสื่อม, ของที่เกินอายุแล้วหยุดที่มูลค่าซาก
    ratio = min(max(age_days / life_days, 0.0), 1.0)
    return round(cost - (cost - salvage) * ratio, 2)


async def attach_book_values(db: AsyncSession, rows: list[Equipment]) -> None:
    """เติม attribute `book_value` ให้ทุกแถวก่อนแปลงเป็น response — schema อ่านผ่าน from_attributes
    (pattern เดียวกับ get_holders_map ที่เติมข้อมูลนอกคอลัมน์ให้ response) ไม่ใช่คอลัมน์ใน DB
    """
    if not rows:
        return
    years, salvage = await _depreciation_settings(db)
    today = date.today()
    for eq in rows:
        eq.book_value = book_value(eq, years, salvage, today)


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


def borrowed_days_expr():
    """SQL expression: จำนวนวันที่ borrow_item หนึ่งแถวออกจากคลัง (ยังไม่คืน = นับถึงตอนนี้)

    นับขั้นต่ำ 1 วันต่อการยืม 1 ครั้ง — ยืมเช้าคืนบ่ายก็คือของไม่อยู่ในคลังวันนั้น ถ้าปล่อยเป็น 0 จะกลาย
    เป็นว่าหน่วยที่ถูกหยิบไปยืมสั้น ๆ ทุกวันยังถูกนับว่า "ไม่เคยถูกใช้" แล้วโดนจ่ายซ้ำอยู่ชิ้นเดียว
    ปัดเศษแบบ round ไม่ใช่ ceil — ยืม 10 วันกับอีก 3 วินาทีต้องได้ 10 ไม่ใช่ 11
    ต้อง join BorrowRequest มาก่อนใช้ (ต้องใช้ approved_at เป็นจุดเริ่มนับ)
    """
    return func.greatest(1, func.round(
        func.extract("epoch", func.coalesce(BorrowItem.returned_at, func.now()) - BorrowRequest.approved_at)
        / 86400.0
    ))


async def usage_days_map(db: AsyncSession, equipment_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """วันรวมที่แต่ละหน่วยเคยถูกยืมออกไป — ใช้จัดลำดับจ่ายของ "ถูกใช้น้อยสุดก่อน" (ดู dispatch_key)

    นับเฉพาะชิ้นที่ของออกจากคลังจริง: ชิ้นที่ถูกปฏิเสธไม่เคยได้ของไป และคำขอที่ยังไม่อนุมัติยังไม่มี
    approved_at หน่วยที่ไม่เคยถูกยืมจะไม่มี key ใน dict (ผู้เรียกใช้ .get(id, 0))
    """
    if not equipment_ids:
        return {}
    rows = (await db.execute(
        select(BorrowItem.equipment_id, func.coalesce(func.sum(borrowed_days_expr()), 0))
        .join(BorrowRequest, BorrowItem.borrow_request_id == BorrowRequest.id)
        .where(
            BorrowItem.equipment_id.in_(equipment_ids),
            BorrowItem.item_status != "rejected",
            BorrowRequest.approved_at.is_not(None),
        )
        .group_by(BorrowItem.equipment_id)
    )).all()
    return {eq_id: int(days) for eq_id, days in rows}


def dispatch_key(eq: Equipment, usage_days: dict[uuid.UUID, int] | None = None) -> tuple:
    """คีย์เรียง "ลำดับจ่ายของ" — **หน่วยที่ถูกใช้มาน้อยที่สุดถูกยืมออกก่อน** แล้วค่อยเก่าสุดก่อน

    เปลี่ยนจาก FIFO ตาม acquired_at ล้วน ๆ ตาม feedback อาจารย์ 5 ก.ย. 69 ข้อ 9 — เกณฑ์เดิมทำให้
    ของเก่าที่โทรมอยู่แล้วถูกจ่ายซ้ำทุกครั้งจนพังอยู่ชิ้นเดียว ขณะที่ชิ้นใหม่แทบไม่ถูกแตะ
    เกณฑ์ใหม่กระจายการสึกหรอตาม "วันที่เคยถูกยืมจริง" ซึ่งเป็นตัววัดการใช้งานที่ตรงกว่าอายุของ

    usage_days = ผลจาก usage_days_map() ไม่ส่งมา = ถือว่าทุกหน่วยยังไม่เคยถูกใช้ (เรียงตาม acquired_at
    เหมือนเดิม) acquired_at = NULL ไปท้ายแถวเสมอ tie-break ด้วย code ให้ผลลัพธ์คงที่

    ⚠ ห้ามเอาไปทำ ORDER BY ของ query ที่มี with_for_update() — ลำดับ "ล็อก" ต้องคง Equipment.code
    เหมือนกันทุก transaction ไม่งั้น deadlock (ดู approve_request / bulk_adjust_stock)
    ตัวนี้ใช้เรียง list ที่ล็อกมาแล้วใน memory เท่านั้น จึงไม่กระทบลำดับล็อก
    """
    used = (usage_days or {}).get(eq.id, 0)
    return (used, eq.acquired_at is None, eq.acquired_at or date.min, eq.code)


def _check_magic_bytes(contents: bytes, ext: str) -> None:
    """เนื้อไฟล์ตรงกับนามสกุลจริงไหม — กันไฟล์สคริปต์ที่เปลี่ยนนามสกุลมาเป็นรูป/PDF"""
    signatures = _MAGIC_BYTES.get(ext)
    if not signatures:
        return
    ok = any(contents.startswith(sig) for sig in signatures)
    if ok and ext == ".webp":
        ok = contents[8:12] == b"WEBP"
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="File content does not match its extension.")


async def _read_validated(file: UploadFile, allowed_ext: set[str], max_bytes: int) -> tuple[bytes, str]:
    """ตรวจนามสกุล + ขนาด + เนื้อไฟล์ แล้วคืน (เนื้อไฟล์, นามสกุล) — ด่านเดียวของทุกการอัปโหลดในระบบ"""
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in allowed_ext:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported file type.")
    limit_mb = max_bytes // (1024 * 1024)
    # ต้องเช็คขนาดก่อน read() — endpoint อัปโหลดรูปโปรไฟล์เปิดให้นักศึกษาทุกคนยิงได้
    # ถ้าเช็คหลัง read() ไฟล์ขนาดกี่ GB ก็ถูกโหลดเข้า RAM จนหมดก่อนถึงบรรทัดตรวจ = worker ตาย
    if file.size is not None and file.size > max_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"File too large (max {limit_mb}MB).")
    contents = await file.read()
    if len(contents) > max_bytes:  # เผื่อกรณี .size เป็น None
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"File too large (max {limit_mb}MB).")
    _check_magic_bytes(contents, ext)
    return contents, ext


async def save_upload(
    file: UploadFile, allowed_ext: set[str] = ALLOWED_IMAGE_EXT, max_bytes: int = MAX_IMAGE_BYTES
) -> str:
    """บันทึกไฟล์อัปโหลดลง UPLOAD_DIR แล้วคืน path relative (/uploads/<uuid>.<ext>) สำหรับเก็บในคอลัมน์ url

    ค่า default เป็นชุดของ "รูปภาพ" เพราะเป็นผู้ใช้ส่วนใหญ่ ผู้เรียกที่รับไฟล์ชนิดอื่นส่ง
    allowed_ext/max_bytes มาเอง — จุดตรวจและการเขียนไฟล์อยู่ที่เดียวไม่ต้องก๊อป

    ไฟล์ที่นี่ถูกเสิร์ฟสาธารณะ (StaticFiles) — เอกสารที่มีข้อมูลส่วนบุคคลต้องใช้ save_private_upload
    """
    contents, ext = await _read_validated(file, allowed_ext, max_bytes)
    filename = f"{uuid.uuid4().hex}{ext}"
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    with open(os.path.join(settings.UPLOAD_DIR, filename), "wb") as f:
        f.write(contents)
    return f"/uploads/{filename}"


async def save_private_upload(file: UploadFile, allowed_ext: set[str], max_bytes: int) -> str:
    """บันทึกไฟล์ลงโฟลเดอร์ที่ไม่ได้เสิร์ฟสาธารณะ แล้วคืน **ชื่อไฟล์เปล่า** (ไม่ใช่ URL)

    คืนชื่อไฟล์อย่างเดียวโดยตั้งใจ — จะเปิดได้ต้องผ่าน endpoint ที่ตรวจสิทธิ์เท่านั้น
    ถ้าคืนเป็น path ที่ประกอบเป็น URL ได้ ปลายทางจะเผลอเอาไปแปะเป็นลิงก์ตรงเหมือนของเดิม
    """
    contents, ext = await _read_validated(file, allowed_ext, max_bytes)
    filename = f"{uuid.uuid4().hex}{ext}"
    os.makedirs(settings.PRIVATE_UPLOAD_DIR, exist_ok=True)
    with open(os.path.join(settings.PRIVATE_UPLOAD_DIR, filename), "wb") as f:
        f.write(contents)
    return filename


async def save_image(file: UploadFile) -> str:
    """บันทึกไฟล์รูปอุปกรณ์/รูปโปรไฟล์ — เปลือกบางของ save_upload ที่ล็อกไว้เฉพาะรูปภาพ"""
    return await save_upload(file)


async def get_holders_map(
    db: AsyncSession, equipment_ids: list[uuid.UUID] | None = None
) -> dict[uuid.UUID, list[HolderInfo]]:
    """หน่วยไหนกำลังถูกยืมอยู่จริงบ้าง (approved + ยังไม่คืน) พร้อมรายละเอียดคนถือ — equipment_ids=None คือทั้งระบบ

    คิวรีเดียวได้ทั้ง "ถูกยืมอยู่ไหม" (เดิมใช้ _borrowed_equipment_ids คืนแค่ set id) และ "ใครถือ" (เดิม
    get_holders แยกอีกคิวรี) รวมเป็นฟังก์ชันเดียว — ผู้เรียกที่ต้องการแค่ boolean เช็ค `id in map` ได้เลย
    ไม่ต้องยิง 2 คิวรีซ้อนกันเหมือนก่อน

    คืนเป็น list ต่อ equipment_id (ไม่ใช่ HolderInfo เดี่ยว) เพราะวัสดุสิ้นเปลืองแถวเดียวยืมพร้อมกันได้หลายคน
    คนละจำนวน (ต่างจาก durable ที่ยืมทีละหน่วยจริง ไม่มีทางมีคนถือพร้อมกันหลายคนต่อ 1 แถว) — เดิมใช้ dict
    comprehension ทับ key ซ้ำ เหลือแค่คนสุดท้ายที่ query คืนมา คนอื่นหายไปเงียบ ๆ
    """
    query = (
        select(
            BorrowItem.equipment_id, User.full_name, User.student_id,
            BorrowItem.extended_due_date, BorrowRequest.due_date, BorrowItem.quantity,
        )
        .join(BorrowRequest, BorrowItem.borrow_request_id == BorrowRequest.id)
        .join(User, BorrowRequest.student_id == User.id)
        .where(BorrowRequest.status == "approved", BorrowItem.returned.is_(False))
        # ไม่มี ORDER BY เดิม DB ไม่การันตีลำดับแถวที่คืนมาเลย — โค้ดที่อ่าน holders[0] เป็น "ตัวแทน" คนเดียว
        # (เช่น _build_group_response, list_equipment) จะได้คนละคนสลับกันไปมาระหว่างการเรียกแต่ละครั้งทั้งที่
        # ข้อมูลไม่ได้เปลี่ยน — เรียงชื่อแล้วตาม BorrowItem.id กันเผื่อชื่อซ้ำ ให้ผลลัพธ์คงที่เสมอ
        .order_by(User.full_name, BorrowItem.id)
    )
    if equipment_ids is not None:
        query = query.where(BorrowItem.equipment_id.in_(equipment_ids))
    result = await db.execute(query)
    holders_map: dict[uuid.UUID, list[HolderInfo]] = {}
    for eq_id, name, sid, ext, due, qty in result.all():
        holders_map.setdefault(eq_id, []).append(
            HolderInfo(holder_name=name, student_number=sid, due_date=ext or due, quantity=qty)
        )
    return holders_map


async def _apply_status_filter(db: AsyncSession, query, filter_status: str | None):
    """status ปกติ (available/damaged/...) filter ตรงคอลัมน์เดิม + เพิ่ม filter พิเศษที่ derive จากตาราง/
    เกณฑ์อื่น ไม่ใช่ค่าจริงใน equipment.status — ใช้ในหน้าจัดการอุปกรณ์แทนการต้องกดเข้ามาจาก dashboard:
    - low_stock: เฉพาะ consumable ที่ต่ำกว่าเกณฑ์ (mirror สูตรเดียวกับ dashboard_service.get_summary)
    - borrowed: มีของออกไปจริงผ่าน BorrowItem ที่ยังไม่คืน (คนละอย่างกับ status="available" ที่กดลบไม่ได้
      สื่อว่า "ยืมได้" ไม่ใช่ "กำลังถูกยืม")

    ใช้กับ list_equipment (ไม่ยุบกลุ่ม) เท่านั้น — list_equipment_grouped ต้อง filter "borrowed" ที่ระดับกลุ่ม
    แยกต่างหาก (ดู comment ใน list_equipment_grouped) ไม่งั้นยอดรวมของการ์ดจะผิด เพราะกรองตัดหน่วย
    พี่น้องในกลุ่มเดียวกันที่ไม่เข้าเงื่อนไขออกจาก query ตั้งแต่ต้น
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
    # ของที่ยังไม่มีราคา — ใช้ไล่เติมราคาให้ครบทุกชิ้น (ของเก่าจากทะเบียนที่ไม่มีคอลัมน์ราคา)
    if filter_status == "no_price":
        return query.where(Equipment.unit_value.is_(None))
    # ของที่ยังไม่รู้ว่าได้มาเมื่อไหร่ — คำนวณอายุ/ค่าเสื่อมไม่ได้จนกว่าจะเติม
    if filter_status == "no_acquired_at":
        return query.where(Equipment.acquired_at.is_(None))
    # "available"/"unavailable" ต้องรวม is_borrowable เข้าไปด้วย ไม่ใช่แค่คอลัมน์ status ตรง ๆ — ของประจำห้อง
    # (is_borrowable=false) status ยังเป็น "available" อยู่ (import ไฟล์ทะเบียนใหม่ไม่แตะฟิลด์นี้) จึงต้องกรอง
    # ทั้งสองคอลัมน์ควบกันไม่งั้นของประจำห้องจะโผล่ปนกลุ่ม "พร้อมให้ยืม" และไม่โผล่ในกลุ่ม "ไม่อนุญาตให้ยืม" เลย
    if filter_status == "available":
        return query.where(Equipment.status == "available", Equipment.is_borrowable == True)  # noqa: E712
    if filter_status == "unavailable":
        return query.where(or_(Equipment.status == "unavailable", Equipment.is_borrowable == False))  # noqa: E712
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
        query = query.where(_search_clause(search))

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
    await attach_book_values(db, items)
    holders_map = await get_holders_map(db)
    responses = []
    for eq in items:
        holders = holders_map.get(eq.id, [])
        responses.append(EquipmentResponse.model_validate(eq, from_attributes=True).model_copy(
            update={
                "is_currently_borrowed": eq.id in holders_map,
                "holder": holders[0] if holders else None,
                "holders": holders,
            }
        ))
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
    rows: list[Equipment], holders_map: dict[uuid.UUID, list[HolderInfo]]
) -> EquipmentGroupResponse:
    """ประกอบการ์ดยุบกลุ่ม — field แสดงผลอื่น ๆ ใช้ของหน่วยรหัสต่ำสุด (rows เรียงมาแล้ว)

    holder เจาะจงหน่วยตัวแทนเท่านั้น (มีความหมายจริงเฉพาะการ์ดหน่วยเดียว unit_count==1 — การ์ดหลายหน่วย
    ต้องกางดูรายหน่วยแทนเพราะแต่ละหน่วยอาจมีคนละคนถือ ไม่มี "คนเดียว" ให้โชว์ตรงนี้) — เอา holders[0] ของ
    หน่วยตัวแทนมาใช้ (ไม่กระทบจริงเพราะมีแค่ consumable เท่านั้นที่ถือพร้อมกันได้หลายคนต่อแถว และ consumable
    ไม่เข้ามาที่นี่เลย เพราะ _group_key ไม่ยุบรวม consumable — unit_count เป็น 1 เสมออยู่แล้ว)
    """
    rep = rows[0]
    eligible = [r for r in rows if _is_eligible(r)]
    rep_holders = holders_map.get(rep.id, [])
    base = EquipmentResponse.model_validate(rep, from_attributes=True).model_dump()
    base["quantity_total"] = sum(r.quantity_total for r in rows)
    base["quantity_available"] = sum(r.quantity_available for r in eligible)
    base["is_currently_borrowed"] = rep.id in holders_map
    base["holder"] = rep_holders[0] if rep_holders else None
    base["holders"] = rep_holders
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
    # "borrowed" ต้อง filter ที่ "กลุ่มไหนมีหน่วยเข้าเงื่อนไขบ้าง" ไม่ใช่กรองที่ query แถวก่อน
    # group — ถ้ากรองที่แถวเลย จะดึงมาแค่หน่วยที่เข้าเงื่อนไข แล้วเอาไปรวมยอด quantity_total/available เป็นยอด
    # ของกลุ่มทำให้ผิด (เช่น Arduino-UNO-R3 มี 42 หน่วย ยืมอยู่ 1 → เห็น "0/1" แทนที่จะเป็น "41/42" ที่ถูกต้อง)
    # ต้องดึงทุกหน่วยของกลุ่มมาคำนวณยอดก่อน แล้วค่อยกรองว่าจะโชว์การ์ดไหนทีหลัง
    # ตัวกรองที่ต้องตัดสินที่ระดับ "กลุ่ม" ไม่ใช่ระดับแถว — เหตุผลเดียวกับ borrowed ด้านบน:
    # ของกลุ่มเดียวกัน 42 หน่วย ถ้าขาดราคาแค่ 3 หน่วย การกรองที่แถวจะเหลือ 3 หน่วยไปรวมยอดเป็นของทั้งกลุ่ม
    group_level = filter_status in ("borrowed", "no_price", "no_acquired_at")
    query = await _apply_status_filter(db, query, None if group_level else filter_status)
    if search:
        query = query.where(_search_clause(search))
    query = query.options(selectinload(Equipment.categories)).order_by(Equipment.code)

    rows = list((await db.execute(query)).scalars().all())
    await attach_book_values(db, rows)

    groups: dict[tuple, list[Equipment]] = {}
    for eq in rows:
        groups.setdefault(_group_key(eq), []).append(eq)

    holders_map = await get_holders_map(db)
    if group_level:
        keep = {
            "borrowed": lambda m: m.id in holders_map,
            "no_price": lambda m: m.unit_value is None,
            "no_acquired_at": lambda m: m.acquired_at is None,
        }[filter_status]
        groups = {key: members for key, members in groups.items() if any(keep(m) for m in members)}

    cards = [_build_group_response(members, holders_map) for members in groups.values()]
    cards.sort(key=lambda c: (not (c.is_borrowable and c.status == "available" and c.quantity_available > 0), c.name))

    total = len(cards)
    start = (page - 1) * page_size
    page_items = cards[start:start + page_size]
    return PaginatedEquipmentGroup(items=page_items, total=total, page=page, page_size=page_size,
                                   summary=_summarize_cards(cards))


def _summarize_cards(cards: list[EquipmentGroupResponse]) -> EquipmentListSummary:
    """สรุปจำนวน "ชิ้นจริง" ของผลการค้นหาทั้งหมด แยกตามประเภท

    การ์ด 1 ใบ = 1 รุ่น (ยุบหลายหน่วยแล้ว) ตัวเลขที่ผู้ใช้ต้องเห็นคือจำนวนชิ้นจริง ไม่ใช่จำนวนการ์ด —
    "187 รายการ" ทำให้เข้าใจผิดว่าคลังมีของแค่ 187 ชิ้น ทั้งที่ยุบมาจากพันกว่าหน่วย (8 ก.ย. 69)
    คิดจาก cards ที่กรองแล้วในหน่วยความจำ ไม่ต้องยิง query เพิ่ม
    """
    by_type: dict[str, dict[str, int]] = {}
    for c in cards:
        acc = by_type.setdefault(c.item_type, {"groups": 0, "pieces": 0, "available": 0})
        acc["groups"] += 1
        acc["pieces"] += c.quantity_total
        acc["available"] += c.quantity_available
    order = {"durable": 0, "material": 1, "consumable": 2}
    return EquipmentListSummary(
        groups=len(cards),
        pieces=sum(a["pieces"] for a in by_type.values()),
        available=sum(a["available"] for a in by_type.values()),
        by_type=[EquipmentTypeSummary(item_type=t, **a)
                 for t, a in sorted(by_type.items(), key=lambda kv: order.get(kv[0], 9))],
    )


async def get_equipment(db: AsyncSession, equipment_id: uuid.UUID) -> Equipment:
    result = await db.execute(
        select(Equipment).where(Equipment.id == equipment_id).options(selectinload(Equipment.categories))
    )
    eq = result.scalar_one_or_none()
    if not eq:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Equipment not found.")
    await attach_book_values(db, [eq])
    return eq


async def get_equipment_group_detail(db: AsyncSession, equipment_id: uuid.UUID) -> EquipmentGroupDetailResponse:
    """รายละเอียดอุปกรณ์แบบยุบกลุ่ม + ผู้ครอบครองทั้งกลุ่ม

    equipment_id เป็นหน่วยไหนในกลุ่มก็ได้ (หน้าเว็บส่งมาจากการ์ดที่โชว์ = หน่วยรหัสต่ำสุดอยู่แล้ว)
    """
    eq = await get_equipment(db, equipment_id)
    members = [eq] if eq.item_type == "consumable" else await find_group_members(db, eq.name, eq.item_type)
    await attach_book_values(db, members)
    holders_map = await get_holders_map(db, [m.id for m in members])
    usage = await usage_days_map(db, [m.id for m in members])
    group = _build_group_response(members, holders_map)
    unit_summaries = []
    for m in members:
        m_holders = holders_map.get(m.id, [])
        unit_summaries.append(EquipmentUnitSummary.model_validate(m, from_attributes=True).model_copy(
            update={
                "is_currently_borrowed": m.id in holders_map,
                "holder": m_holders[0] if m_holders else None,
                "days_borrowed": usage.get(m.id, 0),
            }
        ))
    # flatten list ของ list — holders_map คืนหลายคนต่อ equipment_id ได้แล้ว (ดู get_holders_map) ต้องรวมทุกคน
    # ของทุกหน่วยในกลุ่มมาเป็น list เดียว ไม่ใช่แค่ list ของหน่วยตัวแทนแบบเดิม (group.model_dump() มี key
    # "holders" ของหน่วยตัวแทนอยู่แล้วจาก _build_group_response ต้อง exclude ก่อนไม่งั้นชนกับ kwarg ด้านล่าง)
    all_holders = [h for hs in holders_map.values() for h in hs]
    return EquipmentGroupDetailResponse(
        **group.model_dump(exclude={"holders"}), holders=all_holders, members=unit_summaries,
    )


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


def _validate_durable_code(code: str) -> None:
    """บังคับรหัสครุภัณฑ์ (durable) ต้องเป็นตัวเลข 15 หลักพอดี — นับเฉพาะตัวเลขในสตริง (ตัด "-" ออก)

    เรียกเฉพาะตอน "เปลี่ยนเข้า durable" จาก material/consumable เท่านั้น (create_equipment/update_equipment/
    bulk_update_equipment) — ไม่ retroactive กับแถวที่เป็น durable อยู่แล้ว เพราะของเดิมที่ import จากทะเบียนจริง
    หลายตัวใช้รหัสภายในสั้นกว่านี้ (เช่น "212001") ต้องไม่บล็อกการแก้ไขปกติของแถวเหล่านั้น
    """
    digits = re.sub(r"\D", "", code or "")
    if len(digits) != 15:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f'เปลี่ยนเป็นครุภัณฑ์ได้เฉพาะรหัสที่เป็นตัวเลข 15 หลักเท่านั้น (รหัส "{code}" มี {len(digits)} หลัก)',
        )


async def create_equipment(db: AsyncSession, admin: User, body: EquipmentCreate) -> Equipment:
    code = body.code
    if not code:
        if body.item_type != "consumable":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail="จำเป็นต้องระบุรหัสอุปกรณ์ (เว้นว่างได้เฉพาะวัสดุสิ้นเปลือง)")
        existing_codes = set((await db.execute(select(Equipment.code))).scalars().all())
        code = _generate_consumable_code(body.name, existing_codes)

    if body.item_type == "durable":
        _validate_durable_code(code)

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
                                    "quantity": eq.quantity_total, "item_type": eq.item_type,
                                    "unit_value": float(eq.unit_value) if eq.unit_value is not None else None})
    await db.commit()
    return await get_equipment(db, eq.id)


def _search_clause(search: str):
    """เงื่อนไขค้นหาอุปกรณ์ — ที่เดียวสำหรับทั้งหน้ารายการและหน้ากลุ่ม ไม่งั้นสองหน้าค้นเจอคนละชุด

    ครอบ 4 ช่องตามมาตรฐานการตั้งชื่อ (เฟส 8): ชื่อ · รหัสทะเบียน · รุ่น · ซีเรียล
    เพราะคนค้นด้วยสิ่งที่ตัวเองรู้ — นักศึกษาพิมพ์ "DHT11" (รุ่น) แอดมินพิมพ์เลขครุภัณฑ์ ช่างพิมพ์ SN
    """
    kw = f"%{search.strip()}%"
    return or_(
        Equipment.name.ilike(kw),
        Equipment.code.ilike(kw),
        Equipment.model_number.ilike(kw),
        Equipment.manufacturer.ilike(kw),
        Equipment.serial_number.ilike(kw),
    )


# ฟิลด์ที่กระทบตัวเลขย้อนหลัง (ค่าเสื่อม/มูลค่าในใบยืมเก่า/ค่าเสียหายที่เรียกเก็บ) — superadmin เท่านั้น
# ตามการแบ่งฟอร์มตามความเสี่ยงในเฟส 8 · ตอน "สร้างใหม่" ไม่กั้น เพราะของทุกชิ้นต้องมีราคา+วันที่ได้มา
# ตั้งแต่แรกอยู่แล้ว (EquipmentCreate บังคับ) คนกรอกคือผู้ดูแลคลังที่รับของเข้าทะเบียน
FINANCE_FIELDS = ("unit_value", "book_value_override", "acquired_at", "useful_life_years")


def _assert_can_edit_finance(admin: User, eq: Equipment, changed: dict) -> None:
    """กันผู้ดูแลคลังแก้ตัวเลขการเงินของอุปกรณ์ที่มีอยู่แล้ว — ต้องยื่นคำขอให้ superadmin แก้ผ่าน
    /change-requests แทน (ดู CLAUDE.md หัวข้อ 6) เทียบค่าจริงก่อน ส่งค่าเดิมซ้ำมาไม่นับว่าแก้
    """
    if is_superadmin(admin):
        return
    touched = [f for f in FINANCE_FIELDS if f in changed and changed[f] != getattr(eq, f)]
    # Numeric จาก DB เป็น Decimal ส่วนที่ส่งมาเป็น float — เทียบตรง ๆ จะไม่เท่ากันทั้งที่ค่าเดียวกัน
    touched = [f for f in touched
               if not (isinstance(getattr(eq, f), Decimal) and changed[f] is not None
                       and Decimal(str(changed[f])) == getattr(eq, f))]
    if touched:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="แก้ข้อมูลทะเบียน/การเงินได้เฉพาะผู้ดูแลระบบสูงสุด (ยื่นคำขอแก้ไขข้อมูลแทนได้)",
        )


async def update_equipment(db: AsyncSession, admin: User, equipment_id: uuid.UUID, body: EquipmentUpdate) -> Equipment:
    """แก้ไขอุปกรณ์ — แก้ code/item_type ได้แม้เคยมีประวัติการยืม เพราะ BorrowItem เก็บ snapshot

    equipment_name/code/unit/item_type_snapshot เป็นคอลัมน์จริงบน BorrowItem ไม่ใช่ live join
    (ดู borrow_service.py create_request/approve_request) แก้ตรงนี้จึงไม่กระทบใบยืมเก่าเลย
    """
    eq = await get_equipment(db, equipment_id)
    # exclude_unset (ไม่ใช่ exclude_none) — ต้องแยก "ไม่ได้ส่งฟิลด์นี้มา" ออกจาก "ส่งมาเป็น null ตั้งใจล้างค่า"
    # เช่น SN ที่แอดมินกรอกผิดแล้วอยากลบทิ้ง — exclude_none เดิมจะตัด null ทิ้งเหมือนไม่ได้ส่งมา ลบไม่ได้เลย
    changed = body.model_dump(exclude_unset=True, exclude={"category_ids", "status_reason"})
    # เปลี่ยนสถานะ = action ที่ต้องอธิบายได้ ไม่ใช่แค่แก้ค่าในฟอร์ม (เฟส 8) — เหตุผลลง audit คู่กับ diff
    status_reason = (body.status_reason or "").strip()
    if "status" in changed and changed["status"] != eq.status and not status_reason:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="กรุณาระบุเหตุผลที่เปลี่ยนสถานะอุปกรณ์")
    # ของทุกชิ้นต้องมีราคา (feedback อาจารย์) — แก้เป็นค่าอื่นได้ แต่ล้างทิ้งไม่ได้ ต่างจาก SN/หมวดหมู่
    # ที่ null = ตั้งใจล้างค่า (ดูคอมเมนต์ exclude_unset ด้านบน) book_value_override ยังล้างได้ตามปกติ
    if "unit_value" in changed and changed["unit_value"] is None:
        changed.pop("unit_value")
    # เช็คสิทธิ์หลัง normalize — ฟอร์มส่งทั้งก้อนทุกครั้ง ค่าที่ไม่ได้แก้จริงต้องไม่ทำให้โดน 403
    _assert_can_edit_finance(admin, eq, changed)
    if "name" in changed:
        changed["name"] = _normalize_name(changed["name"])
    if "code" in changed and changed["code"] != eq.code:
        dup_code = await db.execute(
            select(Equipment).where(Equipment.code == changed["code"], Equipment.id != equipment_id)
        )
        if dup_code.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Equipment code already exists.")
    # เช็คซ้ำเฉพาะตอนตั้งค่าจริง (truthy) — ล้าง SN เป็น None ต้องไม่ชนกัน เพราะ partial unique index
    # (ix_equipment_serial_number_unique) เจาะจง WHERE serial_number IS NOT NULL ไว้แล้วว่า NULL ซ้ำกันได้
    if changed.get("serial_number") and changed["serial_number"] != eq.serial_number:
        dup_sn = await db.execute(
            select(Equipment).where(Equipment.serial_number == changed["serial_number"], Equipment.id != equipment_id)
        )
        if dup_sn.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Serial number already exists.")

    # เปลี่ยนเข้า durable (จาก material/consumable) ต้องรหัสครบ 15 หลัก — ใช้ code ใหม่ถ้า request นี้เปลี่ยน code
    # ด้วย ไม่งั้นใช้ของเดิม (ไม่ retroactive กับแถวที่เป็น durable อยู่แล้ว ดู _validate_durable_code)
    if changed.get("item_type") == "durable" and eq.item_type != "durable":
        _validate_durable_code(changed.get("code", eq.code))

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

    # field_diffs ว่าง = ส่งค่าเดิมมาซ้ำ (เช่น unit_value: null ที่ diff_fields กรองทิ้งไปแล้ว) ไม่ log entry
    # เปล่าๆ ที่ไม่มีอะไรอยู่ข้างใต้ ไม่งั้นเป็น noise ใน timeline รายอุปกรณ์ (เจอจาก QA จริง)
    if field_diffs:
        detail = {"code": eq.code, "changes": field_diffs}
        if status_reason and "status" in field_diffs:
            detail["reason"] = status_reason
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
            # แยกแถวรวมเป็นรายชิ้น = ของชิ้นเดิม ไม่ใช่ของใหม่ → อายุ/เกณฑ์ค่าเสื่อมต้องตามไปทุกหน่วย
            # (ถ้าปล่อยให้ acquired_at เป็น None ที่นี่ อายุจะหายทันทีที่แอดมินกดแยกรายชิ้น)
            acquired_at=eq.acquired_at,
            useful_life_years=eq.useful_life_years,
            book_value_override=eq.book_value_override,
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
            # ต่างจาก split โดยตั้งใจ — restock = ซื้อของเพิ่มเข้าคลังจริง หน่วยใหม่จึงเริ่มนับอายุวันนี้
            # ไม่ copy acquired_at ของแถวต้นแบบ (จะทำให้ของใหม่แก่เท่าของเก่าทันที) และไม่ copy override ราคา
            acquired_at=date.today(), useful_life_years=eq.useful_life_years,
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


async def adjust_stock(
    db: AsyncSession, admin: User, equipment_id: uuid.UUID,
    new_available: int, reason: str, photo_urls: list[str],
) -> Equipment:
    """ปรับ quantity_available ให้ตรงกับที่นับได้จริง — quantity_total ไม่เปลี่ยน ต่างจาก restock_equipment
    ที่บวกเพิ่ม (ซื้อของใหม่) อันนี้ SET ตรง ๆ (แก้ยอดให้ตรงการนับจริง เช่นของหายไม่ผ่านระบบยืม)

    quantity_available คือ "จำนวนที่ไม่ได้ถูกยืมออกอยู่" อยู่แล้ว (ยืมออก = total - available) ตั้งค่าต่ำกว่า
    เดิมจึงแปลว่า "ของหาย/ขาดหายไปมากกว่าที่ระบบยืม-คืนบันทึกไว้" ตรงกับ use case นี้พอดี ไม่ต้องมี guard เพิ่ม
    นอกจาก 0 <= new_available <= quantity_total
    """
    eq = (await db.execute(
        select(Equipment).where(Equipment.id == equipment_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )).scalar_one_or_none()
    if not eq:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Equipment not found.")
    if new_available > eq.quantity_total:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"new_available ({new_available}) cannot exceed quantity_total ({eq.quantity_total}).",
        )

    old_available = eq.quantity_available
    eq.quantity_available = new_available
    await audit_service.log_action(db, admin, "adjust_stock", "equipment", eq.id, {
        "code": eq.code, "name": eq.name,
        "old_available": old_available, "new_available": new_available,
        "reason": reason, "photo_urls": photo_urls or None,
    })
    await db.commit()
    return await get_equipment(db, eq.id)


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
    db: AsyncSession, admin: User, equipment_ids: list[uuid.UUID], body: EquipmentBulkUpdate,
    status_reason: str | None = None,
) -> BulkUpdateResult:
    """แก้ไขหลายหน่วยพร้อมกัน (เช่น ย้ายสถานที่ทั้ง 12 หน่วยของรุ่นเดียวกัน) — all-or-nothing ต่างจาก
    bulk_delete_equipment เพราะการแก้ location/status ไม่มีเหตุผลที่ควร "แก้ได้บางชิ้น" เซสชันเดียว
    commit ครั้งเดียว, audit เป็น 1 entry รวม (ไม่ log ทีละแถว)

    ข้อยกเว้นเดียว: เปลี่ยนเข้า durable — แถวที่รหัสไม่ครบ 15 หลัก (ดู _validate_durable_code) ถูกข้าม
    แบบ best-effort ใส่ลง failed แทน ไม่ทำให้ทั้ง batch ล้ม (เหมือน bulk_retire/bulk_delete) เพราะของเดิม
    ที่เลือกมาพร้อมกันมักปนรหัสที่ปฏิรูปแล้วกับยังไม่ปฏิรูป
    """
    changed = body.model_dump(exclude_none=True, exclude={"category_ids"})
    if not changed and body.category_ids is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ไม่มีอะไรจะแก้ไข")
    # กฎเดียวกับแก้ทีละชิ้น (เฟส 8) — ไม่งั้นแก้หลายรายการพร้อมกันกลายเป็นทางลัดข้ามด่านสิทธิ์/เหตุผล
    if not is_superadmin(admin) and any(f in changed for f in FINANCE_FIELDS):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="แก้ข้อมูลทะเบียน/การเงินได้เฉพาะผู้ดูแลระบบสูงสุด (ยื่นคำขอแก้ไขข้อมูลแทนได้)")
    status_reason = (status_reason or "").strip()
    if "status" in changed and not status_reason:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="กรุณาระบุเหตุผลที่เปลี่ยนสถานะอุปกรณ์")
    if "name" in changed:
        changed["name"] = _normalize_name(changed["name"])

    rows = [await get_equipment(db, eq_id) for eq_id in equipment_ids]  # 404 ถ้ามี id ที่ไม่มีจริง

    failed: list[BulkDeleteFailure] = []
    if changed.get("item_type") == "durable":
        valid_rows = []
        for eq in rows:
            if eq.item_type != "durable":
                try:
                    _validate_durable_code(eq.code)
                except HTTPException as e:
                    failed.append(BulkDeleteFailure(equipment_id=eq.id, reason=str(e.detail)))
                    continue
            valid_rows.append(eq)
        rows = valid_rows
        if not rows:
            return BulkUpdateResult(updated=[], failed=failed)

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
        {"count": len(rows), "set": audit_set, "equipment_ids": [str(e.id) for e in rows],
         **({"reason": status_reason} if status_reason and "status" in changed else {})},
    )
    await db.commit()
    ids = [e.id for e in rows]
    result = await db.execute(
        select(Equipment).where(Equipment.id.in_(ids)).options(selectinload(Equipment.categories))
    )
    return BulkUpdateResult(updated=list(result.scalars().all()), failed=failed)


async def bulk_adjust_stock(
    db: AsyncSession, admin: User, equipment_ids: list[uuid.UUID], delta: int, reason: str
) -> BulkAdjustStockResult:
    """ปรับยอดคงเหลือของหลายรายการพร้อมกันด้วยจำนวน delta เดียว

    **ความหมายของ delta ต่างกันตามชนิดแถว** (แก้ 8 ก.ย. 69 หลังผู้ใช้รายงานว่า "ปรับหลายรายการไม่ได้"):
    - แถวที่เป็นก้อน (`quantity_total > 1` เช่นวัสดุสิ้นเปลือง) → บวก/ลบกับแถวนั้นตรง ๆ
    - แถวที่เป็นหน่วยเดี่ยว (`quantity_total == 1` คือของที่แยกรายชิ้นแล้ว) → คิดเป็น **กองรวม**:
      -3 = ปิดการใช้งาน 3 หน่วยแรกที่ยังว่าง · +3 = เปิดคืน 3 หน่วยที่ปิดอยู่
      (เดิมลบทีละแถว = ติ๊กทั้งรุ่นแล้วกด -1 ครั้งเดียว สต็อกทั้งรุ่นกลายเป็น 0)

    clamp อิสระต่อแถว (0 <= quantity_available <= quantity_total - outstanding_qty) โดย outstanding_qty
    คือจำนวนที่ถูกยืมออกไปจริง (approved + ยังไม่คืน ดู get_holders_map) ณ ขณะนี้ — ต้องหักออกจากเพดานบนเสมอ
    ไม่ใช่แค่ quantity_total เฉยๆ ไม่งั้นแอดมินปรับยอดว่างขึ้นไปทับจำนวนที่ยังค้างอยู่ในมือคนยืมได้ (เช่น total=10
    มี 3 หน่วยถูกยืมอยู่ available=7 ถ้า clamp ที่ total เฉยๆ +3 จะดันเป็น 10) พอมีคนคืนของ 3 หน่วยนั้นจริงเข้ามา
    ทีหลัง quantity_available += quantity จะทะลุ quantity_total ชน ck_equipment_quantity_available_range
    (IntegrityError 500 ตอน commit การคืน — ทำให้คืนของไม่ได้เลย)

    best-effort เหมือน bulk_delete/bulk_retire/bulk_update — id ที่ไม่มีจริงถูกใส่ลง failed แทนที่จะ abort
    ทั้ง batch ด้วย 404, แถวที่เหลือยัง commit จริง — ids ซ้ำถูก dedupe ก่อน (ไม่งั้น delta ถูกใช้ซ้ำหลายรอบ
    กับแถวเดียว) และล็อกแถวเรียงตาม Equipment.code เสมอ (ไม่ใช่ id หรือลำดับที่ผู้ใช้ส่งมา) — ต้องตรงกับลำดับล็อก
    ใน borrow_service.approve_request (เรียงตาม code เหมือนกัน) ไม่งั้น deadlock ได้จริงเวลา bulk-adjust ชุดหนึ่ง
    ชนกับอนุมัติคำขอยืมอีกชุดที่แตะอุปกรณ์รุ่นเดียวกันคาบเกี่ยวกันพร้อมกันคนละลำดับ

    holders_map ต้องอ่าน "หลัง" ล็อกแถวเสร็จแล้วเท่านั้น (ไม่ใช่ก่อน) — ไม่งั้นมี race window แคบๆ ที่ approve_request
    อีก transaction หนึ่ง commit คั่นกลางระหว่างอ่าน holders กับตอนล็อกแถวจริง ทำให้ outstanding_qty ที่อ่านมาเก่ากว่า
    ความจริง แล้ว upper_bound คำนวณสูงเกินไป กลับไปเจอบั๊กเดิมที่ docstring ด้านบนอธิบายไว้แบบแคบลง
    """
    ids = list(dict.fromkeys(equipment_ids))  # dedupe รักษาลำดับเดิม — id ซ้ำในคำขอเดียวไม่ควรโดน delta ซ้ำ

    rows = (await db.execute(
        select(Equipment).where(Equipment.id.in_(ids))
        .order_by(Equipment.code)
        .with_for_update()
        .execution_options(populate_existing=True)
    )).scalars().all()
    rows_by_id = {eq.id: eq for eq in rows}

    holders_map = await get_holders_map(db, ids)  # อ่านหลังล็อกแถวเสร็จ กัน race กับ transaction อื่นที่แก้ไข
                                                   # ระหว่างทาง (ดู docstring ด้านบน) — ยังครั้งเดียวก่อน loop กัน N+1

    failed: list[BulkDeleteFailure] = []
    updated_ids: list[uuid.UUID] = []
    # แถวที่เป็น "หน่วยเดี่ยว" (quantity_total == 1) ต้องคิดแบบ **กองรวม** ไม่ใช่บวก/ลบทีละแถว
    # เหตุผล: ครุภัณฑ์/วัสดุที่แยกเป็นรายชิ้นแล้ว 1 แถว = 1 ชิ้น ติ๊กทั้งรุ่น 42 หน่วยแล้วใส่ -1
    # ถ้าลบทีละแถวจะกลายเป็น "ทั้งรุ่นเหลือ 0" ทันที (เจอจริง 8 ก.ย. 69) ทั้งที่แอดมินหมายถึง
    # "นับแล้วรุ่นนี้ขาดไป 1 ชิ้น" — ส่วน +1 ก็ถูก clamp ที่ 1 ทุกแถวจนดูเหมือนกดแล้วไม่มีอะไรเกิดขึ้น
    unit_budget = abs(delta)
    for eq_id in ids:
        eq = rows_by_id.get(eq_id)
        if eq is None:
            failed.append(BulkDeleteFailure(equipment_id=eq_id, reason="Equipment not found."))
            continue
        outstanding_qty = sum(h.quantity for h in holders_map.get(eq_id, []))
        old_available = eq.quantity_available
        upper_bound = eq.quantity_total - outstanding_qty

        if eq.quantity_total == 1:
            # กองรวม: ไล่ปิด/เปิดทีละหน่วยจนครบจำนวนที่สั่ง หน่วยที่เหลือไม่ถูกแตะ
            if unit_budget > 0 and delta < 0 and old_available > 0:
                new_available, unit_budget = 0, unit_budget - 1
            elif unit_budget > 0 and delta > 0 and old_available == 0 and upper_bound > 0:
                new_available, unit_budget = 1, unit_budget - 1
            else:
                new_available = old_available  # โควตาหมด/ถูกยืมอยู่/เป็นแบบที่ต้องการอยู่แล้ว
        else:
            new_available = max(0, min(upper_bound, old_available + delta))

        eq.quantity_available = new_available
        # เขียน audit เฉพาะแถวที่เปลี่ยนจริง — แถวที่ชนเพดาน/ถูกข้ามไม่ต้องรก timeline
        # (แต่ยังคืนใน updated เพื่อให้หน้าเว็บรีเฟรชค่าล่าสุดของทุกแถวที่เลือกได้)
        if new_available != old_available:
            await audit_service.log_action(db, admin, "bulk_adjust_stock", "equipment", eq.id, {
                "code": eq.code, "name": eq.name,
                "old_available": old_available, "new_available": new_available,
                "delta": delta, "reason": reason,
            })
        updated_ids.append(eq.id)
    await db.commit()
    result = await db.execute(
        select(Equipment).where(Equipment.id.in_(updated_ids)).options(selectinload(Equipment.categories))
    )
    return BulkAdjustStockResult(updated=list(result.scalars().all()), failed=failed)


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
            # log เก่าก่อนเฟสนี้ไม่มี unit_value → None แล้ว PDF เว้นช่องว่างไว้ให้กรอกมือเหมือนเดิม
            "unit_value": (log.detail or {}).get("unit_value"),
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


async def generate_qr(db: AsyncSession, equipment_id: uuid.UUID, frontend_origin: str | None = None) -> bytes:
    """สร้าง QR code ชี้ไปหน้ารายละเอียดอุปกรณ์ — ใช้ frontend_origin ที่ router ตรวจจาก request จริง
    ถ้ามี (เครื่อง dev ที่ IP เปลี่ยนบ่อย) แทน settings.FRONTEND_URL คงที่ กัน QR ชี้ผิดเครื่อง/ผิด IP
    """
    eq = await get_equipment(db, equipment_id)
    origin = frontend_origin or settings.FRONTEND_URL
    return generate_qr_png(f"{origin}/equipment/{eq.id}")


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
