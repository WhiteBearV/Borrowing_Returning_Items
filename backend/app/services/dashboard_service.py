from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.config import TZ
from app.models.borrow_item import BorrowItem
from app.models.borrow_request import BorrowRequest
from app.models.equipment import Equipment
from app.models.setting import Setting
from app.models.user import User
from app.services import equipment_service, settings_service
from app.schemas.dashboard import (
    DashboardSummaryResponse,
    EquipmentCounts,
    MajorUserCount,
    FineRow,
    FineSummaryResponse,
    UtilizationMonth,
    UtilizationResponse,
    UtilizationRow,
    YearLevelCount,
)
from app.utils.duedate import effective_due_date
from app.utils.identity import user_identifier
from app.utils.study_year import YEAR_GROUP_ORDER, year_group_key

# ป้ายของการ์ดชั้นปี (เฟส 10) — group เป็น key แบบเครื่องอ่าน ("1".."4"/"retained"/"staff"/"unknown", ลำดับ
# คงที่ตาม YEAR_GROUP_ORDER ที่มาจาก app.utils.study_year จุดเดียวกับ users_service.list_users — แก้ตาม
# รีวิวรอบ 4, M-b) ให้ฝั่งหน้าเว็บ (DashboardPage → link ไป /admin/users?year_group=) ใช้กรองต่อได้ตรง ๆ
# โดยไม่ต้องแกะป้ายภาษาไทยเอง (เดิม DashboardPage.jsx parse ป้ายไทยด้วย regex ซึ่งพังง่าย — แก้ตามรีวิวรอบ 2)
YEAR_GROUP_LABEL = {
    "1": "ปีที่ 1", "2": "ปีที่ 2", "3": "ปีที่ 3", "4": "ปีที่ 4",
    "retained": "ตกค้าง", "staff": "บุคลากร",
    # นักศึกษาที่ enrollment_year เป็น None (รหัสไม่ตรงรูปแบบ/ข้อมูลเก่า) — คนละกลุ่มกับ "บุคลากร" จริง
    # (admin/superadmin) ต้องไม่ถูกนับปนกัน ไม่งั้นจำนวนนักศึกษาที่ enrollment_year หายไปจะไปบวกทับ/ถูกทับ
    # ด้วยจำนวนเจ้าหน้าที่จริง (บั๊กที่พบตอนรีวิวรอบ 2 — ดู MINOR 2)
    "unknown": "ไม่ทราบชั้นปี",
}

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

    # มูลค่าอุปกรณ์ที่ถูกยืมออก (ทุกประเภท) เดือนนี้/ปีนี้ = ผลรวม (จำนวน × ราคาต่อหน่วย ณ วันอนุมัติ)
    # นับตามวันที่อนุมัติ = วันที่ของออกจากคลังจริง · ข้ามชิ้นที่ไม่อนุมัติ (ไม่เคยได้ของไป)
    # เป็น "มูลค่าของที่ออกไปใช้งาน" ไม่ใช่ต้นทุนที่เสียไป (ครุภัณฑ์/วัสดุใช้ซ้ำได้คืน) — ผู้ใช้เลือก 21 ก.ย. 69
    # แทนสูตรเดิมที่นับแค่วัสดุสิ้นเปลืองที่สรุปผลว่าใช้หมด/ทิ้งแล้ว (ของที่ยืมออกไปยังไม่สรุปผลไม่เคยถูกนับ)
    now = datetime.now(TZ)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    year_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)

    async def _borrowed_value_since(since: datetime) -> float:
        return float((await db.execute(
            select(func.coalesce(func.sum(BorrowItem.quantity * BorrowItem.unit_value_snapshot), 0))
            .join(BorrowRequest, BorrowItem.borrow_request_id == BorrowRequest.id)
            .where(BorrowRequest.approved_at >= since, BorrowItem.item_status != "rejected")
        )).scalar() or 0)

    # คิดตรงนี้ทันที — ด้านล่างมีตัวแปร year_start อีกตัว (วันเริ่มปีการศึกษา "06-01") ถ้าเลื่อนไป await ตอน return
    # จะได้ค่านั้นไปเทียบกับ approved_at แทน (เจอจริงตอนเขียนเทส)
    borrowed_month = await _borrowed_value_since(month_start)
    borrowed_year = await _borrowed_value_since(year_start)

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

    # ชั้นปี (เฟส 10) — คำนวณสดจาก enrollment_year (ไม่ใช่คอลัมน์ตรง) รวมกลุ่ม "ตกค้าง" เป็นก้อนเดียว
    # (ไม่แยกรายปีที่ตกค้าง เช่น "ตกค้าง (ปีที่ 5)"/"ตกค้าง (ปีที่ 6)" คนละใบ — ผู้ใช้ต้องการเห็นภาพรวมเดียว)
    # เฉพาะบัญชีที่เปิดใช้งานอยู่ (สอดคล้องกับ users_total ด้านบน) สเกล ≤300 คน (CLAUDE.md) วนในหน่วยความจำได้
    year_start = await settings_service.get_academic_year_start(db)
    student_years_rows = (await db.execute(
        select(User.enrollment_year, User.study_years)
        .where(User.is_active == True, User.role == "student")  # noqa: E712
    )).all()
    year_group_counts: dict[str, int] = {}
    for enrollment_year, study_years in student_years_rows:
        # ทุก query ข้างบนกรอง role == "student" ไว้แล้ว — is_student=True ตรงนี้เสมอ (staff นับแยกด้านล่าง
        # จาก users_total - users_students) ใช้ year_group_key() จุดเดียวกับ users_service.list_users.matches()
        # (แก้ตามรีวิวรอบ 4, M-b — เดิมคำนวณ/พับกลุ่ม "นอกช่วง 1-4" ซ้ำเองตรงนี้ ไม่ตรงกับที่ users_service
        # ใช้กรอง ทำให้ user บางคนที่การ์ดนับว่าอยู่กลุ่ม retained กลับหาไม่เจอเลยผ่านตัวกรอง year_group)
        group = year_group_key(True, enrollment_year, study_years, academic_year_start=year_start)
        # บวกสะสมด้วย group key เสมอ (ไม่ใช่ set ทับ) — ของเดิมใช้ label เป็น key แล้วเขียนทับ "บุคลากร" ด้วย
        # staff_count ทีหลัง ทำให้จำนวนนักศึกษาที่ enrollment_year=None หายไปเงียบ ๆ (บั๊กที่พบตอนรีวิวรอบ 2)
        year_group_counts[group] = year_group_counts.get(group, 0) + 1
    staff_count = users_total - users_students
    if staff_count:
        year_group_counts["staff"] = year_group_counts.get("staff", 0) + staff_count
    users_by_year = [
        YearLevelCount(group=g, label=YEAR_GROUP_LABEL.get(g, g), count=year_group_counts[g])
        for g in YEAR_GROUP_ORDER if g in year_group_counts
    ]

    # การ์ดคุณภาพ (เฟส 10) — เฉพาะรุ่นที่เปิดติดตาม quality_tracked และยังไม่ปลดระวาง (ของที่ปลดระวางแล้ว
    # ไม่มีใครต้องไปตรวจสภาพหรือประเมินต่ออีก ขึ้นเตือนไว้จะหลอกให้เจ้าหน้าที่เสียเวลาไปดูของที่เลิกใช้แล้ว)
    tracked_rows = (await db.execute(
        select(Equipment).where(Equipment.quality_tracked == True, Equipment.status != "retired")  # noqa: E712
    )).scalars().all()
    threshold = await equipment_service.quality_low_threshold(db)
    unassessed = [e for e in tracked_rows if e.quality_baseline is None]
    assessed = [e for e in tracked_rows if e.quality_baseline is not None]
    quality_low_count = 0
    if assessed:
        age_weight, life_default = await equipment_service.quality_settings(db)
        usage = await equipment_service.quality_usage_days_map(db, [e.id for e in assessed])
        for e in assessed:
            cq = equipment_service.current_quality(
                float(e.quality_baseline), e.quality_baseline_at, e.quality_life_years,
                usage.get(e.id, 0), age_weight, life_default,
            )
            if cq is not None and cq < threshold:
                quality_low_count += 1

    return DashboardSummaryResponse(
        users_total=users_total,
        users_students=users_students,
        users_staff=users_total - users_students,
        users_pending_approval=pending_users,
        users_by_major=[MajorUserCount(major=m, count=c)
                        for m, c in sorted(by_major.items(), key=lambda kv: -kv[1])],
        users_by_year=users_by_year,
        quality_low_count=quality_low_count,
        quality_unassessed_count=len(unassessed),
        pending_requests=pending_result.scalar() or 0,
        overdue_requests=overdue_result.scalar() or 0,
        low_stock_items=low_stock_result.scalar() or 0,
        active_borrows=active_borrows_result.scalar() or 0,
        equipment_borrowed_out=borrowed_out_result.scalar() or 0,
        equipment_counts=equipment_counts,
        borrowed_value_this_month=borrowed_month,
        borrowed_value_this_year=borrowed_year,
        missing_price_items=missing_price_result.scalar() or 0,
        missing_acquired_at_items=missing_date_result.scalar() or 0,
    )


# เกณฑ์ป้าย "คุ้มค่า / ปานกลาง / ไม่ถูกใช้" — สัดส่วนวันที่ถูกยืมต่อช่วงที่วัดผล (tracked_days)
# ตัวเลขนี้เป็นเกณฑ์เพื่อการตัดสินใจจัดซื้อล้วน ๆ ไม่ได้ผูกกับกฎธุรกิจอื่น จึงไม่ต้องเป็น setting
UTILIZATION_GOOD = 0.30
UTILIZATION_FAIR = 0.05


def _rate_label(rate: float | None, days_borrowed: int) -> str:
    """good = คุ้มค่า · fair = ปานกลาง · low = เคยถูกยืมแต่ใช้น้อย · idle = ไม่เคยถูกยืมเลย

    low แยกจาก idle (21 ก.ย. 69) — เดิมของที่ถูกยืมจริงแต่อัตราต่ำกว่าเกณฑ์ขึ้นป้าย "ไม่ถูกใช้" ปนกับของที่
    ไม่เคยมีใครแตะ ทำให้อ่านผิดว่าประวัติการยืมหาย · rate=None (กันไว้เผื่อ caller อื่น) ถือเป็นปานกลาง
    """
    # ตัดสินจากวันที่ถูกยืม ไม่ใช่จำนวนครั้ง — แบบเลือกช่วง ของที่ยืมมาก่อนช่วงแต่ยังไม่คืนคือถูกใช้อยู่
    # แม้ "ยืมใหม่" ในช่วงนั้นจะเป็น 0 ครั้ง (แบบสะสม วัน = 0 ก็ต่อเมื่อไม่เคยยืมเลยอยู่แล้ว)
    if days_borrowed == 0:
        return "idle"
    if rate is None:
        return "fair"
    if rate >= UTILIZATION_GOOD:
        return "good"
    return "fair" if rate >= UTILIZATION_FAIR else "low"


UTILIZATION_TYPES = ("durable", "material")          # ค่าเริ่มต้น: ของที่ได้คืน (ดู docstring get_utilization)
ALL_ITEM_TYPES = ("durable", "material", "consumable")
MAX_MONTHS = 36   # ponytail: สรุปรายเดือนยิง query ละเดือน เกินนี้ตัดเหลือ 36 เดือนล่าสุด — ถ้าช้าค่อยรวบเป็น query เดียว


async def get_utilization(
    db: AsyncSession, item_type: str | None = None, date_from: date | None = None, date_to: date | None = None,
) -> UtilizationResponse:
    """สถิติความคุ้มค่ารายหน่วย — ถูกยืมกี่ครั้ง กี่วัน คิดเป็นต้นทุนต่อวันเท่าไหร่ ชิ้นไหนไม่ถูกยืมเลย

    ใช้ตอบคำถามจัดซื้อ ("ซื้อมา 30,000 มีใครยืมบ้างไหม") ค่าเริ่มต้นจึงนับเฉพาะ durable/material ที่ได้ของ
    กลับคืน (item_type="all" = รวม consumable ด้วย — ใช้ตอนกดมาจากการ์ด "มูลค่าที่ถูกยืมออก" ใน Dashboard
    ให้ตัวเลขรายเดือนตรงกับการ์ด)

    date_from/date_to (รวมทั้งสองวัน มาคู่กันเสมอ): นับเฉพาะในช่วงนั้น — วันที่ถูกยืม/วันที่อยู่ในระบบ/ค่าเสื่อม
    ถูกตัดให้อยู่ในช่วง, borrow_count = ยืมใหม่ในช่วง, ของที่ยังไม่เข้าระบบในช่วงนั้นไม่แสดง
    ไม่ส่ง = สะสมตั้งแต่เข้าระบบถึงวันนี้

    **ไม่ใช่ฐานคิดค่าปรับ** — ค่าปรับ/ค่าเสียหายใช้มูลค่าตามบัญชี (book_value_snapshot) คนละตัวกัน
    """
    now = datetime.now(TZ)
    today = now.date()
    period = date_from is not None and date_to is not None
    # ใช้นิยาม "วันที่ออกจากคลัง" ตัวเดียวกับที่กฎจ่ายของ (dispatch_key) ใช้ — ห้ามเขียนสูตรนับวันซ้ำที่อื่น
    # นับเฉพาะชิ้นที่ของออกจากคลังจริง — ชิ้นที่ถูกปฏิเสธไม่เคยได้ของไป และคำขอที่ยังไม่อนุมัติยังไม่มี approved_at
    conds = [BorrowItem.equipment_id.is_not(None), BorrowItem.item_status != "rejected",
             BorrowRequest.approved_at.is_not(None)]
    if period:
        since = datetime.combine(date_from, time.min, TZ)
        until = min(datetime.combine(date_to + timedelta(days=1), time.min, TZ), now)
        days_out = equipment_service.borrowed_days_expr(since, until)
        new_borrows = func.count(BorrowItem.id).filter(BorrowRequest.approved_at >= since)
        conds += equipment_service.overlaps_window(since, until)
    else:
        days_out = equipment_service.borrowed_days_expr()
        new_borrows = func.count(BorrowItem.id)
    usage_rows = (await db.execute(
        select(BorrowItem.equipment_id, new_borrows, func.coalesce(func.sum(days_out), 0))
        .join(BorrowRequest, BorrowItem.borrow_request_id == BorrowRequest.id)
        .where(*conds)
        .group_by(BorrowItem.equipment_id)
    )).all()
    usage = {eq_id: (int(cnt), int(days)) for eq_id, cnt, days in usage_rows}

    types = ALL_ITEM_TYPES if item_type == "all" else (item_type,) if item_type else UTILIZATION_TYPES
    equipment = (await db.execute(
        select(Equipment).where(Equipment.item_type.in_(types)).order_by(Equipment.code)
    )).scalars().all()

    years_default, salvage = await equipment_service._depreciation_settings(db)
    rows: list[UtilizationRow] = []
    for eq in equipment:
        count, days = usage.get(eq.id, (0, 0))
        # วันที่อยู่ในระบบ = ตั้งแต่ของเข้าระบบ (หรือวันที่ได้มา ถ้าช้ากว่า) ถึงวันนี้ — ก่อนหน้านั้นระบบไม่เคยบันทึก
        # การยืมได้ ถ้าวัดตั้งแต่วันซื้อ ของเก่าที่เพิ่งนำเข้าจะดูเหมือนไม่มีใครใช้มาหลายปี (ทั้งที่แค่ไม่มีข้อมูล)
        # และเป็นหลักเดียวกับ cost-per-use สากล: ต้นทุน "ของช่วงนั้น" ÷ การใช้ "ในช่วงเดียวกัน"
        tracked_from = max(d for d in (eq.created_at.astimezone(TZ).date(), eq.acquired_at) if d)
        if period and tracked_from > date_to:
            continue   # ยังไม่เข้าระบบในช่วงที่เลือก — ไม่มีข้อมูลให้ตัดสิน
        lo = max(tracked_from, date_from) if period else tracked_from
        # เลือกช่วง = นับรวมวันสุดท้าย (1–21 ก.ย. = 21 วัน) · สะสม = วันที่ผ่านไปแล้วตั้งแต่เข้าระบบ
        hi = min(date_to, today) + timedelta(days=1) if period else today
        tracked_days = max((hi - lo).days, 1)   # เข้าระบบวันนี้ก็นับ 1 วัน ไม่หารด้วยศูนย์
        rate = min(days / tracked_days, 1.0)
        daily = equipment_service.daily_depreciation(eq, years_default, salvage)
        # ค่าเสื่อมที่เกิดในช่วงวัด — ของที่หมดอายุการใช้งานไปแล้วไม่เสื่อมเพิ่ม (รู้ได้เฉพาะตอนมีวันที่ได้มา)
        dep_days = tracked_days
        if eq.acquired_at:
            life_end = eq.acquired_at + timedelta(days=equipment_service.life_days(eq, years_default))
            dep_days = max(min((life_end - lo).days, tracked_days), 0)
        value = float(eq.unit_value) if eq.unit_value is not None else None
        rows.append(UtilizationRow(
            equipment_id=eq.id, code=eq.code, name=eq.name, item_type=eq.item_type, status=eq.status,
            unit_value=value, acquired_at=eq.acquired_at,
            borrow_count=count, days_borrowed=days, tracked_days=tracked_days,
            utilization_rate=rate,
            daily_depreciation=round(daily, 2) if daily is not None else None,
            cost_per_use_day=round(daily * dep_days / days, 2) if daily is not None and days else None,
            rating=_rate_label(rate, days),
        ))

    never = [r for r in rows if r.days_borrowed == 0]
    first_at = (await db.execute(select(func.min(BorrowRequest.approved_at)))).scalar()
    first = first_at.astimezone(TZ).date() if first_at else None
    # ตัวหาร "เฉลี่ยของอยู่นอกคลังกี่ชิ้นต่อวัน" นับรวมวันนี้ (ของที่ยังไม่คืนถูกนับถึงตอนนี้)
    if period:
        span_days = max((min(date_to, today) - date_from).days + 1, 1)
    else:
        span_days = (today - first).days + 1 if first else 0
    return UtilizationResponse(
        rows=rows,
        never_borrowed_count=len(never),
        never_borrowed_value=sum(r.unit_value or 0 for r in never),
        total_days_borrowed=sum(r.days_borrowed for r in rows),
        span_days=span_days,
        depreciation_years_default=years_default, salvage_value=salvage,
        good_threshold=UTILIZATION_GOOD, fair_threshold=UTILIZATION_FAIR,
        date_from=date_from if period else None, date_to=date_to if period else None,
        monthly=await _monthly_usage(db, types, now, first),
    )


async def _monthly_usage(
    db: AsyncSession, types: tuple[str, ...], now: datetime, first: date | None,
) -> list[UtilizationMonth]:
    """สรุปรายเดือน (ปฏิทิน) ตอบว่า "เดือนไหนใช้ของเยอะ/น้อย" — ยืมใหม่ / วันที่ของออกจากคลัง (ตัดเฉพาะส่วนที่
    อยู่ในเดือนนั้น) / มูลค่าที่ถูกยืมออก (นิยามเดียวกับการ์ด Dashboard: ราคา ณ วันอนุมัติ ตามเดือนที่อนุมัติ)

    ครอบทุกเดือนตั้งแต่เดือนแรกที่มีการอนุมัติถึงเดือนนี้เสมอ **ไม่ขึ้นกับช่วงที่เลือก** (เลือก "เดือนนี้" แล้วเหลือ
    แถวเดียวจะเทียบกับเดือนอื่นไม่ได้ — หน้าเว็บไฮไลต์เดือนที่เลือกแทน) · กรองประเภทด้วย item_type_snapshot
    """
    if first is None:
        return []
    last = now.date()
    months: list[tuple[int, int]] = []
    y, m = first.year, first.month
    while (y, m) <= (last.year, last.month):
        months.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)

    out: list[UtilizationMonth] = []
    for y, m in months[-MAX_MONTHS:]:
        since = datetime(y, m, 1, tzinfo=TZ)
        until = min(datetime(y + 1, 1, 1, tzinfo=TZ) if m == 12 else datetime(y, m + 1, 1, tzinfo=TZ), now)
        is_new = BorrowRequest.approved_at >= since
        cnt, days, value = (await db.execute(
            select(
                func.count(BorrowItem.id).filter(is_new),
                func.coalesce(func.sum(equipment_service.borrowed_days_expr(since, until)), 0),
                func.coalesce(func.sum(BorrowItem.quantity * BorrowItem.unit_value_snapshot).filter(is_new), 0),
            )
            .select_from(BorrowItem)
            .join(BorrowRequest, BorrowItem.borrow_request_id == BorrowRequest.id)
            .where(BorrowItem.item_status != "rejected", BorrowRequest.approved_at.is_not(None),
                   BorrowItem.item_type_snapshot.in_(types), *equipment_service.overlaps_window(since, until))
        )).one()
        out.append(UtilizationMonth(month=f"{y}-{m:02d}", new_borrows=int(cnt), days_borrowed=int(days),
                                    borrowed_value=float(value)))
    return out


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
