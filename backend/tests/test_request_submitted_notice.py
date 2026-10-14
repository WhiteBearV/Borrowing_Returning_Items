"""ส่งคำขอแล้วผู้ยืมต้องได้รู้ขั้นต่อไป (24 ก.ย. 69): แจ้งเตือน request_submitted + สถานที่รับของ (pickup_place)

หมายเหตุ: conftest.py มี PYTEST_ALLOW_DB=1 รันใส่ DB dev จริง — ลบทุกอย่างที่สร้างใน finally
"""
import uuid

from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.borrow_item import BorrowItem
from app.models.borrow_request import BorrowRequest
from app.models.equipment import Equipment
from app.models.notification import Notification
from app.models.setting import Setting
from app.models.user import User
from app.services.borrow_service import _fmt_appoint
from tests.conftest import auth


def test_fmt_appoint_keeps_location_without_time():
    assert _fmt_appoint(None, "ห้องพัสดุ") == "ที่ ห้องพัสดุ"
    assert _fmt_appoint(None, None) == ""


async def test_submit_notifies_borrower_with_pickup_place(
    client: AsyncClient, admin_token: str, student_token: str, test_student: User,
):
    r = await client.post("/equipment", headers=auth(admin_token), json={
        "name": f"ทดสอบแจ้งรับของ {uuid.uuid4().hex[:6]}", "category_ids": [], "item_type": "durable",
        "quantity_total": 1, "image_urls": ["/uploads/test.jpg"], "unit_value": 1000, "acquired_at": "2024-01-15"})
    eq_id, req_id = r.json()["id"], None
    try:
        r = await client.post("/borrow-requests", headers=auth(student_token), json={
            "purpose": "ทดสอบ", "requested_due_date": "2028-06-01",
            "items": [{"equipment_id": eq_id, "quantity": 1}]})
        assert r.status_code == 201, r.text
        req_id = r.json()["id"]
        async with AsyncSessionLocal() as db:
            place = (await db.execute(
                select(Setting.value).where(Setting.key == "default_pickup_location"))).scalar_one()
            note = (await db.execute(select(Notification).where(
                Notification.user_id == test_student.id, Notification.type == "request_submitted",
                Notification.borrow_request_id == uuid.UUID(req_id)))).scalar_one()
        assert place in note.message and "รอเจ้าหน้าที่อนุมัติ" in note.message
        assert r.json()["pickup_place"] == place   # หน้าเว็บนักศึกษาอ่าน settings ไม่ได้ ต้องมากับ response
    finally:
        async with AsyncSessionLocal() as db:
            if req_id:
                rid = uuid.UUID(req_id)
                await db.execute(delete(AuditLog).where(AuditLog.target_id == rid))
                await db.execute(delete(Notification).where(Notification.borrow_request_id == rid))
                await db.execute(delete(BorrowItem).where(BorrowItem.borrow_request_id == rid))
                await db.execute(delete(BorrowRequest).where(BorrowRequest.id == rid))
            await db.execute(delete(AuditLog).where(AuditLog.target_id == uuid.UUID(eq_id)))
            await db.execute(delete(Equipment).where(Equipment.id == uuid.UUID(eq_id)))
            await db.commit()
