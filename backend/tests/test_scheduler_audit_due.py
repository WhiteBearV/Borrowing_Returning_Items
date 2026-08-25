"""scheduler._check_audit_due — แจ้งเตือน admin (ไม่ใช่นักศึกษา) เมื่อมีอุปกรณ์ครบกำหนดตรวจนับ

ใช้ test_admin (throwaway fixture ลบเองอัตโนมัติ) แทน admin_token จริง กัน notification ค้างบัญชีจริง
เนื่องจาก dev DB มีอุปกรณ์เดิมจำนวนมากที่ last_audited_at เป็น NULL อยู่แล้ว (ยังไม่เคยตรวจนับ) job
จึงมี rows ที่ไม่ว่างเสมอในทางปฏิบัติ — เทสนี้ยืนยันแค่ว่า admin ได้รับแจ้งเตือนจริง ไม่ได้ล็อกจำนวนเป๊ะ ๆ
"""
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.notification import Notification
from app.models.user import User
from app.utils.scheduler import _check_audit_due


async def test_check_audit_due_notifies_admins_only(test_admin: User, test_student):
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Notification).where(Notification.user_id == test_admin.id))
        await db.execute(delete(Notification).where(Notification.user_id == test_student.id))
        await db.commit()

    await _check_audit_due()

    async with AsyncSessionLocal() as db:
        admin_notifs = (await db.execute(
            select(Notification).where(Notification.user_id == test_admin.id, Notification.type == "audit_due")
        )).scalars().all()
        student_notifs = (await db.execute(
            select(Notification).where(Notification.user_id == test_student.id, Notification.type == "audit_due")
        )).scalars().all()

    assert len(admin_notifs) == 1
    assert "ครบกำหนดตรวจนับ" in admin_notifs[0].message
    assert student_notifs == []  # ตรวจนับกายภาพเป็นงานแอดมินเท่านั้น ไม่แจ้งนักศึกษา

    async with AsyncSessionLocal() as db:
        await db.execute(delete(Notification).where(Notification.user_id == test_admin.id))
        await db.commit()
