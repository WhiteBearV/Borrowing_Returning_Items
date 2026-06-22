from datetime import date, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.borrow_request import BorrowRequest
from app.models.setting import Setting

scheduler = AsyncIOScheduler()


async def _check_due_soon() -> None:
    """แจ้งเตือนรายการที่ใกล้ครบกำหนดคืน (รันทุกวันเที่ยงคืน)"""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Setting).where(Setting.key == "due_soon_notify_days_before"))
        s = result.scalar_one_or_none()
        target_date = date.today() + timedelta(days=int(s.value) if s else 1)

        result = await db.execute(
            select(BorrowRequest).where(
                BorrowRequest.status == "approved",
                BorrowRequest.due_date == target_date,
                BorrowRequest.is_overdue == False,
            )
        )
        # TODO: ส่งแจ้งเตือน due_soon ให้นักศึกษา
        for req in result.scalars().all():
            pass


async def _check_overdue() -> None:
    """ตั้งค่า is_overdue=True และแจ้งเตือนรายการที่เกินกำหนดคืน (รันทุกวันเที่ยงคืน)"""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(BorrowRequest).where(
                BorrowRequest.status == "approved",
                BorrowRequest.due_date < date.today(),
                BorrowRequest.is_overdue == False,
            )
        )
        for req in result.scalars().all():
            req.is_overdue = True
            # TODO: ส่งแจ้งเตือน overdue ให้นักศึกษาและแอดมิน
        await db.commit()


def start_scheduler() -> None:
    scheduler.add_job(_check_due_soon, CronTrigger(hour=0, minute=0), id="due_soon")
    scheduler.add_job(_check_overdue, CronTrigger(hour=0, minute=1), id="overdue")
    scheduler.start()
