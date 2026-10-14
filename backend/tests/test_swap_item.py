"""เปลี่ยนตัวระหว่างยืม (SKGRent ข้อ 4 — 24 ก.ย. 69)

ยืมครุภัณฑ์ A (รุ่นมี 2 หน่วย A/B) เลยกำหนด 3 วัน → A พัง เปลี่ยนเป็น B → คืน B ปกติ:
- A ปิดเป็น damaged + ค่าเสียหาย แต่ **ไม่มีค่าปรับล่าช้า** (การยืมยังไม่จบ) · A สถานะ damaged ไม่กลับเข้าคลัง
- B ได้วันครบกำหนดเดิม · ค่าปรับล่าช้าคิดครั้งเดียวตอนคืน B · วันที่ถูกยืมของ B นับตั้งแต่เปลี่ยนตัว ไม่ย้อนหลัง
- ไม่มีหน่วยว่างเหลือ = 400 · สิทธิ์เจ้าหน้าที่เท่านั้น

หมายเหตุ: conftest.py มี PYTEST_ALLOW_DB=1 รันใส่ DB dev จริง — ลบทุกอย่างที่สร้าง + audit ใน finally
"""
import uuid
from datetime import date, datetime, timedelta, timezone

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
from app.services import equipment_service
from tests.conftest import auth

FINE_KEYS = {"fine_per_day_per_item": "10", "fine_grace_days": "0", "fine_max_per_item": "0"}


async def test_swap_item_mid_loan(
    client: AsyncClient, admin_token: str, student_token: str, test_admin: User, test_student: User,
):
    a_id, b_id, req_id, item_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    tag = a_id.hex[:6].upper()
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        before = dict((await db.execute(
            select(Setting.key, Setting.value).where(Setting.key.in_(FINE_KEYS)))).all())
        for row in (await db.execute(select(Setting).where(Setting.key.in_(FINE_KEYS)))).scalars():
            row.value = FINE_KEYS[row.key]
        for eq_id, suffix, avail in ((a_id, "A", 0), (b_id, "B", 1)):
            db.add(Equipment(id=eq_id, code=f"TEST-SWP-{tag}-{suffix}", name=f"โน้ตบุ๊กทดสอบเปลี่ยนตัว {tag}",
                             item_type="durable", quantity_total=1, quantity_available=avail, status="available",
                             unit_value=1000, acquired_at=date.today(), useful_life_years=5))
        db.add(BorrowRequest(id=req_id, request_code=f"REQ-SWP-{req_id.hex[:6]}", student_id=test_student.id,
                             status="approved", purpose="ทดสอบเปลี่ยนตัว", approved_at=now - timedelta(days=10),
                             approved_by=test_admin.id, requested_due_date=date.today() - timedelta(days=3),
                             due_date=date.today() - timedelta(days=3)))
        db.add(BorrowItem(id=item_id, borrow_request_id=req_id, equipment_id=a_id, item_type_snapshot="durable",
                          quantity=1, item_status="approved", due_date=date.today() - timedelta(days=3),
                          book_value_snapshot=1000, equipment_code=f"TEST-SWP-{tag}-A",
                          equipment_name=f"โน้ตบุ๊กทดสอบเปลี่ยนตัว {tag}"))
        await db.commit()
    url = f"/borrow-requests/{req_id}/items/{item_id}/swap"
    h = auth(admin_token)
    try:
        body = {"condition_on_return": "damaged", "reason": "จอเสีย", "damage_photo_urls": ["/uploads/x.jpg"]}
        assert (await client.post(url, headers=auth(student_token), json=body)).status_code == 403
        assert (await client.post(url, headers=h, json={**body, "damage_photo_urls": []})).status_code == 400
        r = await client.post(url, headers=h, json=body)
        assert r.status_code == 200, r.text

        async with AsyncSessionLocal() as db:
            old = await db.get(BorrowItem, item_id)
            new = (await db.execute(select(BorrowItem).where(BorrowItem.swapped_from_id == item_id))).scalar_one()
            a, b = await db.get(Equipment, a_id), await db.get(Equipment, b_id)
            assert old.returned and old.condition_on_return == "damaged"
            assert float(old.fine_late_amount) == 0 and float(old.fine_damage_amount) == 1000
            assert a.status == "damaged" and a.quantity_available == 0
            assert new.equipment_id == b_id and new.due_date == old.due_date and not new.returned
            assert new.equipment_code == f"TEST-SWP-{tag}-B" and b.quantity_available == 0
            assert (await equipment_service.usage_days_map(db, [b_id]))[b_id] == 1   # ไม่ย้อนหลัง 10 วัน
            new_id = new.id

        # ไม่มีหน่วยว่างให้เปลี่ยนแล้ว (A พัง B ถูกยืมอยู่)
        r = await client.post(f"/borrow-requests/{req_id}/items/{new_id}/swap", headers=h,
                              json={"condition_on_return": "ok", "reason": "ทดสอบ"})
        assert r.status_code == 400, r.text

        r = await client.post(f"/borrow-requests/{req_id}/items/{new_id}/return", headers=h,
                              json={"condition_on_return": "ok"})
        assert r.status_code == 200, r.text
        async with AsyncSessionLocal() as db:
            new = await db.get(BorrowItem, new_id)
            assert float(new.fine_late_amount) == 30.0   # ล่าช้า 3 วัน คิดครั้งเดียว
            assert (await db.get(BorrowRequest, req_id)).status == "completed"
            assert (await db.get(Equipment, b_id)).quantity_available == 1
    finally:
        async with AsyncSessionLocal() as db:
            for row in (await db.execute(select(Setting).where(Setting.key.in_(before)))).scalars():
                row.value = before[row.key]
            ids = (await db.execute(select(BorrowItem.id).where(BorrowItem.borrow_request_id == req_id))
                   ).scalars().all()
            await db.execute(delete(AuditLog).where(AuditLog.target_id.in_([*ids, req_id])))
            await db.execute(delete(Notification).where(Notification.borrow_request_id == req_id))
            await db.execute(delete(BorrowItem).where(BorrowItem.borrow_request_id == req_id))
            await db.execute(delete(BorrowRequest).where(BorrowRequest.id == req_id))
            await db.execute(delete(Equipment).where(Equipment.id.in_((a_id, b_id))))
            await db.commit()
