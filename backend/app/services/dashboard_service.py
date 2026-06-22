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
    # อุปกรณ์สิ้นเปลืองที่สต็อกต่ำ
    low_stock_result = await db.execute(
        select(func.count(Equipment.id)).where(
            Equipment.item_type == "consumable",
            Equipment.low_stock_threshold.is_not(None),
            Equipment.quantity_available <= Equipment.low_stock_threshold,
        )
    )
    return {
        "pending_requests": pending_result.scalar() or 0,
        "overdue_requests": overdue_result.scalar() or 0,
        "low_stock_items": low_stock_result.scalar() or 0,
    }
