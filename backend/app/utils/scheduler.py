from datetime import date, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.borrow_request import BorrowRequest
from app.models.notification import Notification
from app.models.setting import Setting
from app.models.user import User

scheduler = AsyncIOScheduler()


def _notif(db, user_id, notif_type, message, borrow_request_id=None):
    db.add(Notification(
        user_id=user_id,
        borrow_request_id=borrow_request_id,
        type=notif_type,
        channel="in_app",
        message=message,
    ))


async def _check_due_soon() -> None:
    """แจ้งเตือนรายการที่ใกล้ครบกำหนดคืน (รันทุกวันเที่ยงคืน)"""
    async with AsyncSessionLocal() as db:
        s = (await db.execute(select(Setting).where(Setting.key == "due_soon_notify_days_before"))).scalar_one_or_none()
        target_date = date.today() + timedelta(days=int(s.value) if s else 2)

        rows = (await db.execute(
            select(BorrowRequest).where(
                BorrowRequest.status == "approved",
                BorrowRequest.due_date == target_date,
                BorrowRequest.is_overdue == False,
            )
        )).scalars().all()

        for req in rows:
            _notif(db, req.student_id, "due_soon",
                   f"คำขอ {req.request_code} ครบกำหนดคืนในอีก {(target_date - date.today()).days} วัน ({req.due_date})",
                   borrow_request_id=req.id)

        if rows:
            await db.commit()


async def _check_overdue() -> None:
    """ตั้งค่า is_overdue=True และแจ้งเตือนรายการที่เกินกำหนดคืน (รันทุกวันเที่ยงคืน)"""
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(BorrowRequest).where(
                BorrowRequest.status == "approved",
                BorrowRequest.due_date < date.today(),
                BorrowRequest.is_overdue == False,
            )
        )).scalars().all()

        if not rows:
            return

        admins = (await db.execute(select(User).where(User.role == "admin", User.is_active == True))).scalars().all()

        for req in rows:
            req.is_overdue = True
            _notif(db, req.student_id, "overdue",
                   f"คำขอ {req.request_code} เกินกำหนดคืนแล้ว กรุณาคืนโดยด่วน",
                   borrow_request_id=req.id)
            for admin in admins:
                _notif(db, admin.id, "overdue",
                       f"คำขอ {req.request_code} เกินกำหนดคืน",
                       borrow_request_id=req.id)

        await db.commit()


def start_scheduler() -> None:
    scheduler.add_job(_check_due_soon, CronTrigger(hour=0, minute=0), id="due_soon")
    scheduler.add_job(_check_overdue, CronTrigger(hour=0, minute=1), id="overdue")
    scheduler.start()
