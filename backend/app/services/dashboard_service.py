from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.config import TZ
from app.models.borrow_item import BorrowItem
from app.models.borrow_request import BorrowRequest
from app.models.equipment import Equipment
from app.models.setting import Setting
from app.models.user import User
from app.services import equipment_service
from app.schemas.dashboard import (
    DashboardSummaryResponse,
    EquipmentCounts,
    MajorUserCount,
    FineRow,
    FineSummaryResponse,
    UtilizationResponse,
    UtilizationRow,
)
from app.utils.duedate import effective_due_date
from app.utils.identity import user_identifier

ITEM_TYPES = ("durable", "material", "consumable")


async def _get_setting_int(db: AsyncSession, key: str) -> int:
    """อ่านค่า int จาก settings — ไฟล์นี้เก็บ helper แยกของตัวเอง ไม่ import จาก borrow_service"""
    result = await db.execute(select(Setting).where(Setting.key == key))
    return int(result.scalar_one().value)


async def get_summary(db: AsyncSession) -> DashboardSummaryResponse:
    """สรุปภาพรวมสำหรับ dashboard admin"""
    pending_result = await db.execute(
        select(func.count(BorrowRequest.id)).where(BorrowRequest.status == "pending")
    )
    overdue_result = await db.execute(
        select(func.count(BorrowRequest.id)).where(
            BorrowRequest.is_overdue == True, BorrowRequest.status == "approved"
        )
    )

    # สต็อกต่ำ: ใช้เกณฑ์เฉพาะชิ้นถ้าตั้งไว้ ไม่งั้น fallback เป็นเกณฑ์กลาง — ครอบทุกชิ้น consumable
    # ไม่มีใครหลุดเหมือนเดิมที่นับเฉพาะชิ้นที่ตั้ง threshold รายชิ้นเอาไว้เท่านั้น
    default_threshold = await _get_setting_int(db, "low_stock_threshold_default")
    low_stock_result = await db.execute(
        select(func.count(Equipment.id)).where(
            Equipment.item_type == "consumable",
            Equipment.quantity_available <= func.coalesce(Equipment.low_stock_threshold, default_threshold),
        )
    )

    # คำขอที่อยู่ระหว่างการยืม (approved ยังไม่คืนครบ)
    active_borrows_result = await db.execute(
        select(func.count(BorrowRequest.id)).where(BorrowRequest.status == "approved")
    )

    # จำนวนอุปกรณ์ที่ถูกยืมออกไปจริง (approved + ยังไม่คืน) — ต้องนับจาก borrow_item เท่านั้น
    # ห้ามใช้ quantity_total - quantity_available เพราะรวมของที่ชำรุด/ซ่อมอยู่/แอดมินปิดใช้งานเองด้วย
    # ซึ่งไม่ใช่ "ถูกยืมอยู่" (พบจาก QA จริง: ค่าขึ้น 55 ทั้งที่ active_borrows request = 0)
    borrowed_out_result = await db.execute(
        select(func.coalesce(func.sum(BorrowItem.quantity), 0))
        .join(BorrowRequest, BorrowItem.borrow_request_id == BorrowRequest.id)
        .where(BorrowRequest.status == "approved", BorrowItem.returned.is_(False))
    )

    # สรุปจำนวนอุปกรณ์ตามประเภท — ix_equipment_item_type มีอยู่แล้ว query นี้ถูกมาก
    counts_result = await db.execute(
        select(Equipment.item_type, func.count(Equipment.id)).group_by(Equipment.item_type)
    )
    counts_by_type = {t: n for t, n in counts_result.all()}
    equipment_counts = EquipmentCounts(
        durable=counts_by_type.get("durable", 0),
        material=counts_by_type.get("material", 0),
        consumable=counts_by_type.get("consumable", 0),
        total=sum(counts_by_type.values()),
    )

    # ของที่ข้อมูลทะเบียนยังไม่ครบ — ไม่นับของที่ปลดระวางแล้ว (ไม่ต้องไล่เติมย้อนหลัง)
    missing_price_result = await db.execute(
        select(func.count(Equipment.id)).where(
            Equipment.unit_value.is_(None), Equipment.status != "retired")
    )
    missing_date_result = await db.execute(
        select(func.count(Equipment.id)).where(
            Equipment.acquired_at.is_(None), Equipment.status != "retired")
    )

    # ต้นทุนวัสดุที่ถูกใช้ไปในเดือนนี้/ปีนี้ = ผลรวม (จำนวน × ราคาต่อหน่วย ณ วันอนุมัติ)
    # นับเฉพาะ used_up/discarded — ของที่คืนครบ (returned_full) กลับเข้าคลังแล้ว ไม่ใช่ต้นทุน
    now = datetime.now(TZ)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    year_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    consumed_month_result = await db.execute(
        select(func.coalesce(func.sum(BorrowItem.quantity * BorrowItem.unit_value_snapshot), 0)).where(
            BorrowItem.condition_on_return.in_(("used_up", "discarded")),
            BorrowItem.returned_at >= month_start,
        )
    )
    consumed_year_result = await db.execute(
        select(func.coalesce(func.sum(BorrowItem.quantity * BorrowItem.unit_value_snapshot), 0)).where(
            BorrowItem.condition_on_return.in_(("used_up", "discarded")),
            BorrowItem.returned_at >= year_start,
        )
    )

    # ภาพรวมผู้ใช้ — นับเฉพาะบัญชีที่เปิดใช้งานอยู่ (ปิดไปแล้วไม่ใช่ "ผู้ใช้ของระบบ" อีกต่อไป)
    users_rows = (await db.execute(
        select(User.role, User.major, func.count(User.id))
        .where(User.is_active == True)  # noqa: E712
        .group_by(User.role, User.major)
    )).all()
    users_total = sum(n for _, _, n in users_rows)
    users_students = sum(n for role, _, n in users_rows if role == "student")
    by_major: dict[str | None, int] = {}
    for role, major, n in users_rows:
        if role == "student":  # สาขามีความหมายกับนักศึกษาเท่านั้น เจ้าหน้าที่ไม่ได้สังกัดสาขา
            by_major[major] = by_major.get(major, 0) + n
    pending_users = (await db.execute(
        select(func.count(User.id)).where(User.approval_status == "pending"))).scalar() or 0

    return DashboardSummaryResponse(
        users_total=users_total,
        users_students=users_students,
        users_staff=users_total - users_students,
        users_pending_approval=pending_users,
        users_by_major=[MajorUserCount(major=m, count=c)
                        for m, c in sorted(by_major.items(), key=lambda kv: -kv[1])],
        pending_requests=pending_result.scalar() or 0,
        overdue_requests=overdue_result.scalar() or 0,
        low_stock_items=low_stock_result.scalar() or 0,
        active_borrows=active_borrows_result.scalar() or 0,
        equipment_borrowed_out=borrowed_out_result.scalar() or 0,
        equipment_counts=equipment_counts,
        consumed_value_this_month=float(consumed_month_result.scalar() or 0),
        consumed_value_this_year=float(consumed_year_result.scalar() or 0),
        missing_price_items=missing_price_result.scalar() or 0,
        missing_acquired_at_items=missing_date_result.scalar() or 0,
    )


# เกณฑ์ป้าย "คุ้มค่า / ปานกลาง / ไม่ถูกใช้" — สัดส่วนวันที่ถูกยืมต่อวันที่ครอบครอง
# ตัวเลขนี้เป็นเกณฑ์เพื่อการตัดสินใจจัดซื้อล้วน ๆ ไม่ได้ผูกกับกฎธุรกิจอื่น จึงไม่ต้องเป็น setting
UTILIZATION_GOOD = 0.30
UTILIZATION_FAIR = 0.05


def _rate_label(rate: float | None, borrow_count: int) -> str:
    """แปลงอัตราการใช้งานเป็นป้าย — ของที่ยังไม่กรอก acquired_at คิดอัตราไม่ได้ ตัดสินจาก "เคยถูกยืมไหม" แทน"""
    if borrow_count == 0:
        return "idle"
    if rate is None:
        return "fair"
    if rate >= UTILIZATION_GOOD:
        return "good"
    return "fair" if rate >= UTILIZATION_FAIR else "idle"


async def get_utilization(db: AsyncSession, item_type: str | None = None) -> UtilizationResponse:
    """สถิติความคุ้มค่ารายหน่วย — ถูกยืมกี่ครั้ง กี่วัน คิดเป็นต้นทุนต่อวันเท่าไหร่ ชิ้นไหนไม่เคยถูกยืมเลย

    ใช้ตอบคำถามจัดซื้อ ("ซื้อมา 30,000 มีใครยืมบ้างไหม") จึงนับเฉพาะ durable/material ที่ได้ของกลับคืน
    consumable ใช้แล้วหมดไป ตัวเลข "วันที่ถูกยืม" ไม่มีความหมาย (ดูต้นทุนวัสดุที่ get_summary แทน)

    **ไม่ใช่ฐานคิดค่าปรับ** — ค่าปรับ/ค่าเสียหายใช้มูลค่าตามบัญชี (book_value_snapshot) คนละตัวกัน
    """
    # ใช้นิยาม "วันที่ออกจากคลัง" ตัวเดียวกับที่กฎจ่ายของ (dispatch_key) ใช้ — สองที่นี้ต้องตรงกันเสมอ
    # ไม่งั้นหน้าสถิติบอกว่าชิ้นนี้ถูกใช้น้อยสุด แต่ระบบดันจ่ายอีกชิ้นให้
    days_out = equipment_service.borrowed_days_expr()
    # นับเฉพาะชิ้นที่ของออกจากคลังจริง — ชิ้นที่ถูกปฏิเสธไม่เคยได้ของไป และคำขอที่ยังไม่อนุมัติยังไม่มี approved_at
    usage_rows = (await db.execute(
        select(
            BorrowItem.equipment_id,
            func.count(BorrowItem.id),
            func.coalesce(func.sum(days_out), 0),
        )
        .join(BorrowRequest, BorrowItem.borrow_request_id == BorrowRequest.id)
        .where(
            BorrowItem.equipment_id.is_not(None),
            BorrowItem.item_status != "rejected",
            BorrowRequest.approved_at.is_not(None),
        )
        .group_by(BorrowItem.equipment_id)
    )).all()
    usage = {eq_id: (int(cnt), int(days)) for eq_id, cnt, days in usage_rows}

    types = (item_type,) if item_type else ("durable", "material")
    equipment = (await db.execute(
        select(Equipment).where(Equipment.item_type.in_(types)).order_by(Equipment.code)
    )).scalars().all()

    today = datetime.now(TZ).date()
    rows: list[UtilizationRow] = []
    for eq in equipment:
        count, days = usage.get(eq.id, (0, 0))
        owned_days = (today - eq.acquired_at).days if eq.acquired_at else None
        # ของที่เพิ่งได้มาวันนี้ owned_days = 0 → หารไม่ได้ ปล่อยเป็น None (ยังไม่มีข้อมูลพอจะตัดสิน)
        rate = min(days / owned_days, 1.0) if owned_days else None
        value = float(eq.unit_value) if eq.unit_value is not None else None
        rows.append(UtilizationRow(
            equipment_id=eq.id, code=eq.code, name=eq.name, item_type=eq.item_type, status=eq.status,
            unit_value=value, acquired_at=eq.acquired_at,
            borrow_count=count, days_borrowed=days, owned_days=owned_days,
            utilization_rate=rate,
            cost_per_day=round(value / days, 2) if value is not None and days else None,
            rating=_rate_label(rate, count),
        ))

    never = [r for r in rows if r.borrow_count == 0]
    return UtilizationResponse(
        rows=rows,
        never_borrowed_count=len(never),
        never_borrowed_value=sum(r.unit_value or 0 for r in never),
        total_days_borrowed=sum(r.days_borrowed for r in rows),
    )


async def get_fines(db: AsyncSession) -> FineSummaryResponse:
    """ค่าปรับทุกรายการที่เคยถูกบันทึก + ยอดรวมแยกตามสถานะ (ค้างชำระ/ชำระแล้ว/ยกเว้น)

    คืนทั้งชุดโดยไม่แบ่งหน้า — ระบบมีผู้ใช้ ~300 คน อุปกรณ์ ≤100 ชิ้น จำนวนแถวที่มีค่าปรับจึงน้อยมาก
    หน้าเว็บกรอง/เรียงเองฝั่ง client แบบเดียวกับหน้าสถิติความคุ้มค่า

    ยอดที่เห็นคือค่าที่ freeze ไว้ตอนรับคืน ไม่คำนวณใหม่ตอนอ่าน — แก้อัตราใน settings แล้วยอดเก่าต้องไม่ขยับ
    """
    waiver = aliased(User)
    result = await db.execute(
        select(BorrowItem, BorrowRequest, User, waiver)
        .join(BorrowRequest, BorrowItem.borrow_request_id == BorrowRequest.id)
        .join(User, BorrowRequest.student_id == User.id)
        .outerjoin(waiver, BorrowItem.fine_waived_by == waiver.id)
        .where(BorrowItem.fine_status != "none")
        .order_by(BorrowItem.returned_at.desc().nullslast())
    )

    rows: list[FineRow] = []
    totals = {"unpaid": 0.0, "paid": 0.0, "waived": 0.0}
    counts = {"unpaid": 0, "paid": 0, "waived": 0}
    for item, req, student, waived_by in result.all():
        total = item.fine_total
        if item.fine_status in totals:
            totals[item.fine_status] += total
            counts[item.fine_status] += 1
        rows.append(FineRow(
            item_id=item.id, request_id=req.id, request_code=req.request_code,
            student_name=student.full_name, student_identifier=user_identifier(student),
            equipment_name=item.equipment_name, equipment_code=item.equipment_code,
            condition_on_return=item.condition_on_return,
            due_date=effective_due_date(item, req), returned_at=item.returned_at,
            days_late=item.fine_days_late or 0,
            late_amount=float(item.fine_late_amount or 0),
            damage_amount=float(item.fine_damage_amount or 0),
            total=total, status=item.fine_status,
            waived_by_name=waived_by.full_name if waived_by else None,
            waived_reason=item.fine_waived_reason, basis=item.fine_basis,
        ))

    return FineSummaryResponse(
        rows=rows,
        unpaid_total=round(totals["unpaid"], 2),
        paid_total=round(totals["paid"], 2),
        waived_total=round(totals["waived"], 2),
        unpaid_count=counts["unpaid"], paid_count=counts["paid"], waived_count=counts["waived"],
    )
