from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.borrow_request import BorrowRequest
from app.models.equipment import Equipment


async def get_summary(db: AsyncSession) -> dict:
    """สรุปภาพรวมสำหรับ dashboard admin"""
    pending_result = await db.execute(
        select(func.count(BorrowRequest.id)).where(BorrowRequest.status == "pending")
    )
    overdue_result = await db.execute(
        select(func.count(BorrowRequest.id)).where(
            BorrowRequest.is_overdue == True, BorrowRequest.status == "approved"
        )
    )
    low_stock_result = await db.execute(
        select(func.count(Equipment.id)).where(
            Equipment.item_type == "consumable",
            Equipment.low_stock_threshold.is_not(None),
            Equipment.quantity_available <= Equipment.low_stock_threshold,
        )
    )
    # คำขอที่อยู่ระหว่างการยืม (approved ยังไม่คืนครบ)
    active_borrows_result = await db.execute(
        select(func.count(BorrowRequest.id)).where(BorrowRequest.status == "approved")
    )
    # จำนวนนักศึกษาที่ยืมของอยู่ (distinct student)
    active_borrowers_result = await db.execute(
        select(func.count(func.distinct(BorrowRequest.student_id))).where(BorrowRequest.status == "approved")
    )
    return {
        "pending_requests": pending_result.scalar() or 0,
        "overdue_requests": overdue_result.scalar() or 0,
        "low_stock_items": low_stock_result.scalar() or 0,
        "active_borrows": active_borrows_result.scalar() or 0,
        "active_borrowers": active_borrowers_result.scalar() or 0,
    }
