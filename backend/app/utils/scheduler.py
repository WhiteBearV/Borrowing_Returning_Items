from datetime import date, datetime, timedelta
from html import escape

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.config import TZ
from app.core.database import AsyncSessionLocal
from app.models.borrow_item import BorrowItem
from app.models.borrow_request import BorrowRequest
from app.models.notification import Notification
from app.models.setting import Setting
from app.models.user import User
from app.utils.roles import STAFF_ROLES
from app.utils.duedate import fmt_date
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

        # เทียบวันครบกำหนด "ของแต่ละชิ้น" ไม่ใช่ของทั้งใบ — ตั้งแต่เฟส 3 วันคืนแยกรายชิ้นได้
        # และรายการที่ต่อเวลาแล้วมีวันของตัวเอง ดูแต่ due_date ระดับใบจะพลาดทั้งสองกรณี
        has_due_item = (
            select(BorrowItem.id)
            .where(
                BorrowItem.borrow_request_id == BorrowRequest.id,
                BorrowItem.returned == False,
                BorrowItem.item_status != "rejected",
                func.coalesce(BorrowItem.extended_due_date, BorrowItem.due_date,
                              BorrowRequest.due_date) == target_date,
            )
            .exists()
        )
        rows = (await db.execute(
            select(BorrowRequest)
            .options(selectinload(BorrowRequest.student))
            .where(
                BorrowRequest.status == "approved",
                BorrowRequest.is_overdue == False,
                has_due_item,
            )
        )).scalars().all()

        for req in rows:
            _notif(db, req.student_id, "due_soon",
                   f"คำขอ {req.request_code} มีอุปกรณ์ครบกำหนดคืนในอีก "
                   f"{(target_date - date.today()).days} วัน ({fmt_date(target_date)})",
                   borrow_request_id=req.id)

        if rows:
            await db.commit()

        # อีเมลแจ้งนักศึกษาทีละคน (ไม่ใช่ digest เหมือน admin เพราะแต่ละคนมีแค่ 1-2 รายการ)
        for req in rows:
            try:
                await send_email(
                    req.student.email,
                    f"ใกล้ครบกำหนดคืน — คำขอ {req.request_code}",
                    f"<p>คำขอยืม <b>{escape(req.request_code)}</b> มีอุปกรณ์ใกล้ครบกำหนดคืนแล้ว "
                    f"(ภายในวันที่ {fmt_date(target_date)}) กรุณาเตรียมนำอุปกรณ์มาคืน</p>",
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
                BorrowItem.item_status != "rejected",   # ชิ้นที่ไม่อนุมัติไม่เคยออกจากคลัง
                func.coalesce(BorrowItem.extended_due_date, BorrowItem.due_date,
                              BorrowRequest.due_date) < date.today(),
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

        admins = (await db.execute(select(User).where(User.role.in_(STAFF_ROLES), User.is_active == True))).scalars().all()

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
                    f"(ครบกำหนด {fmt_date(req.due_date)}) กรุณานำอุปกรณ์มาคืนโดยด่วน</p>",
                )
            except Exception as e:  # ponytail: อีเมลพังไม่ควรทำให้ job ล้ม
                print(f"[email] แจ้งนักศึกษา {req.student.email} ไม่สำเร็จ: {e}")

        # อีเมลสรุปให้ admin เป็น digest เดียวต่อรอบ กันสแปมถ้าเกินกำหนดพร้อมกันหลายรายการ
        if admins:
            # escape เลขคำขอ — มีส่วนที่มาจาก student_id/username ที่ผู้ใช้กรอกเอง
            items_html = "".join(
                f"<li>{escape(r.request_code)} (ครบกำหนด {fmt_date(r.due_date)})</li>" for r in rows
            )
            body = f"<p>มีคำขอเกินกำหนดคืน {len(rows)} รายการ:</p><ul>{items_html}</ul>"
            for admin in admins:
                try:
                    await send_email(admin.email, f"เกินกำหนดคืน {len(rows)} รายการ", body)
                except Exception as e:  # ponytail: อีเมลพังไม่ควรทำให้ job ล้ม
                    print(f"[email] แจ้ง admin {admin.email} ไม่สำเร็จ: {e}")


# เวลาส่งแจ้งเตือนรายวัน (setting `notify_time`, superadmin แก้ได้) — เดิมตายตัวเที่ยงคืน
# นักศึกษาได้อีเมลทวงตอนตี 0 · ค่าเริ่มต้นตรงกับ migration 0041
DEFAULT_NOTIFY_TIME = "08:00"
DAILY_JOB_IDS = ("due_soon", "overdue")


def _daily_trigger(hhmm: str) -> CronTrigger:
    """"HH:MM" (เวลาไทย) → CronTrigger — ค่าเพี้ยน (หลุดการตรวจตอนบันทึก) ถอยไปค่าเริ่มต้น ไม่ให้แอปบูตไม่ขึ้น"""
    try:
        h, m = (int(x) for x in hhmm.split(":"))
        return CronTrigger(hour=h, minute=m)
    except (ValueError, AttributeError):
        return _daily_trigger(DEFAULT_NOTIFY_TIME)


def reschedule_daily_jobs(hhmm: str) -> None:
    """เลื่อนเวลา job รายวันทันทีที่ setting เปลี่ยน ไม่ต้องรีสตาร์ต — ข้ามเงียบ ๆ ถ้า scheduler ไม่ได้รัน
    (เทส/สคริปต์ที่ไม่ผ่าน lifespan ของแอป)"""
    for job_id in DAILY_JOB_IDS:
        if scheduler.get_job(job_id):
            scheduler.reschedule_job(job_id, trigger=_daily_trigger(hhmm))


async def start_scheduler() -> None:
    try:
        async with AsyncSessionLocal() as db:
            hhmm = (await db.execute(
                select(Setting.value).where(Setting.key == "notify_time"))).scalar_one_or_none()
    except Exception as e:  # ponytail: DB ยังไม่พร้อม ไม่ควรทำให้แอปบูตไม่ขึ้น ใช้ค่าเริ่มต้นไปก่อน
        print(f"[scheduler] อ่าน notify_time ไม่ได้ ใช้ {DEFAULT_NOTIFY_TIME}: {e}")
        hhmm = None
    trigger = _daily_trigger(hhmm or DEFAULT_NOTIFY_TIME)
    # misfire_grace_time: ถ้า VM ปิด/รีสตาร์ตคร่อมเวลาส่ง job จะรันชดเชยภายใน 1 ชม.
    # ไม่ใส่ = รอบนั้นหายถาวร ไม่มีใครได้รับแจ้งเตือนของวันนั้นเลย
    scheduler.add_job(_check_due_soon, trigger, id="due_soon", misfire_grace_time=3600)
    scheduler.add_job(_check_overdue, trigger, id="overdue", misfire_grace_time=3600)
    scheduler.start()
