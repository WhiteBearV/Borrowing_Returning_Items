from datetime import date, datetime, timedelta
from html import escape

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.core.config import TZ
from app.core.database import AsyncSessionLocal
from app.models.borrow_item import BorrowItem
from app.models.borrow_request import BorrowRequest
from app.models.equipment import Equipment
from app.models.notification import Notification
from app.models.setting import Setting
from app.models.user import User
from app.utils.email import send_email

# ต้องระบุ timezone ไม่งั้น APScheduler ใช้โซนของ container ซึ่งเป็น UTC
# แล้ว CronTrigger(hour=0) จะไปยิงตอน 07:00 น. เวลาไทย ไม่ใช่เที่ยงคืนอย่างที่ตั้งใจ
scheduler = AsyncIOScheduler(timezone=TZ)


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
            select(BorrowRequest)
            .options(selectinload(BorrowRequest.student))
            .where(
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

        # อีเมลแจ้งนักศึกษาทีละคน (ไม่ใช่ digest เหมือน admin เพราะแต่ละคนมีแค่ 1-2 รายการ)
        for req in rows:
            try:
                await send_email(
                    req.student.email,
                    f"ใกล้ครบกำหนดคืน — คำขอ {req.request_code}",
                    f"<p>คำขอยืม <b>{escape(req.request_code)}</b> ใกล้ครบกำหนดคืนแล้ว "
                    f"(ภายในวันที่ {req.due_date}) กรุณาเตรียมนำอุปกรณ์มาคืน</p>",
                )
            except Exception as e:  # ponytail: อีเมลพังไม่ควรทำให้ job ล้ม
                print(f"[email] แจ้งนักศึกษา {req.student.email} ไม่สำเร็จ: {e}")


async def _check_overdue() -> None:
    """ตั้งค่า is_overdue=True และแจ้งเตือนรายการที่เกินกำหนดคืน (รันทุกวันเที่ยงคืน)"""
    async with AsyncSessionLocal() as db:
        # เทียบกำหนดคืน "ที่ใช้จริง" ของแต่ละรายการ = extended_due_date ถ้าต่อเวลาแล้ว
        # ไม่งั้นใช้ due_date ของใบ — ดูแค่ due_date ระดับใบอย่างเดียวจะทวงคนที่ต่อเวลาถูกต้อง
        # ใบไหนมีรายการที่ยังไม่คืนและเลยกำหนดแม้แต่ชิ้นเดียว ถือว่าใบนั้นเกินกำหนด
        has_overdue_item = (
            select(BorrowItem.id)
            .where(
                BorrowItem.borrow_request_id == BorrowRequest.id,
                BorrowItem.returned == False,
                func.coalesce(BorrowItem.extended_due_date, BorrowRequest.due_date) < date.today(),
            )
            .exists()
        )
        rows = (await db.execute(
            select(BorrowRequest)
            .options(selectinload(BorrowRequest.student))
            .where(
                BorrowRequest.status == "approved",
                BorrowRequest.is_overdue == False,
                has_overdue_item,
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

        # อีเมลแจ้งนักศึกษาแต่ละคนด้วย (เดิมมีแค่ in-app + digest ให้ admin เท่านั้น)
        for req in rows:
            try:
                await send_email(
                    req.student.email,
                    f"เกินกำหนดคืน — คำขอ {req.request_code}",
                    f"<p>คำขอยืม <b>{escape(req.request_code)}</b> เกินกำหนดคืนแล้ว "
                    f"(ครบกำหนด {req.due_date}) กรุณานำอุปกรณ์มาคืนโดยด่วน</p>",
                )
            except Exception as e:  # ponytail: อีเมลพังไม่ควรทำให้ job ล้ม
                print(f"[email] แจ้งนักศึกษา {req.student.email} ไม่สำเร็จ: {e}")

        # อีเมลสรุปให้ admin เป็น digest เดียวต่อรอบ กันสแปมถ้าเกินกำหนดพร้อมกันหลายรายการ
        if admins:
            # escape เลขคำขอ — มีส่วนที่มาจาก student_id/username ที่ผู้ใช้กรอกเอง
            items_html = "".join(
                f"<li>{escape(r.request_code)} (ครบกำหนด {r.due_date})</li>" for r in rows
            )
            body = f"<p>มีคำขอเกินกำหนดคืน {len(rows)} รายการ:</p><ul>{items_html}</ul>"
            for admin in admins:
                try:
                    await send_email(admin.email, f"เกินกำหนดคืน {len(rows)} รายการ", body)
                except Exception as e:  # ponytail: อีเมลพังไม่ควรทำให้ job ล้ม
                    print(f"[email] แจ้ง admin {admin.email} ไม่สำเร็จ: {e}")


async def _check_audit_due() -> None:
    """แจ้งเตือน admin (digest รายสัปดาห์) เมื่อมีอุปกรณ์ครบกำหนดตรวจนับทางกายภาพ — รันทุกวันจันทร์เที่ยงคืน
    ไม่ใช่รายวันเหมือน due_soon/overdue เพราะไม่มี flag กันแจ้งซ้ำแบบ BorrowRequest.is_overdue
    (ตรวจนับไม่ใช่เรื่องเร่งด่วนรายวัน แจ้งถี่กว่านี้จะกลายเป็นสแปมของเดิมซ้ำทุกวันไปเรื่อย ๆ)
    """
    async with AsyncSessionLocal() as db:
        s = (await db.execute(select(Setting.value).where(Setting.key == "audit_interval_days"))).scalar_one_or_none()
        cutoff = datetime.now(TZ) - timedelta(days=int(s) if s else 180)

        rows = (await db.execute(
            select(Equipment).where(
                Equipment.status != "retired",
                or_(Equipment.last_audited_at.is_(None), Equipment.last_audited_at < cutoff),
            )
        )).scalars().all()
        if not rows:
            return

        admins = (await db.execute(select(User).where(User.role == "admin", User.is_active == True))).scalars().all()
        for admin in admins:
            _notif(db, admin.id, "audit_due", f"มีอุปกรณ์ครบกำหนดตรวจนับทางกายภาพ {len(rows)} รายการ")
        await db.commit()

        if admins:
            items_html = "".join(f"<li>{escape(r.name)} ({escape(r.code)})</li>" for r in rows[:50])
            more = f"<p>และอีก {len(rows) - 50} รายการ</p>" if len(rows) > 50 else ""
            body = f"<p>มีอุปกรณ์ครบกำหนดตรวจนับทางกายภาพ {len(rows)} รายการ:</p><ul>{items_html}</ul>{more}"
            for admin in admins:
                try:
                    await send_email(admin.email, f"ครบกำหนดตรวจนับอุปกรณ์ {len(rows)} รายการ", body)
                except Exception as e:  # ponytail: อีเมลพังไม่ควรทำให้ job ล้ม
                    print(f"[email] แจ้ง admin {admin.email} ไม่สำเร็จ: {e}")


def start_scheduler() -> None:
    # misfire_grace_time: ถ้า VM ปิด/รีสตาร์ตคร่อมเที่ยงคืน job จะรันชดเชยภายใน 1 ชม.
    # ไม่ใส่ = รอบนั้นหายถาวร ไม่มีใครได้รับแจ้งเตือนของวันนั้นเลย
    scheduler.add_job(_check_due_soon, CronTrigger(hour=0, minute=0),
                      id="due_soon", misfire_grace_time=3600)
    scheduler.add_job(_check_overdue, CronTrigger(hour=0, minute=1),
                      id="overdue", misfire_grace_time=3600)
    # job รายสัปดาห์ — grace time ยาวกว่า job รายวัน (86400 = 1 วัน) เพราะถ้า VM ดับคร่อมช่วงนั้นเกิน 1 ชม.
    # งานทั้งสัปดาห์จะหายไปเลย ไม่เหมือน job รายวันที่พรุ่งนี้ก็รันชดเชยใหม่ได้อยู่ดี
    scheduler.add_job(_check_audit_due, CronTrigger(day_of_week="mon", hour=0, minute=2),
                      id="audit_due", misfire_grace_time=86400)
    scheduler.start()
