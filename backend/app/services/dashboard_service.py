from datetime import datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import TZ
from app.models.borrow_item import BorrowItem
from app.models.borrow_request import BorrowRequest
from app.models.equipment import Equipment
from app.models.setting import Setting
from app.schemas.dashboard import DashboardSummaryResponse, EquipmentCounts

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

    # ต้นทุนวัสดุที่ถูกใช้ไปในเดือนนี้ = ผลรวม (จำนวน × ราคาต่อหน่วย ณ วันอนุมัติ)
    # นับเฉพาะ used_up/discarded — ของที่คืนครบ (returned_full) กลับเข้าคลังแล้ว ไม่ใช่ต้นทุน
    month_start = datetime.now(TZ).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    consumed_result = await db.execute(
        select(func.coalesce(func.sum(BorrowItem.quantity * BorrowItem.unit_value_snapshot), 0)).where(
            BorrowItem.condition_on_return.in_(("used_up", "discarded")),
            BorrowItem.returned_at >= month_start,
        )
    )

    # ครบกำหนดตรวจนับทางกายภาพ — mirror cutoff เดียวกับ equipment_service._audit_cutoff /
    # scheduler._check_audit_due (ยังไม่เคยตรวจนับ หรือตรวจนับล่าสุดเกิน audit_interval_days วันแล้ว)
    interval_days = await _get_setting_int(db, "audit_interval_days")
    audit_cutoff = datetime.now(TZ) - timedelta(days=interval_days)
    due_for_audit_result = await db.execute(
        select(func.count(Equipment.id)).where(
            Equipment.status != "retired",
            or_(Equipment.last_audited_at.is_(None), Equipment.last_audited_at < audit_cutoff),
        )
    )

    return DashboardSummaryResponse(
        pending_requests=pending_result.scalar() or 0,
        overdue_requests=overdue_result.scalar() or 0,
        low_stock_items=low_stock_result.scalar() or 0,
        active_borrows=active_borrows_result.scalar() or 0,
        equipment_borrowed_out=borrowed_out_result.scalar() or 0,
        equipment_counts=equipment_counts,
        consumed_value_this_month=float(consumed_result.scalar() or 0),
        due_for_audit_items=due_for_audit_result.scalar() or 0,
    )
