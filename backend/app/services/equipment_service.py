import os
import re
import uuid
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import TypeVar

from fastapi import HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import ColumnElement, func, or_, select
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
from app.services import audit_service, settings_service
from app.utils.qrcode_gen import generate_qr_png
from app.utils.roles import is_staff, is_superadmin
from app.utils.study_year import compute_study_year

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
    age_days = ((today or date.today()) - eq.acquired_at).days
    # clamp 0..อายุ — ของที่ลงวันที่ได้มาไว้ในอนาคตยังไม่เสื่อม, ของที่เกินอายุแล้วหยุดที่มูลค่าซาก
    depreciated_days = min(max(age_days, 0), life_days(eq, years_default))
    return round(cost - daily_depreciation(eq, years_default, salvage) * depreciated_days, 2)


def life_days(eq: Equipment, years_default: int) -> float:
    """อายุการใช้งานเป็นวัน (ว่าง = ค่ากลางใน settings) — ฐานของ book_value()/daily_depreciation()"""
    return max(eq.useful_life_years or years_default, 1) * 365.25


def daily_depreciation(eq: Equipment, years_default: int, salvage: float) -> float | None:
    """ค่าเสื่อมต่อวันแบบเส้นตรง = (ราคาทุน − มูลค่าซาก) ÷ อายุการใช้งาน (วิธีของกรมบัญชีกลาง)

    **จุดเดียว** ของสูตรค่าเสื่อม — book_value() กับหน้าสถิติความคุ้มค่า (dashboard_service.get_utilization)
    ใช้ตัวนี้ร่วมกัน ห้ามคิดซ้ำที่อื่น ไม่งั้นมูลค่าตามบัญชีกับต้นทุนการใช้งานจะเล่าคนละเรื่อง
    None = ยังไม่กรอกราคา
    """
    if eq.unit_value is None:
        return None
    cost = float(eq.unit_value)
    return 0.0 if cost <= salvage else (cost - salvage) / life_days(eq, years_default)


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


def borrowed_days_expr(since: ColumnElement | None = None, until: ColumnElement | None = None) -> ColumnElement:
    """SQL expression: จำนวนวันที่ borrow_item หนึ่งแถวออกจากคลัง (ยังไม่คืน = นับถึงตอนนี้)

    since=None (ค่าเริ่มต้น — ใช้จ่ายของ/สถิติความคุ้มค่า): นับขั้นต่ำ 1 วันต่อการยืม 1 ครั้ง — ยืมเช้าคืนบ่าย
    ก็คือของไม่อยู่ในคลังวันนั้น ถ้าปล่อยเป็น 0 จะกลายเป็นว่าหน่วยที่ถูกหยิบไปยืมสั้น ๆ ทุกวันยังถูกนับว่า
    "ไม่เคยถูกใช้" แล้วโดนจ่ายซ้ำอยู่ชิ้นเดียว ปัดเศษแบบ round ไม่ใช่ ceil — ยืม 10 วันกับอีก 3 วินาทีต้องได้
    10 ไม่ใช่ 11

    since=<timestamp column/ค่า> (ใช้สูตรคุณภาพ equipment_service.current_quality เท่านั้น — ห้ามเขียนสูตร
    นับวันยืมซ้ำที่อื่นตาม CLAUDE.md): นับเฉพาะช่วงที่ยืมอยู่ "หลัง" since เท่านั้น ไม่มีขั้นต่ำ 1 วัน —
    ช่วงที่ยืมทั้งหมดอยู่ก่อน since (คืนไปแล้วก่อนวันประเมิน) ต้องนับ 0 ไม่ใช่ 1 ช่วงที่คาบเกี่ยว since
    (ยืมมาก่อนประเมิน ยังไม่คืนตอนประเมิน) ถูกตัดให้เริ่มนับจาก since แทน ไม่ใช่ตั้งแต่ approved_at จริง

    since+until (หน้าสถิติความคุ้มค่าแบบเลือกช่วงเวลา/สรุปรายเดือน): นับเฉพาะส่วนที่คาบเกี่ยวช่วง [since, until)
    ขั้นต่ำ 1 วันเหมือนโหมดปกติ (ยืมเช้าคืนบ่ายในช่วงนั้นก็คือของไม่อยู่ในคลัง) — **ผู้เรียกต้องกรองเฉพาะแถวที่
    คาบเกี่ยวช่วงเองด้วย** `overlaps_window()` ไม่งั้นแถวนอกช่วงจะได้ 1 วันจากขั้นต่ำนี้

    ต้อง join BorrowRequest มาก่อนใช้ (ต้องใช้ approved_at เป็นจุดเริ่มนับ)
    """
    end = func.coalesce(BorrowItem.returned_at, func.now())
    if until is not None:
        start = func.greatest(BorrowRequest.approved_at, since)
        return func.greatest(1, func.round(func.extract("epoch", func.least(end, until) - start) / 86400.0))
    if since is None:
        return func.greatest(1, func.round(func.extract("epoch", end - BorrowRequest.approved_at) / 86400.0))
    start = func.greatest(BorrowRequest.approved_at, since)
    return func.greatest(0, func.round(func.extract("epoch", end - start) / 86400.0))


def overlaps_window(since: ColumnElement, until: ColumnElement) -> list[ColumnElement]:
    """เงื่อนไข WHERE: ช่วงที่ของออกจากคลังคาบเกี่ยว [since, until) — ใช้คู่กับ borrowed_days_expr(since, until)"""
    return [BorrowRequest.approved_at < until, func.coalesce(BorrowItem.returned_at, func.now()) > since]


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


async def quality_usage_days_map(db: AsyncSession, equipment_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """วันรวมที่แต่ละหน่วยถูกยืมออกไป **นับตั้งแต่วันประเมินคุณภาพล่าสุดของหน่วยนั้น** (quality_baseline_at)

    ใช้ใน current_quality()/attach_quality_info() เท่านั้น — คนละความหมายกับ usage_days_map() ที่นับ
    ตั้งแต่ approved_at เสมอ (ใช้จ่ายของ/สถิติความคุ้มค่า) ห้ามใช้แทนกัน หน่วยที่ยังไม่เคยประเมิน
    (quality_baseline_at เป็น NULL) ไม่มี key ในผลลัพธ์ — ไม่มีความหมายเพราะยังไม่มีวันตั้งต้นให้นับจาก
    """
    if not equipment_ids:
        return {}
    days_expr = borrowed_days_expr(since=Equipment.quality_baseline_at)
    rows = (await db.execute(
        select(BorrowItem.equipment_id, func.coalesce(func.sum(days_expr), 0))
        .join(BorrowRequest, BorrowItem.borrow_request_id == BorrowRequest.id)
        .join(Equipment, BorrowItem.equipment_id == Equipment.id)
        .where(
            BorrowItem.equipment_id.in_(equipment_ids),
            BorrowItem.item_status != "rejected",
            BorrowRequest.approved_at.is_not(None),
            Equipment.quality_baseline_at.is_not(None),
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


# ── ค่าคุณภาพอุปกรณ์ (เฟส 10, 15 ก.ย. 69) ──────────────────────────────────────
# สูตรมีจุดเดียวที่ current_quality() (ฟังก์ชันบริสุทธิ์ pattern เดียวกับ borrow_service._compute_fine)
# การประเมิน (เขียน quality_baseline) มีจุดเดียวที่ assess_quality() เรียกจาก 4 จังหวะ — ดู CLAUDE.md

def _safe_float(value: str | None, default: float) -> float:
    """แปลงค่า setting เป็น float แบบกันพัง — ค่าที่เสียอยู่ใน DB (เผลอถูกแก้ผ่านทางอื่นที่ไม่ผ่าน
    settings_service.update_setting ซึ่ง validate ไว้แล้ว เช่น SQL ตรง ๆ ตอน migrate/seed ข้อมูล) ต้อง
    fallback เป็นค่าเริ่มต้นแทนโยน 500 ทั้งหน้าที่มีอุปกรณ์เปิดติดตามคุณภาพ (M3 — รีวิวรอบ 2)
    """
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _safe_int(value: str | None, default: int, minimum: int = 1) -> int:
    """เหมือน _safe_float แต่คืน int — ค่าที่มีจุดทศนิยม/พิมพ์ผิด/ต่ำกว่าขั้นต่ำ fallback เป็นค่าเริ่มต้นเช่นกัน
    (ไม่ใช่แค่ TypeError/ValueError — ค่า 0 หรือติดลบที่หลุดผ่านการ validate มาได้ก็ต้องกันไว้ด้วย)
    """
    try:
        n = int(value) if value is not None else default
    except (TypeError, ValueError):
        return default
    return n if n >= minimum else default


async def quality_settings(db: AsyncSession) -> tuple[float, int]:
    """อ่านค่ากลางที่ใช้คิดคุณภาพ (น้ำหนักอายุ 0-100, อายุการใช้งานกลาง) ครั้งเดียวต่อ request

    **public** (ไม่มี underscore นำหน้า) เพราะ `dashboard_service.py` (การ์ดคุณภาพต่ำ) เรียกข้าม module —
    เดิมชื่อ `_quality_settings` (private ตามธรรมเนียม Python) แต่ถูกเรียกข้าม module อยู่แล้วจริง ๆ
    เปลี่ยนชื่อให้ตรงกับการใช้งานจริง แทนที่จะเพิ่ม wrapper อีกชั้น (แก้ตามรีวิวรอบ 3, MINOR-11)
    """
    rows = dict((await db.execute(
        select(Setting.key, Setting.value).where(
            Setting.key.in_(("quality_age_weight", "quality_life_years_default"))
        )
    )).all())
    return (
        _safe_float(rows.get("quality_age_weight"), 50.0),
        _safe_int(rows.get("quality_life_years_default"), 4),
    )


async def quality_low_threshold(db: AsyncSession) -> float:
    """อ่านเกณฑ์คุณภาพต่ำ (setting `quality_low_threshold`, default 10%) — ต่ำกว่านี้ขึ้นป้าย "ควรตรวจสภาพ"
    (ยังยืมได้ปกติ ไม่บล็อก ดู CLAUDE.md) **public** ด้วยเหตุผลเดียวกับ `quality_settings()` ด้านบน —
    `dashboard_service.get_summary()` เรียกข้าม module (การ์ดคุณภาพต่ำ) จึงเปลี่ยนชื่อแทนเพิ่ม wrapper
    """
    row = (await db.execute(select(Setting.value).where(Setting.key == "quality_low_threshold"))).scalar_one_or_none()
    return _safe_float(row, 10.0)


def _quality_components(
    baseline: float | Decimal | None,
    baseline_at: datetime | None,
    life_years: int | None,
    usage_days_since_baseline: float,
    age_weight: float,
    life_years_default: int,
    now: datetime | None = None,
) -> tuple[float, float, float] | None:
    """คำนวณ (age_drop, usage_drop, current) แบบ **ไม่ปัดเศษระหว่างทาง** — จุดเดียวที่มีสูตรคุณภาพจริง
    ทั้ง current_quality() และ _quality_breakdown() ด้านล่างเป็นแค่เปลือกบางที่เรียกฟังก์ชันนี้แล้วค่อยปัด
    เศษตอนคืนค่า (ของเดิมมี 2 ก็อปปี้ที่ต่างกัน: current_quality() ปัดเศษ "ผลรวม" ครั้งเดียว ส่วน
    _quality_breakdown() ปัดเศษ age_drop/usage_drop แยกกันก่อนค่อยลบ ทำให้ current ที่ได้จากสองฟังก์ชัน
    เพี้ยนกันได้ ±0.01 ในเคสขอบพอดี — แก้ตามรีวิวรอบ 2, M4)

    สูตร: คุณภาพ = baseline − 100 × (w_อายุ × วันตั้งแต่ประเมิน/365 + w_ใช้งาน × วันที่ถูกยืมหลังประเมิน/365)
                    ÷ อายุการใช้งาน(ปี)
    เท่ากับหักเป็น "จุด" เท่ากันทุกวันที่ผ่านไปหรือถูกยืม 1 วัน ไม่ว่า baseline จะเป็นเท่าไหร่ (ของบริจาคที่
    เริ่มต้นไม่ใช่ 100% ก็ลดในอัตราเดียวกัน) — baseline=None หรือ baseline_at=None คือ "ยังไม่เคยประเมิน"
    คืน None เสมอ (ห้ามคืน 0 — 0 มีความหมายว่า "ประเมินแล้วว่าเสื่อมสภาพเต็มที่")
    """
    if baseline is None or baseline_at is None:
        return None
    life = max(life_years or life_years_default, 1)
    life_days = life * 365.0
    now = now or datetime.now(timezone.utc)
    bat = baseline_at if baseline_at.tzinfo else baseline_at.replace(tzinfo=timezone.utc)
    age_days = max((now - bat).total_seconds() / 86400.0, 0.0)
    w_age = min(max(age_weight, 0.0), 100.0) / 100.0
    w_usage = 1.0 - w_age
    age_drop = 100.0 * w_age * age_days / life_days
    usage_drop = 100.0 * w_usage * max(usage_days_since_baseline, 0.0) / life_days
    current = min(max(float(baseline) - age_drop - usage_drop, 0.0), 100.0)
    return age_drop, usage_drop, current


def current_quality(
    baseline: float | Decimal | None,
    baseline_at: datetime | None,
    life_years: int | None,
    usage_days_since_baseline: float,
    age_weight: float,
    life_years_default: int,
    now: datetime | None = None,
) -> float | None:
    """ค่าคุณภาพปัจจุบัน (%) — ฟังก์ชันบริสุทธิ์ ไม่แตะ DB คำนวณสดทุกครั้งที่อ่าน ไม่เก็บเป็นคอลัมน์
    (ค่าเดินทุกวันแม้ไม่มีใครยืม) เรียก _quality_components() ที่เดียว (ดู docstring ที่นั่นสำหรับสูตรเต็ม)
    แล้วปัดเศษค่า "current" ก่อนคืน
    """
    comp = _quality_components(
        baseline, baseline_at, life_years, usage_days_since_baseline, age_weight, life_years_default, now,
    )
    if comp is None:
        return None
    _, _, current = comp
    return round(current, 2)


def _quality_breakdown(
    baseline: float | Decimal | None, baseline_at: datetime | None, life_years: int | None,
    usage_days_since_baseline: float, age_weight: float, life_years_default: int,
    now: datetime | None = None,
) -> dict[str, float | None]:
    """เหมือน current_quality() แต่คืนที่มาของตัวเลขแยกส่วน (หักจากอายุ / หักจากการใช้งาน) ให้หน้าเว็บ
    โชว์ "ตั้งต้น X% เมื่อ… · หักจากอายุ Y · หักจากการใช้งาน Z" — ใช้ _quality_components() สูตรเดียวกับ
    current_quality() เป๊ะ (age_drop/usage_drop ปัดเศษแยกเฉพาะตอนแสดงผล ไม่กระทบค่า current)
    """
    comp = _quality_components(
        baseline, baseline_at, life_years, usage_days_since_baseline, age_weight, life_years_default, now,
    )
    if comp is None:
        return {"current": None, "age_drop": None, "usage_drop": None}
    age_drop, usage_drop, current = comp
    return {"current": round(current, 2), "age_drop": round(age_drop, 2), "usage_drop": round(usage_drop, 2)}


def remaining_life_years(
    current: float | None, life_years: int | None, life_years_default: int,
) -> float | None:
    """อายุที่เหลือของเครื่อง (ปี) = คุณภาพปัจจุบัน% × อายุการใช้งาน — **จุดเดียว** ใช้ทั้ง attach_quality_info()
    (โชว์ในหน้าจัดการอุปกรณ์) และ dispatch_order() (จับคู่กับเวลาเรียนที่เหลือของผู้ยืม ดู CLAUDE.md) ผู้เรียก
    ต้องคำนวณ current ผ่าน current_quality()/_quality_breakdown() มาก่อนเสมอ ไม่คำนวณเองซ้ำที่นี่ (เดิมมี
    สูตร `cq/100*life` แยกกันอยู่ 2 ที่ — แก้ตามรีวิวรอบ 2, M4)
    """
    if current is None:
        return None
    life = max(life_years or life_years_default, 1)
    return round(current / 100.0 * life, 2)


async def get_current_quality(db: AsyncSession, eq: Equipment) -> float | None:
    """ค่าคุณภาพปัจจุบันของหน่วยเดียว — เปิด DB อ่าน settings + วันที่ถูกยืมหลังประเมินให้ครบก่อนเรียกฟังก์ชันบริสุทธิ์
    ใช้ตอน assess_quality() (หา "ก่อน" ก่อนตั้งค่าใหม่) — เรียกดูหน่วยเดียวเป็นครั้งคราว ไม่ใช่ path ที่เดินถี่
    (list หลายแถวพร้อมกันใช้ attach_quality_info ที่ query รวมทีเดียวแทน)
    """
    if not eq.quality_tracked or eq.quality_baseline is None or eq.quality_baseline_at is None:
        return None
    age_weight, life_default = await quality_settings(db)
    usage = (await quality_usage_days_map(db, [eq.id])).get(eq.id, 0)
    return current_quality(
        float(eq.quality_baseline), eq.quality_baseline_at, eq.quality_life_years,
        usage, age_weight, life_default,
    )


QUALITY_FIELDS = (
    "quality_tracked", "quality_life_years", "quality_baseline", "quality_baseline_at",
    "current_quality", "quality_age_drop", "quality_usage_drop",
    "quality_needs_inspection", "quality_remaining_life_years",
)

# สวิตช์ระดับรุ่น (propagate/inherit ทั้งรุ่น) — ลำดับตรงกับ tuple ที่ _inherit_quality_from_group() คืน
QUALITY_SWITCH_FIELDS = ("quality_tracked", "quality_life_years")


_QualityResponse = TypeVar("_QualityResponse", bound=BaseModel)


def hide_quality_for_viewer(model: _QualityResponse, viewer: User | None) -> _QualityResponse:
    """ล้างฟิลด์ค่าคุณภาพทั้งหมดออกจาก **response model** (Pydantic) สำหรับผู้เรียกที่ไม่ใช่เจ้าหน้าที่ —
    จุดเดียวที่ตัดสินว่าใครเห็นค่าคุณภาพได้ ทำงานกับ response ที่ build เสร็จแล้วเท่านั้น (model_copy)

    **ห้ามแตะแถว ORM เพื่อซ่อนข้อมูล** (ของเดิมใช้ set_committed_value เขียนทับคอลัมน์จริงเป็น None ใน
    attach_quality_info() — อันตรายเพราะแถว Equipment เดียวกันอาจถูกอ่าน/commit ซ้ำที่อื่นในคำขอเดียวกัน
    เช่น retire_equipment/delete_equipment/generate_qr ที่เคยเรียก get_equipment() โดยไม่ระบุ viewer
    (ได้ None ทันทีเพราะ default) ทำให้ค่า None เสี่ยงถูก commit ทับ DB จริงโดยไม่ตั้งใจ และ setattr(col,
    None) ทับค่าจริงแบบนี้ก็ไม่ถูกนับเป็น "การแก้ไข" โดย audit_service.diff_fields ด้วย — แก้ตามรีวิวรอบ 2)
    """
    if viewer is not None and is_staff(viewer):
        return model
    return model.model_copy(update=dict.fromkeys(QUALITY_FIELDS))


async def attach_quality_info(db: AsyncSession, rows: list[Equipment], viewer: User | None) -> None:
    """เติม current_quality/breakdown ให้ **แถว ORM เป็น transient attribute เท่านั้น** (ไม่ใช่คอลัมน์จริง)
    เพื่อให้ response ที่ build จากแถวนี้อ่านค่าไปแสดงได้ — ไม่ตัดสินใจว่าใครเห็นตรงนี้ (ดู hide_quality_for_viewer
    ที่ทำหน้าที่นั้นกับ response model ตอนปลายทางแทน) คำนวณให้เฉพาะเมื่อ viewer เป็นเจ้าหน้าที่เท่านั้น (ประหยัด
    query — นักศึกษาจะถูกซ่อนที่ response อยู่แล้วไม่ว่าค่าตรงนี้จะเป็นอะไร)

    รุ่นที่ไม่ได้เปิดติดตาม (quality_tracked=False) หรือยังไม่เคยประเมิน (quality_baseline=None) ก็ไม่ต้องขึ้น
    "ควรตรวจสภาพ" — เกณฑ์นั้นมีความหมายเฉพาะหน่วยที่ประเมินแล้วเท่านั้น
    """
    if not rows:
        return
    for r in rows:
        r.current_quality = None
        r.quality_age_drop = None
        r.quality_usage_drop = None
        r.quality_needs_inspection = False
        r.quality_remaining_life_years = None
    if viewer is None or not is_staff(viewer):
        return
    tracked = [r for r in rows if r.quality_tracked and r.quality_baseline is not None and r.quality_baseline_at is not None]
    if not tracked:
        return
    age_weight, life_default = await quality_settings(db)
    threshold = await quality_low_threshold(db)
    usage = await quality_usage_days_map(db, [r.id for r in tracked])
    now = datetime.now(timezone.utc)
    for r in tracked:
        u = usage.get(r.id, 0)
        bd = _quality_breakdown(
            float(r.quality_baseline), r.quality_baseline_at, r.quality_life_years,
            u, age_weight, life_default, now,
        )
        r.current_quality = bd["current"]
        r.quality_age_drop = bd["age_drop"]
        r.quality_usage_drop = bd["usage_drop"]
        r.quality_needs_inspection = bd["current"] is not None and bd["current"] < threshold
        r.quality_remaining_life_years = remaining_life_years(bd["current"], r.quality_life_years, life_default)


async def assess_quality(
    db: AsyncSession, admin: User, equipment_id: uuid.UUID,
    quality_after: float, reason: str | None, event: str,
) -> Equipment:
    """ตั้งค่าคุณภาพใหม่ (quality_baseline + quality_baseline_at = ตอนนี้) — **จุดเดียว** ที่เขียนค่านี้

    เรียกจาก 4 จังหวะ: ปุ่ม "ประเมินคุณภาพ" ในหน้าอุปกรณ์ (บังคับเหตุผล — บังคับที่ router)
    · ติดตั้ง/เปลี่ยนชิ้นส่วน (equipment_part_service.install_part) · สถานะกลับเป็น available
    (update_equipment) · รับคืนแบบชำรุด (borrow_service.return_item) — 3 จังหวะหลังไม่บังคับเหตุผล

    เฉพาะรุ่นที่เปิดติดตาม (quality_tracked) เท่านั้น — เรียกกับรุ่นที่ไม่ได้เปิดไว้ถือเป็นการเรียกผิดที่
    (caller ต้องเช็ค quality_tracked ก่อนเสนอ field ให้กรอกอยู่แล้ว) จึง 400 ไม่ใช่เงียบข้าม
    """
    eq = await get_equipment(db, equipment_id, viewer=admin)
    if not eq.quality_tracked:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="รุ่นนี้ยังไม่เปิดติดตามคุณภาพ")
    before = await get_current_quality(db, eq)
    after = round(min(max(quality_after, 0.0), 100.0), 2)
    eq.quality_baseline = after
    eq.quality_baseline_at = datetime.now(timezone.utc)
    await audit_service.log_action(db, admin, "assess_quality", "equipment", eq.id, {
        "code": eq.code, "name": eq.name, "event": event,
        "before": before, "after": after, "reason": (reason or "").strip() or None,
    })
    await db.commit()
    return await get_equipment(db, eq.id, viewer=admin)


async def dispatch_order(
    db: AsyncSession, units: list[Equipment], borrower: User,
    usage_days: dict[uuid.UUID, int] | None = None,
) -> list[Equipment]:
    """ลำดับ "จะจ่ายหน่วยไหนก่อน" ให้ผู้ยืมคนนี้ — **จุดเดียว** ใช้ทั้ง borrow_service.create_request()
    (จองตอนยื่นคำขอ) และ borrow_service.approve_request() (จัดสรรจริงตอนอนุมัติ) เรียงใน memory
    เท่านั้นหลังล็อกแถวแล้ว (ห้ามเอาไปทำ ORDER BY ของ query ที่มี with_for_update — ดู dispatch_key)

    กฎ (เปลี่ยน 7 ก.ย. 69 — จับคู่อายุที่เหลือของเครื่องกับเวลาเรียนที่เหลือของผู้ยืม):
    รุ่นที่ไม่ได้เปิดติดตามคุณภาพ (มีหน่วยที่ **ยืมได้จริง** ตัวไหนในกลุ่ม untracked แม้แค่หน่วยเดียว) หรือ
    ผู้ยืมไม่ใช่นักศึกษาที่รู้ปีการศึกษา (staff/อาจารย์, หรือ enrollment_year เป็น None) → ใช้กฎเดิมทั้งหมด:
    ถูกใช้น้อยสุดก่อน (dispatch_key)

    รุ่นที่ติดตามคุณภาพครบ + ผู้ยืมเป็นนักศึกษาที่มีปีการศึกษา:
    1. หน่วยที่ประเมินแล้วและ "อายุที่เหลือ" (คุณภาพ% × อายุการใช้งาน) ≥ เวลาเรียนที่เหลือของผู้ยืม
       → เลือกตัวที่เหลือน้อยที่สุดในกลุ่มนี้ก่อน (เก็บของดีที่สุดไว้ให้คนชั้นปีต่ำกว่า)
    2. ไม่มีตัวไหนพอ → ตัวที่อายุเหลือมากที่สุด (ใกล้เคียงที่สุดที่หาได้)
    3. หน่วยที่ยังไม่เคยประเมิน → ต่อท้ายเสมอ เรียงด้วยกฎเดิม (dispatch_key)
    เสมอกัน (อายุเหลือเท่ากัน) → ตัดสินด้วย dispatch_key (ถูกใช้น้อยสุด → ได้มาก่อน → code)

    **เกณฑ์ "เปิดติดตามครบ" ต้องดูเฉพาะหน่วยที่ยืมได้จริง** (`_is_eligible` + ยังมีของว่าง) — เกณฑ์เดียวกับที่
    ผู้เรียกทุกจุด (create_request/get_equipment_group_detail) กรองมาก่อนส่งเข้าที่นี่อยู่แล้ว แต่
    approve_request ส่ง "ทั้งกลุ่ม" ที่ล็อกมา (รวมหน่วยปลดระวาง/ถูกยืมอยู่/ไม่อนุญาตให้ยืมด้วย) ถ้าเอาหน่วย
    พวกนั้นมารวมเช็ค all(tracked) จะได้ผลต่างจาก create_request/recommend ที่กรองมาก่อนแล้ว ทำให้จองไว้ตอน
    ยื่นคำขอกับที่จ่ายจริงตอนอนุมัติกลายเป็นคนละหน่วย (บั๊กที่แก้ตามรีวิวรอบ 2 — ดู CLAUDE.md) — กรองแค่ตอน
    ตัดสินใจว่าจะใช้กฎไหน (gate) เท่านั้น รายการที่คืน/เรียงยังคงเป็น `units` ครบชุดเดิม เพราะ approve_request
    ยังต้องใช้ลำดับเต็มไปเลือกหน่วยที่ยืมได้จริงตัวแรกในนั้นต่ออีกที
    """
    if not units:
        return []
    usage = usage_days if usage_days is not None else await usage_days_map(db, [u.id for u in units])
    fallback_key = lambda u: dispatch_key(u, usage)  # noqa: E731
    eligible_units = [u for u in units if _is_eligible(u) and u.quantity_available > 0]

    if not is_staff(borrower) and getattr(borrower, "enrollment_year", None) is not None \
            and eligible_units and all(u.quality_tracked for u in eligible_units):
        academic_start = await settings_service.get_academic_year_start(db)
        study_years = borrower.study_years or 4
        info = compute_study_year(borrower.enrollment_year, study_years, academic_year_start=academic_start)
        remaining = info.remaining_study_years or 1

        age_weight, life_default = await quality_settings(db)
        q_usage = await quality_usage_days_map(db, [u.id for u in units])

        def remaining_life(u: Equipment) -> float | None:
            cq = current_quality(
                float(u.quality_baseline) if u.quality_baseline is not None else None,
                u.quality_baseline_at, u.quality_life_years, q_usage.get(u.id, 0), age_weight, life_default,
            )
            return remaining_life_years(cq, u.quality_life_years, life_default)

        pairs = [(u, remaining_life(u)) for u in units]
        tail = sorted((u for u, rl in pairs if rl is None), key=fallback_key)
        with_life = [(u, rl) for u, rl in pairs if rl is not None]
        sufficient = sorted((p for p in with_life if p[1] >= remaining), key=lambda p: (p[1], fallback_key(p[0])))
        insufficient = sorted((p for p in with_life if p[1] < remaining), key=lambda p: (-p[1], fallback_key(p[0])))
        return [u for u, _ in sufficient] + [u for u, _ in insufficient] + tail

    return sorted(units, key=fallback_key)


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
    viewer: User | None = None,
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
    await attach_quality_info(db, items, viewer)
    holders_map = await get_holders_map(db)
    responses = []
    for eq in items:
        holders = holders_map.get(eq.id, [])
        resp = EquipmentResponse.model_validate(eq, from_attributes=True).model_copy(
            update={
                "is_currently_borrowed": eq.id in holders_map,
                "holder": holders[0] if holders else None,
                "holders": holders,
            }
        )
        responses.append(hide_quality_for_viewer(resp, viewer))
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
    rows: list[Equipment], holders_map: dict[uuid.UUID, list[HolderInfo]], viewer: User | None = None
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
    resp = EquipmentGroupResponse(**base, unit_count=len(rows), locations=_location_breakdown(rows))
    return hide_quality_for_viewer(resp, viewer)


async def list_equipment_grouped(
    db: AsyncSession,
    page: int,
    page_size: int,
    category_id: uuid.UUID | None,
    item_type: str | None,
    filter_status: str | None,
    search: str | None,
    viewer: User | None = None,
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
    await attach_quality_info(db, rows, viewer)

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

    cards = [_build_group_response(members, holders_map, viewer) for members in groups.values()]
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


async def get_equipment(
    db: AsyncSession, equipment_id: uuid.UUID, viewer: User | None = None
) -> Equipment:
    result = await db.execute(
        select(Equipment).where(Equipment.id == equipment_id).options(selectinload(Equipment.categories))
    )
    eq = result.scalar_one_or_none()
    if not eq:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Equipment not found.")
    await attach_book_values(db, [eq])
    await attach_quality_info(db, [eq], viewer)
    return eq


async def get_equipment_group_detail(
    db: AsyncSession, equipment_id: uuid.UUID, viewer: User | None = None,
    recommend_for: uuid.UUID | None = None,
) -> EquipmentGroupDetailResponse:
    """รายละเอียดอุปกรณ์แบบยุบกลุ่ม + ผู้ครอบครองทั้งกลุ่ม

    equipment_id เป็นหน่วยไหนในกลุ่มก็ได้ (หน้าเว็บส่งมาจากการ์ดที่โชว์ = หน่วยรหัสต่ำสุดอยู่แล้ว)

    recommend_for (เฉพาะเจ้าหน้าที่): user_id ของผู้ยืมที่กำลังจะจ่ายของให้ — คำนวณหน่วยที่ระบบจะเลือกให้
    ด้วยกฎเดียวกับตอนอนุมัติจริง (equipment_service.dispatch_order) ใส่ลง recommended_unit_id ให้
    UnitPickerModal ขึ้นป้าย "แนะนำสำหรับผู้ยืมนี้" — ไม่ทำสูตรแนะนำซ้ำฝั่งหน้าเว็บ
    """
    eq = await get_equipment(db, equipment_id, viewer=viewer)
    members = [eq] if eq.item_type == "consumable" else await find_group_members(db, eq.name, eq.item_type)
    await attach_book_values(db, members)
    await attach_quality_info(db, members, viewer)
    holders_map = await get_holders_map(db, [m.id for m in members])
    usage = await usage_days_map(db, [m.id for m in members])
    group = _build_group_response(members, holders_map, viewer)
    unit_summaries = []
    for m in members:
        m_holders = holders_map.get(m.id, [])
        summary = EquipmentUnitSummary.model_validate(m, from_attributes=True).model_copy(
            update={
                "is_currently_borrowed": m.id in holders_map,
                "holder": m_holders[0] if m_holders else None,
                "days_borrowed": usage.get(m.id, 0),
            }
        )
        unit_summaries.append(hide_quality_for_viewer(summary, viewer))
    # flatten list ของ list — holders_map คืนหลายคนต่อ equipment_id ได้แล้ว (ดู get_holders_map) ต้องรวมทุกคน
    # ของทุกหน่วยในกลุ่มมาเป็น list เดียว ไม่ใช่แค่ list ของหน่วยตัวแทนแบบเดิม (group.model_dump() มี key
    # "holders" ของหน่วยตัวแทนอยู่แล้วจาก _build_group_response ต้อง exclude ก่อนไม่งั้นชนกับ kwarg ด้านล่าง)
    all_holders = [h for hs in holders_map.values() for h in hs]

    recommended_unit_id = None
    if recommend_for and viewer is not None and is_staff(viewer):
        borrower = (await db.execute(select(User).where(User.id == recommend_for))).scalar_one_or_none()
        eligible = [m for m in members if _is_eligible(m) and m.quantity_available > 0]
        if borrower and eligible:
            ordered = await dispatch_order(db, eligible, borrower)
            recommended_unit_id = ordered[0].id if ordered else None

    return EquipmentGroupDetailResponse(
        **group.model_dump(exclude={"holders"}), holders=all_holders, members=unit_summaries,
        recommended_unit_id=recommended_unit_id,
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


def _assert_quality_trackable(item_type: str, quality_tracked: bool | None) -> None:
    """เปิดติดตามคุณภาพได้เฉพาะครุภัณฑ์ (durable) และวัสดุใช้ซ้ำ (material) ตามขอบเขตแผนเดิม — วัสดุสิ้นเปลือง
    (consumable) หลายแถวมีชื่อซ้ำกันได้โดยตั้งใจ (คนละล็อต/คนละก้อน แยกกันจริงตาม `_group_key`) ถ้าเปิดติดตาม
    แล้ว `_propagate_quality_to_group`/`_inherit_quality_from_group` (จับกลุ่มด้วยชื่อ+ประเภทเหมือน
    `find_group_members`) จะไปแตะแถวอื่นที่ไม่เกี่ยวข้องกันจริงโดยไม่ตั้งใจ — เรียกเฉพาะตอนแอดมิน **ตั้งใจ**
    ส่ง `quality_tracked=True` มาตรง ๆ เท่านั้น (400 ชัดเจน) ส่วนกรณีแปลง item_type เป็น consumable ทั้งที่
    เคยติดตามอยู่ก่อนโดยไม่ได้แตะ field นี้ในคำขอเดียวกัน ปิดเงียบ ๆ แทนที่จุดเรียก (ดู CLAUDE.md, แก้ตาม
    รีวิวรอบ 3, MINOR-8)
    """
    if item_type == "consumable" and quality_tracked:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="เปิดติดตามค่าคุณภาพได้เฉพาะครุภัณฑ์และวัสดุใช้ซ้ำเท่านั้น")


async def _inherit_quality_from_group(
    db: AsyncSession, name: str, item_type: str, exclude_id: uuid.UUID | None = None,
) -> tuple[bool, int | None] | None:
    """คืนสถานะติดตามคุณภาพของ "รุ่นปลายทาง" (name+item_type) คำนวณจากหน่วยอื่นในรุ่นเดียวกัน (ไม่รวมตัวเอง)
    — ใช้ตัดสินว่าหน่วยที่เพิ่งสร้าง/เพิ่งเปลี่ยนชื่อ-ประเภทเข้ารุ่นนี้ควรได้สวิตช์อะไร:

    - มีหน่วยอื่นอย่างน้อย 1 หน่วย และ **ทุกหน่วย** เปิดติดตาม (`quality_tracked=True`) → `(True, life_years
      ของหน่วยที่เปิดติดตามหน่วยหนึ่ง)`
    - มีหน่วยอื่นอย่างน้อย 1 หน่วย แต่ **ไม่ใช่ทุกหน่วย** เปิดติดตาม (ปนกัน/ไม่มีใครเปิดเลย) → `(False, None)`
    - ไม่มีหน่วยอื่นเลยในรุ่นนี้ → `None` (ไม่ต้องแตะอะไร — หน่วยเดิมคงค่าตัวเอง / หน่วยที่เพิ่งสร้างใหม่ใช้
      ค่าเริ่มต้น "ยังไม่ติดตาม")

    **จุดเดียว** ที่ตัดสินการ inherit นี้ ใช้ทั้งตอนสร้างหน่วยใหม่ (create_equipment/import_service) และตอน
    หน่วยเดิมเปลี่ยน name/item_type จนย้ายเข้ารุ่นใหม่ (update_equipment/bulk_update_equipment) — exclude_id
    กันไม่ให้หน่วยตัวเองที่เพิ่งถูก setattr ชื่อ/ประเภทใหม่ไปแล้ว (autoflush ของ query ข้างในนี้เห็นค่าที่
    เพิ่ง set ไปแล้ว) ถูกนับเป็น "sibling ของตัวเอง"

    เดิมคืน `(True, ...)` แค่เพราะ "มี sibling สักตัวที่ tracked=True" (ไม่ต้องครบทั้งกลุ่ม) และคืน `None`
    เฉยๆ ตอนกลุ่มปลายทาง "ไม่มีใครติดตามเลย" (ปล่อยให้หน่วยที่ย้ายเข้ามาคงค่าตัวเอง) — ทำให้หน่วยที่เคยติดตาม
    ย้ายเข้ารุ่นที่ปนกัน/ไม่ติดตามเลยกลาย "ค้างติดตาม" อยู่คนเดียวในรุ่นใหม่ (กลุ่มปนกัน — mixed) แล้วรุ่นถัดไป
    ที่ย้ายเข้ามาอีกจะไป inherit True จากหน่วยที่ค้างนั้นซ้ำอีกทอด ลาม tracked ทั้งรุ่นโดยไม่ตั้งใจ กระทบ
    `dispatch_order` (จับคู่คุณภาพ↔ชั้นปี ดู CLAUDE.md) ให้หน่วยที่ประเมินแล้วเพียงตัวเดียวถูกจ่ายซ้ำทุกครั้ง
    (แก้ตามรีวิวรอบ 4, M-a) — ผู้เรียกต้องใช้ผลลัพธ์นี้กับ "หน่วยที่กำลังย้าย/สร้างเท่านั้น" ห้าม propagate
    ต่อไปยัง sibling อื่นในรุ่นปลายทาง (sibling ที่ใช้คำนวณค่านี้ก็มีค่าตรงกันอยู่แล้วโดยนิยาม ไม่มีอะไรต้อง sync)

    consumable ไม่มีวัน inherit ติดตามคุณภาพได้ (MINOR-8) — กันไว้ในนี้อีกชั้นแม้ผู้เรียกควรเช็คก่อนอยู่แล้ว
    เผื่อจุดเรียกในอนาคตลืม guard (เช่น legacy sibling ที่หลุดผ่าน validate มาได้ก่อนแก้รอบนี้)
    """
    if item_type == "consumable":
        return None
    siblings = [m for m in await find_group_members(db, name, item_type) if m.id != exclude_id]
    if not siblings:
        return None
    if all(m.quality_tracked for m in siblings):
        tracked_life = next(m.quality_life_years for m in siblings if m.quality_tracked)
        return True, tracked_life
    return False, None


async def create_equipment(db: AsyncSession, admin: User, body: EquipmentCreate) -> Equipment:
    """รับของใหม่เข้าทะเบียน — ออกรหัสให้เฉพาะวัสดุสิ้นเปลือง และหน่วยใหม่ของรุ่นที่ติดตามคุณภาพอยู่แล้ว
    ได้สวิตช์ตามรุ่นอัตโนมัติ (ไม่ copy baseline — ของจริงคนละสภาพ ต้องประเมินแยก)"""
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
    # ต้อง add(eq) ก่อนเรียก query อื่นใด (find_group_members ด้านล่าง) — ถ้า query ก่อน add จะไป trigger
    # autoflush ตอน eq.categories ถูกตั้งไปแล้วแต่ eq ยังไม่อยู่ในเซสชัน กลายเป็น SAWarning "not in session"
    # (เจอจริงตอนพัฒนา ดู sqlalchemy.orm.attributes back_populates ของ EquipmentCategory.equipment)
    db.add(eq)
    # flush ก่อนเรียก _inherit_quality_from_group เสมอ — eq.id ใช้ default ฝั่ง Python (`uuid.uuid4`, ดู
    # models/equipment.py) ยังเป็น None จนกว่าจะ flush จริง ถ้าไม่ flush ก่อน `exclude_id=eq.id` จะจับค่า
    # None ไปเป็นอาร์กิวเมนต์ แล้ว find_group_members() ด้านในเรียก autoflush เองอยู่ดี (ผ่าน SELECT) ทำให้
    # eq ถูก INSERT เข้า DB "ระหว่างคำนวณ" แต่ exclude_id ที่จับไว้ก่อนหน้ายังเป็น None (ไม่อัปเดตตาม) —
    # eq โผล่มานับเป็น sibling ของตัวเอง (id ไม่ตรงกับ exclude_id=None) ด้วย quality_tracked=False เสมอ
    # (ยังไม่ทันตั้งค่า) ทำให้เช็ค "ทุกหน่วยติดตามครบไหม" เจอ eq เองที่ยังไม่ติดตามปนอยู่ กลายเป็น False ทุกครั้ง
    # แม้ sibling จริงจะติดตามครบก็ตาม (เจอจากเทสจริงตอนแก้ M-a รีวิวรอบ 4 — ของเดิมรอดมาได้เพราะกฎเก่า
    # "เจอ sibling ที่ tracked=True สักตัวก็พอ" ไม่สนใจ eq ปลอมที่ปนเข้ามา)
    await db.flush()
    # หน่วยใหม่ของรุ่นที่เปิดติดตามคุณภาพอยู่แล้ว (เพิ่มเอง/นำเข้า) ต้องได้สวิตช์ตามรุ่นอัตโนมัติ — ไม่งั้น
    # ต้องมากดเปิดเองทีละหน่วยทุกครั้งที่มีของเข้าใหม่ในรุ่นเดียวกัน (ดู CLAUDE.md หัวข้อค่าคุณภาพ)
    inherited = await _inherit_quality_from_group(db, eq.name, eq.item_type, exclude_id=eq.id)
    if inherited:
        eq.quality_tracked, eq.quality_life_years = inherited
    await db.flush()  # เขียนค่าคุณภาพที่ inherit มาให้เป็น pending ก่อนบันทึก audit ต่อ (id มีอยู่แล้วจากข้างบน)
    # เก็บ quantity/item_type ลง detail ด้วย เพื่อให้ใบรับเข้า (ร่างเข้า) ดึงจำนวนมาโชว์ได้
    await audit_service.log_action(db, admin, "create_equipment", "equipment", eq.id,
                                   {"code": eq.code, "name": eq.name,
                                    "quantity": eq.quantity_total, "item_type": eq.item_type,
                                    "unit_value": float(eq.unit_value) if eq.unit_value is not None else None})
    await db.commit()
    return await get_equipment(db, eq.id, viewer=admin)


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


async def _propagate_quality_to_group(
    db: AsyncSession, eq: Equipment, quality_tracked: bool | None, quality_life_years: int | None,
    fields_present: set[str],
) -> list[str]:
    """ตั้งค่า quality_tracked/quality_life_years ให้ทุกหน่วยในรุ่นเดียวกับ `eq` (name+item_type ตรงกัน)
    ยกเว้น `eq` เอง (caller แก้ตัวมันเองแล้ว) — **จุดเดียว** ที่ propagate ค่านี้ ใช้ร่วมกันทั้ง
    update_equipment() (แก้ทีละหน่วย) และ bulk_update_equipment() (แก้หลายหน่วยพร้อมกัน — ยังต้อง sync
    กับหน่วยอื่นในรุ่นเดียวกันที่ไม่ได้ถูกเลือกมาด้วยในคำขอเดียวกัน)

    เขียนเฉพาะหน่วยที่ค่าจริงต่างจากที่จะตั้งเท่านั้น (ฟอร์มส่งค่าเดิมซ้ำทุกครั้งไม่นับว่าแก้ — ไม่งั้น
    audit รกด้วย entry ที่ไม่มีอะไรเปลี่ยนจริง) คืนรหัสของหน่วยที่ถูกแก้จริง ให้ caller ตัดสินใจว่าจะลง
    audit หรือไม่ (ว่าง = ไม่มีอะไรเปลี่ยนในรุ่น ไม่ต้อง log)

    consumable ไม่ propagate เด็ดขาด (MINOR-8) — หลายแถวชื่อซ้ำกันได้โดยตั้งใจ (คนละล็อต แยกกันจริงตาม
    `_group_key`) propagate ตามชื่อจะไปแตะแถวที่ไม่เกี่ยวข้องกันจริง กันไว้ในนี้อีกชั้นแม้ caller ควรเช็ค
    `_assert_quality_trackable`/ล้างค่าก่อนเรียกอยู่แล้ว
    """
    if not fields_present or eq.item_type == "consumable":
        return []
    siblings = [m for m in await find_group_members(db, eq.name, eq.item_type) if m.id != eq.id]
    affected: list[str] = []
    for m in siblings:
        changed_here = False
        if "quality_tracked" in fields_present and m.quality_tracked != quality_tracked:
            m.quality_tracked = quality_tracked
            changed_here = True
        if "quality_life_years" in fields_present and m.quality_life_years != quality_life_years:
            m.quality_life_years = quality_life_years
            changed_here = True
        if changed_here:
            affected.append(m.code)
    return affected


async def update_equipment(db: AsyncSession, admin: User, equipment_id: uuid.UUID, body: EquipmentUpdate) -> Equipment:
    """แก้ไขอุปกรณ์ — แก้ code/item_type ได้แม้เคยมีประวัติการยืม เพราะ BorrowItem เก็บ snapshot

    equipment_name/code/unit/item_type_snapshot เป็นคอลัมน์จริงบน BorrowItem ไม่ใช่ live join
    (ดู borrow_service.py create_request/approve_request) แก้ตรงนี้จึงไม่กระทบใบยืมเก่าเลย
    """
    eq = await get_equipment(db, equipment_id, viewer=admin)
    # exclude_unset (ไม่ใช่ exclude_none) — ต้องแยก "ไม่ได้ส่งฟิลด์นี้มา" ออกจาก "ส่งมาเป็น null ตั้งใจล้างค่า"
    # เช่น SN ที่แอดมินกรอกผิดแล้วอยากลบทิ้ง — exclude_none เดิมจะตัด null ทิ้งเหมือนไม่ได้ส่งมา ลบไม่ได้เลย
    changed = body.model_dump(
        exclude_unset=True,
        exclude={"category_ids", "status_reason", "quality_after", "quality_reason"},
    )
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

    # เปิดติดตามคุณภาพได้เฉพาะ durable/material (MINOR-8) — reject เฉพาะตอนคำขอนี้ "ตั้งใจ" ส่ง
    # quality_tracked=True มาตรง ๆ ทับกับรุ่นที่ (จะ) เป็น consumable เท่านั้น (400 ชัดเจน กันไว้แม้ frontend
    # ซ่อนสวิตช์นี้ไปแล้วสำหรับ consumable) ส่วนกรณีแปลง item_type เป็น consumable เฉย ๆ โดยไม่ได้แตะ field
    # นี้ในคำขอเดียวกัน (ค่า quality_tracked เดิมที่เคยเป็น True ค้างอยู่) ปิดเงียบ ๆ หลัง setattr แทน (ดูด้านล่าง)
    if changed.get("quality_tracked"):
        _assert_quality_trackable(changed.get("item_type", eq.item_type), True)

    # เปลี่ยน name/item_type เข้ารุ่นใหม่ที่เปิดติดตามคุณภาพอยู่แล้ว ต้องได้สวิตช์ตามรุ่นใหม่อัตโนมัติ เหมือน
    # ตอนสร้างหน่วยใหม่ (create_equipment — ใช้ _inherit_quality_from_group() จุดเดียวกัน) ไม่งั้นหน่วยที่ยัง
    # ไม่ประเมิน/ไม่ติดตามถูกเปลี่ยนชื่อเข้ารุ่นเดิมจะไม่ได้ตามอัตโนมัติ ต้องมากดเปิดเองทีละหน่วย ยกเว้นคำขอนี้
    # ระบุ quality_tracked/quality_life_years มาตรง ๆ เอง — ค่านั้นชนะเสมอ (ผู้ใช้ตั้งใจกำหนดเอง ไม่ใช่ inherit
    # อัตโนมัติ) แทรกเข้า `changed` ก่อน snapshot diff ด้านล่าง ให้ทั้ง audit (field_diffs) และการ propagate
    # ต่อ (quality_fields_present ด้านล่าง) ทำงานเหมือนผู้ใช้ส่งมาเองทุกประการ (แก้ตามรีวิวรอบ 3, MAJOR-1b)
    new_name = changed.get("name", eq.name)
    new_item_type = changed.get("item_type", eq.item_type)
    group_changing = ("name" in changed and new_name != eq.name) or \
        ("item_type" in changed and new_item_type != eq.item_type)
    # inherited_fields = ฟิลด์คุณภาพใน `changed` ที่มาจากการ inherit อัตโนมัติ (ไม่ได้ตั้งใจส่งมาเอง) — ต้องกัน
    # ไม่ให้ quality_fields_present ด้านล่างเอาไป propagate ต่อทั้งรุ่นปลายทาง มีผลกับ "หน่วยนี้หน่วยเดียว"
    # เท่านั้น (แก้ตามรีวิวรอบ 4, M-a) · ตัดสินรายฟิลด์: ส่ง quality_life_years มาเองอย่างเดียวยังต้อง inherit
    # quality_tracked ตามรุ่นปลายทาง ไม่งั้นเหลือหน่วยไม่ติดตามค้างในรุ่นที่ติดตามทั้งรุ่น (รีวิวรอบ 4 MINOR ข้อ 2)
    inherited_fields: set[str] = set()
    if group_changing:
        inherited = await _inherit_quality_from_group(db, new_name, new_item_type, exclude_id=eq.id)
        for f, v in zip(QUALITY_SWITCH_FIELDS, inherited or ()):
            if f not in changed:
                changed[f] = v
                inherited_fields.add(f)

    # เก็บ diff ก่อน/หลังไว้ทำ audit (ดู audit_service.diff_fields) — setattr loop ด้านล่างเขียนทับแล้ว
    # ย้อนดูค่าเดิมไม่ได้ ต้องอ่านจาก eq ก่อนแก้เท่านั้น (ค่าที่ inherit มาข้างบนอยู่ใน `changed` แล้วตรงนี้
    # จึงเห็น diff ของมันด้วยเหมือนกัน แม้จะไม่ propagate ต่อทั้งรุ่นก็ตาม — หน่วยนี้เองยังต้องมี audit)
    field_diffs = audit_service.diff_fields(eq, changed)
    old_status, old_total, old_available = eq.status, eq.quantity_total, eq.quantity_available
    old_quality_tracked, old_quality_life_years = eq.quality_tracked, eq.quality_life_years

    for field, value in changed.items():
        setattr(eq, field, value)
    # แปลง item_type เป็น consumable เฉย ๆ (ไม่ได้แตะ quality_tracked ในคำขอนี้) แต่แถวเคยเปิดติดตามค้างมา
    # จากตอนยังเป็น durable/material — ปิดเงียบ ๆ ตรงนี้ (ไม่ error เพราะ admin ไม่ได้ตั้งใจแก้ field นี้เลย
    # ต่างจากเช็ค reject ด้านบนที่ดักเฉพาะตอนตั้งใจส่ง quality_tracked=True ทับ consumable ตรง ๆ) กันรุ่น
    # consumable มี quality_tracked=True ค้างในระบบซึ่ง _propagate_quality_to_group ปฏิเสธไม่ทำงานให้อยู่ดี
    # แต่ปล่อยค้างในแถวนี้เองไว้ก็ยังผิดหลักการ (แก้ตามรีวิวรอบ 3, MINOR-8) — ต้องโผล่ใน audit ด้วยว่า
    # quality_tracked หลุดจาก True เป็น False ไปตอนไหน ไม่งั้น field_diffs (คำนวณไว้ก่อนหน้านี้) เห็นแค่
    # item_type เปลี่ยน แต่ไม่เห็นผลข้างเคียงที่ปิดติดตามไปด้วย (แก้ตามรีวิวรอบ 4, M-e)
    if eq.item_type == "consumable" and eq.quality_tracked:
        field_diffs["quality_tracked"] = [old_quality_tracked, False]
        if old_quality_life_years is not None:
            field_diffs["quality_life_years"] = [old_quality_life_years, None]
        eq.quality_tracked = False
        eq.quality_life_years = None
    # เปิด/ปิดติดตามคุณภาพ หรือแก้อายุการใช้งานที่ใช้คิดคุณภาพ ใช้กับ "ทั้งรุ่น" เสมอ ไม่ใช่แค่หน่วยนี้ —
    # แอดมินกดจากฟอร์มแก้ไขหน่วยเดียว แต่หน่วยอื่นในรุ่นเดียวกัน (ชื่อ+ประเภทตรงกัน) ต้องได้สวิตช์เดียวกันด้วย
    # ใช้ _propagate_quality_to_group() จุดเดียว (ใช้ร่วมกับ bulk_update_equipment) เขียนเฉพาะหน่วยที่ค่า
    # จริงเปลี่ยน ไม่ใช่ทุกครั้งที่ฟอร์มส่ง field นี้มา (ฟอร์มส่งค่าเดิมซ้ำทุกครั้ง — เทียบกับค่า "เดิมจริง"
    # ของหน่วยนี้ ไม่ใช่แค่เช็คว่ามี key อยู่ใน `changed` ไหม เพราะ backend ต้องไม่พึ่ง frontend ว่าจะกรอง
    # ฟิลด์ที่ไม่เปลี่ยนออกก่อนส่งมาหรือเปล่า — แก้ตามรีวิวรอบ 3, MAJOR-1a) — ฟิลด์ที่ inherit มาต้องไม่ propagate
    # เด็ดขาด (M-a ด้านบน) เลยตัดฟิลด์ที่ inherit มาออกไปเลย
    old_quality_values = {"quality_tracked": old_quality_tracked, "quality_life_years": old_quality_life_years}
    quality_fields_present: set[str] = {
        f for f in QUALITY_SWITCH_FIELDS
        if f in changed and f not in inherited_fields and changed[f] != old_quality_values[f]
    }
    affected_codes = await _propagate_quality_to_group(
        db, eq, eq.quality_tracked, eq.quality_life_years, quality_fields_present,
    )
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
    # ซ่อมเสร็จกลับมาพร้อมใช้ — จังหวะที่ 3 ของ 4 จังหวะที่ให้ประเมินคุณภาพใหม่ (ดู CLAUDE.md) ใช้เงื่อนไข
    # "สถานะเปลี่ยนออกจาก available เดิม → available ใหม่" แบบเดียวกับจุดดักคืนสต็อกด้านบน แต่ไม่ผูกกับ
    # quantity_total==1 เพราะการประเมินคุณภาพไม่เกี่ยวกับตัวนับสต็อก
    repaired_to_available = "status" in changed and old_status != "available" and eq.status == "available"
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
    # audit ของ "ผลกับทั้งรุ่น" เป็น entry แยก อิสระจาก field_diffs ของหน่วยนี้เอง — หน่วยนี้เองอาจไม่มีอะไร
    # เปลี่ยนเลย (ส่งค่า quality_tracked เดิมซ้ำมา) แต่ sibling เปลี่ยนจริง ก็ยังต้องมี audit ให้ตามได้ว่า
    # หน่วยไหนบ้างที่โดนผลกระทบ (ของเดิมพลาดจุดนี้ไป sibling ไม่มี audit เลย — แก้ตามรีวิวรอบ 2)
    if affected_codes:
        group_diff: dict[str, list] = {}
        if "quality_tracked" in quality_fields_present:
            group_diff["quality_tracked"] = [old_quality_tracked, eq.quality_tracked]
        if "quality_life_years" in quality_fields_present:
            group_diff["quality_life_years"] = [old_quality_life_years, eq.quality_life_years]
        await audit_service.log_action(db, admin, "update_equipment", "equipment", eq.id, {
            "code": eq.code, "name": eq.name,
            "quality_group_change": group_diff, "affected_codes": affected_codes,
        })
    await db.commit()

    # ประเมินคุณภาพใหม่ (ไม่บังคับ) — เฉพาะตอนสถานะกลับมา available จริง และรุ่นนี้เปิดติดตามอยู่
    # ไม่ส่ง quality_after มา = ไม่แตะค่าคุณภาพเลย (ซ่อมเสร็จแต่ยังไม่อยากประเมินใหม่ตอนนี้ก็ทำได้)
    if repaired_to_available and eq.quality_tracked and body.quality_after is not None:
        await assess_quality(db, admin, eq.id, body.quality_after, body.quality_reason, event="repair_complete")

    return await get_equipment(db, equipment_id, viewer=admin)


async def retire_equipment(
    db: AsyncSession, admin: User, equipment_id: uuid.UUID, reason: str | None = None
) -> None:
    """ปลดระวางอุปกรณ์ + บันทึกเหตุผลลง audit เพื่อออกใบปลดระวาง (ร่างออก) ภายหลัง"""
    eq = await get_equipment(db, equipment_id, viewer=admin)
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
            # หน่วยใหม่ของรุ่นที่เปิดติดตามคุณภาพแล้วต้องได้สวิตช์ตามรุ่นอัตโนมัติ (ดู CLAUDE.md) — ไม่ copy
            # quality_baseline/_at มาด้วย เพราะแต่ละหน่วยเป็นของจริงแยกกันแล้ว ต้องประเมินใหม่รายหน่วยเอง
            quality_tracked=eq.quality_tracked,
            quality_life_years=eq.quality_life_years,
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
        return [await get_equipment(db, eq.id, viewer=admin)]

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
            # ของใหม่ของรุ่นที่เปิดติดตามคุณภาพแล้วได้สวิตช์ตามรุ่นอัตโนมัติ — ยังไม่ copy baseline (ของใหม่จริง
            # ต้องเริ่มจาก "ยังไม่ประเมิน" ไม่ใช่สภาพเดียวกับของเก่าในรุ่น)
            quality_tracked=eq.quality_tracked,
            quality_life_years=eq.quality_life_years,
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
    return await get_equipment(db, eq.id, viewer=admin)


async def delete_equipment(db: AsyncSession, admin: User, equipment_id: uuid.UUID) -> None:
    """ลบอุปกรณ์ออกจาก DB ถาวร — อนุญาตเฉพาะ retired และไม่มีการยืมที่ยังไม่คืน (pending/approved)

    ประวัติที่จบแล้ว (completed/rejected/cancelled) ไม่กันการลบอีกต่อไป — BorrowItem เก็บ
    equipment_name/code/unit เป็น snapshot คอลัมน์จริงแล้ว (ดู borrow_item.py) ไม่ต้องพึ่ง live join
    กับแถว equipment ที่กำลังจะถูกลบ ประวัติจึงไม่พังแม้ FK equipment_id จะถูก SET NULL (ดู migration 0020)

    เช็คด้วย returned==False เฉยๆ ไม่พอ: rejected/cancelled ไม่เคยเซ็ต returned=True เลย (ไม่มี flow
    คืนของสำหรับสถานะเหล่านี้) ต้อง join ไป BorrowRequest.status ด้วย ไม่งั้นของที่เคยอยู่ในคำขอที่ถูกปฏิเสธ/ยกเลิก
    จะติดล็อกลบไม่ได้ตลอดกาลเหมือนบั๊กเดิม
    """
    eq = await get_equipment(db, equipment_id, viewer=admin)
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
    quality_baseline: float | None = None, quality_reason: str | None = None,
) -> BulkUpdateResult:
    """แก้ไขหลายหน่วยพร้อมกัน (เช่น ย้ายสถานที่ทั้ง 12 หน่วยของรุ่นเดียวกัน) — all-or-nothing ต่างจาก
    bulk_delete_equipment เพราะการแก้ location/status ไม่มีเหตุผลที่ควร "แก้ได้บางชิ้น" เซสชันเดียว
    commit ครั้งเดียว, audit เป็น 1 entry รวม (ไม่ log ทีละแถว)

    ข้อยกเว้นเดียว: เปลี่ยนเข้า durable — แถวที่รหัสไม่ครบ 15 หลัก (ดู _validate_durable_code) ถูกข้าม
    แบบ best-effort ใส่ลง failed แทน ไม่ทำให้ทั้ง batch ล้ม (เหมือน bulk_retire/bulk_delete) เพราะของเดิม
    ที่เลือกมาพร้อมกันมักปนรหัสที่ปฏิรูปแล้วกับยังไม่ปฏิรูป

    quality_baseline (+ quality_reason บังคับคู่กัน): ประเมินคุณภาพทั้งชุดพร้อมกันในคลิกเดียว ("ประเมินทั้งรุ่นทีเดียว")
    — เรียก assess_quality() ตัวเดียวกับประเมินทีละชิ้นซ้ำต่อแถว (ได้ audit แยกทีละแถวเหมือน "assess_quality"
    ทีละชิ้นทุกประการ ไม่ใช่ audit รวมแบบฟิลด์อื่นในฟังก์ชันนี้) ข้ามแถวที่ไม่ได้เปิดติดตามอย่างเงียบ ๆ
    (เลือกมาพร้อมกันปนรุ่นที่ยังไม่เปิดติดตามได้ตามปกติ)

    quality_tracked/quality_life_years ใน `update`: propagate ไปทั้งรุ่นของทุกแถวที่เลือก (ไม่ใช่แค่แถวที่
    เลือกมาในคำขอนี้) ผ่าน _propagate_quality_to_group() จุดเดียวกับ update_equipment() — sync หน่วยอื่นใน
    รุ่นเดียวกันที่แอดมินไม่ได้ติ๊กมาด้วย พร้อม audit "ผลกับทั้งรุ่น" แยกต่างหากต่อรุ่น (ดู M1 ใน CLAUDE.md)
    """
    changed = body.model_dump(exclude_none=True, exclude={"category_ids"})
    if not changed and body.category_ids is None and quality_baseline is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ไม่มีอะไรจะแก้ไข")
    if quality_baseline is not None and not (quality_reason or "").strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="กรุณาระบุเหตุผลที่ประเมินคุณภาพ")
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

    rows = [await get_equipment(db, eq_id, viewer=admin) for eq_id in equipment_ids]  # 404 ถ้ามี id ที่ไม่มีจริง

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

    # เปิดติดตามคุณภาพได้เฉพาะ durable/material (MINOR-8) — reject ก่อน mutate แถวไหนเลย ถ้าคำขอนี้ตั้งใจ
    # ส่ง quality_tracked=True มาตรง ๆ ทับแถวที่ (จะ) เป็น consumable แม้แค่แถวเดียวในชุดที่เลือกมาพร้อมกัน
    if changed.get("quality_tracked"):
        target_item_type = changed.get("item_type")
        for eq in rows:
            _assert_quality_trackable(target_item_type or eq.item_type, True)

    # resolve ครั้งเดียวใช้ร่วมกันทุกแถว — ตั้งหมวดหมู่ชุดเดียวกันให้ทุกหน่วยที่เลือก ไม่ต้อง query ซ้ำ
    new_categories = await _resolve_categories(db, body.category_ids) if body.category_ids is not None else None

    if changed or new_categories is not None:
        old_quality = {eq.id: (eq.quality_tracked, eq.quality_life_years) for eq in rows}
        # เปลี่ยน name/item_type พร้อมกันหลายแถว — ถ้าไม่ได้ระบุ quality_tracked/quality_life_years มาตรง ๆ
        # ในคำขอนี้ด้วย แถวที่ย้ายเข้ารุ่นใหม่ (ตามชื่อ/ประเภทที่ตั้งใหม่) ที่เปิดติดตามคุณภาพอยู่แล้วต้องได้
        # สวิตช์ตามรุ่นใหม่อัตโนมัติเหมือนกับ update_equipment() ทีละหน่วย (ใช้ _inherit_quality_from_group()
        # จุดเดียวกัน, รุ่นปลายทางต่อแถวอาจต่างกันถ้า `changed` ไม่ได้ระบุ name/item_type มาครบ — แก้ตามรีวิว
        # รอบ 3, MAJOR-1b) — ไม่ผ่าน _propagate_quality_to_group() ต่อ เพราะ
        # sibling ต้นทางที่ใช้ inherit มาก็มีค่าตรงกันอยู่แล้วโดยนิยาม ไม่มีอะไรต้อง sync เพิ่ม
        # ตัดสินสถานะรุ่นปลายทาง "ครั้งเดียวต่อรุ่น ก่อน setattr แถวไหนเลย" — ถ้าถามทีละแถวหลัง setattr
        # autoflush จะเห็นแถวที่เลือกมาด้วยกันซึ่งเพิ่งย้ายเข้าไปก่อนหน้า ผลเลยขึ้นกับลำดับที่ติ๊ก (รีวิวรอบ 4
        # MINOR ข้อ 1) · ตัดสินรายฟิลด์: ฟิลด์ที่ส่งมาตรง ๆ ชนะ ที่เหลือ inherit (เหมือน update_equipment)
        inherit_fields = [f for f in QUALITY_SWITCH_FIELDS if f not in changed]
        dest_of = {
            eq.id: (changed.get("name", eq.name), changed.get("item_type", eq.item_type)) for eq in rows
        }
        moving = {eq.id for eq in rows if dest_of[eq.id] != (eq.name, eq.item_type)}
        decisions = {
            key: await _inherit_quality_from_group(db, *key)
            for key in {dest_of[i] for i in moving}
        } if inherit_fields else {}
        # M-e (รีวิวรอบ 4): ทั้งสองผลข้างเคียงนี้ไม่เคยโผล่ใน audit "bulk_update_equipment" เลย (audit_set
        # ด้านล่างเก็บแค่ "ตั้งเป็นอะไร" จาก `changed` ที่แอดมินส่งมาตรง ๆ) เก็บเป็น list ต่อแถวที่ถูกกระทบจริง
        # ไว้ต่อท้าย audit_set — ฟิลด์ที่ inherit มา (ไม่ propagate ต่อทั้งรุ่น เหมือน update_equipment, ดู M-a)
        quality_inherited_changes: list[dict] = []
        quality_cleared_changes: list[dict] = []
        for eq in rows:
            for field, value in changed.items():
                setattr(eq, field, value)
            if "image_urls" in changed:
                eq.image_url = changed["image_urls"][0] if changed["image_urls"] else None  # sync cover
            if new_categories is not None:
                eq.categories = list(new_categories)
            # แปลง item_type เป็น consumable เฉย ๆ (ไม่ได้แตะ quality_tracked ในคำขอนี้ — reject ด้านบนดักแค่
            # ตอนตั้งใจส่ง True ตรง ๆ) แต่แถวเคยติดตามค้างมาก่อน ปิดเงียบ ๆ ที่นี่ (กฎเดียวกับ update_equipment
            # แก้ตามรีวิวรอบ 3, MINOR-8)
            if eq.item_type == "consumable" and eq.quality_tracked:
                cleared_life = eq.quality_life_years
                eq.quality_tracked = False
                eq.quality_life_years = None
                quality_cleared_changes.append({
                    "code": eq.code, "quality_tracked": [True, False],
                    "quality_life_years": [cleared_life, None],
                })
            inherited = decisions.get(dest_of[eq.id]) if eq.id in moving else None
            if inherited:
                before = (eq.quality_tracked, eq.quality_life_years)
                for f, v in zip(QUALITY_SWITCH_FIELDS, inherited):
                    if f in inherit_fields:
                        setattr(eq, f, v)
                if (eq.quality_tracked, eq.quality_life_years) != before:
                    quality_inherited_changes.append({
                        "code": eq.code,
                        "quality_tracked": [before[0], eq.quality_tracked],
                        "quality_life_years": [before[1], eq.quality_life_years],
                    })

        # ไม่ใช่ before/after จริง เพราะ 1 การแก้ไขกระทบหลายแถวที่ค่าเดิมต่างกัน — log ฝั่ง "ตั้งเป็นอะไร" พอ
        audit_set = dict(changed)
        if new_categories is not None:
            audit_set["category_ids"] = sorted(c.name for c in new_categories)
        if quality_inherited_changes:
            audit_set["quality_inherited"] = quality_inherited_changes
        if quality_cleared_changes:
            audit_set["quality_auto_untracked"] = quality_cleared_changes
        await audit_service.log_action(
            db, admin, "bulk_update_equipment", "equipment", rows[0].id,
            {"count": len(rows), "set": audit_set, "equipment_ids": [str(e.id) for e in rows],
             **({"reason": status_reason} if status_reason and "status" in changed else {})},
        )

        # เปิด/ปิดติดตามคุณภาพ หรือแก้อายุการใช้งาน ใช้กับ "ทั้งรุ่น" เสมอ (กฎเดียวกับแก้ทีละหน่วย ดู
        # _propagate_quality_to_group ที่เดียว) — แอดมินอาจเลือกมาแค่บางหน่วยของรุ่นในคำขอนี้ หน่วยอื่นใน
        # รุ่นเดียวกันที่ไม่ได้ถูกเลือกมาด้วยต้องได้สวิตช์เดียวกันด้วย ไม่งั้นรุ่นเดียวกันมี quality_tracked
        # ไม่ตรงกันเอง ทำให้ dispatch_order() เห็นเป็นรุ่นที่ "ไม่ได้เปิดติดตามครบ" ทั้งที่แอดมินตั้งใจเปิดทั้ง
        # รุ่นแล้ว (M2) — ประมวลผลแค่ 1 ครั้งต่อรุ่น แม้ rows จะมีหลายหน่วยของรุ่นเดียวกันปนกัน
        quality_fields_present = {f for f in QUALITY_SWITCH_FIELDS if f in changed}
        if quality_fields_present:
            seen_groups: set[tuple[str, str]] = set()
            for eq in rows:
                key = (eq.name, eq.item_type)
                if key in seen_groups:
                    continue
                seen_groups.add(key)
                # แอดมินอาจเลือกมาหลายแถวของรุ่นเดียวกันพร้อมกันโดยค่าก่อนแก้ไม่ตรงกันเอง ("mixed selection")
                # ใช้ค่าก่อนแก้ของ "ตัวแทนตัวแรกที่เจอ" อย่างเดียว (old_quality[eq.id]) ทำให้ [old,new] ที่ log
                # ไม่ตรงกับค่าก่อนแก้จริงของแถวอื่นในรุ่นเดียวกันที่ถูกเลือกมาด้วย — เก็บค่าก่อนแก้ของ "ทุกแถว
                # ที่ถูกเลือกในรุ่นนี้" แทน ถ้าตรงกันหมด log เป็นค่าเดียว ถ้าไม่ตรงกัน log เป็น list ค่าที่พบ
                # ทั้งหมด (แก้ตามรีวิวรอบ 3, MINOR-7)
                group_row_ids = [m.id for m in rows if (m.name, m.item_type) == key]
                old_tracked_vals = {old_quality[i][0] for i in group_row_ids}
                old_life_vals = {old_quality[i][1] for i in group_row_ids}
                old_tracked = next(iter(old_tracked_vals)) if len(old_tracked_vals) == 1 \
                    else sorted(old_tracked_vals, key=str)
                old_life = next(iter(old_life_vals)) if len(old_life_vals) == 1 \
                    else sorted(old_life_vals, key=str)
                affected = await _propagate_quality_to_group(
                    db, eq, eq.quality_tracked, eq.quality_life_years, quality_fields_present,
                )
                if affected:
                    group_diff: dict[str, list] = {}
                    if "quality_tracked" in quality_fields_present:
                        group_diff["quality_tracked"] = [old_tracked, eq.quality_tracked]
                    if "quality_life_years" in quality_fields_present:
                        group_diff["quality_life_years"] = [old_life, eq.quality_life_years]
                    await audit_service.log_action(db, admin, "update_equipment", "equipment", eq.id, {
                        "code": eq.code, "name": eq.name,
                        "quality_group_change": group_diff, "affected_codes": affected,
                    })
    await db.commit()
    ids = [e.id for e in rows]

    # ประเมินคุณภาพทั้งชุด — ต่อจาก commit ฟิลด์อื่นด้านบนแล้ว (เผื่อเพิ่งเปิด quality_tracked ในคำขอเดียวกัน)
    if quality_baseline is not None:
        for eq_id in ids:
            eq = next((e for e in rows if e.id == eq_id), None)
            if eq is not None and eq.quality_tracked:
                await assess_quality(db, admin, eq_id, quality_baseline, quality_reason, event="bulk")

    result = await db.execute(
        select(Equipment).where(Equipment.id.in_(ids)).options(selectinload(Equipment.categories))
    )
    updated = list(result.scalars().all())
    await attach_book_values(db, updated)
    await attach_quality_info(db, updated, admin)
    return BulkUpdateResult(updated=updated, failed=failed)


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


async def generate_qr(
    db: AsyncSession, equipment_id: uuid.UUID, frontend_origin: str | None = None,
    viewer: User | None = None,
) -> bytes:
    """สร้าง QR code ชี้ไปหน้ารายละเอียดอุปกรณ์ — ใช้ frontend_origin ที่ router ตรวจจาก request จริง
    ถ้ามี (เครื่อง dev ที่ IP เปลี่ยนบ่อย) แทน settings.FRONTEND_URL คงที่ กัน QR ชี้ผิดเครื่อง/ผิด IP

    viewer: ผู้เรียกจริง (ใครก็สแกน QR ได้ ไม่จำกัดเฉพาะเจ้าหน้าที่) — ส่งต่อให้ get_equipment() เพื่อความ
    ชัดเจนว่าเป็นการตั้งใจไม่ระบุ staff ไม่ใช่ default None เงียบ ๆ (รูปภาพที่คืนไม่มีค่าคุณภาพอยู่แล้ว
    แต่ต้องระบุให้ชัดตามกฎ "ห้าม default viewer=None ที่จุดใช้งานจริง" — ดู CLAUDE.md)
    """
    eq = await get_equipment(db, equipment_id, viewer=viewer)
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
