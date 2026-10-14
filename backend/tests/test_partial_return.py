"""คืนบางส่วน / แยกสภาพในรายการเดียว (SKGRent ข้อ 2 — 24 ก.ย. 69)

ยืมวัสดุ 10 ชิ้น คืนช้า 3 วัน → ดี 7 · พัง 2 · หาย 1 (กด 3 รอบ):
- สต็อกคืนเฉพาะ 7 ชิ้นที่ดี · คำขอปิดเมื่อคืนครบทั้ง 10
- ค่าปรับล่าช้าคิดครั้งเดียวต่อรายการ (ไม่ใช่ × จำนวนรอบที่คืน) · ค่าเสียหาย × จำนวนที่เสีย
- สถิติยังนับเป็นการยืม 1 ครั้ง (แถวลูกไม่นับวัน/ครั้งซ้ำ)

หมายเหตุ: conftest.py มี PYTEST_ALLOW_DB=1 รันใส่ DB dev จริง — ลบทุกอย่างที่สร้างใน finally
"""
import uuid
from datetime import date, timedelta

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
from app.services import borrow_service, equipment_service
from tests.conftest import auth

FINE_KEYS = {"fine_per_day_per_item": "10", "fine_grace_days": "0", "fine_max_per_item": "0"}


async def test_partial_return_split_conditions(
    client: AsyncClient, admin_token: str, test_admin: User, test_student: User,
):
    eq_id, req_id, item_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with AsyncSessionLocal() as db:
        before = {k: v for k, v in (await db.execute(
            select(Setting.key, Setting.value).where(Setting.key.in_(FINE_KEYS)))).all()}
        for row in (await db.execute(select(Setting).where(Setting.key.in_(FINE_KEYS)))).scalars():
            row.value = FINE_KEYS[row.key]
        db.add(Equipment(
            id=eq_id, code=f"TEST-PRT-{eq_id.hex[:6].upper()}", name=f"สายทดสอบคืนบางส่วน {eq_id.hex[:6]}",
            item_type="material", quantity_total=10, quantity_available=10, status="available",
            unit_value=100, acquired_at=date.today(), useful_life_years=5,
        ))
        db.add(BorrowRequest(
            id=req_id, request_code=f"REQ-PRT-{req_id.hex[:6]}", student_id=test_student.id,
            status="pending", purpose="ทดสอบคืนบางส่วน", requested_due_date=date(2099, 1, 1),
        ))
        db.add(BorrowItem(id=item_id, borrow_request_id=req_id, equipment_id=eq_id,
                          item_type_snapshot="material", quantity=10))
        await db.commit()
    try:
        async with AsyncSessionLocal() as db:
            await borrow_service.approve_request(db, await db.get(User, test_admin.id), req_id)
        async with AsyncSessionLocal() as db:
            (await db.get(BorrowItem, item_id)).due_date = date.today() - timedelta(days=3)
            await db.commit()

        url = f"/borrow-requests/{req_id}/items/{item_id}/return"
        h = auth(admin_token)
        photo = ["/uploads/test.jpg"]
        assert (await client.post(url, headers=h, json={"condition_on_return": "ok", "quantity": 11})
                ).status_code == 400
        r = await client.post(url, headers=h, json={"condition_on_return": "ok", "quantity": 7})
        assert r.status_code == 200, r.text
        r = await client.post(url, headers=h, json={"condition_on_return": "damaged", "quantity": 2,
                                                     "damage_photo_urls": photo})
        assert r.status_code == 200, r.text
        # ชิ้นสุดท้าย — ไม่ส่ง quantity = คืนที่เหลือทั้งหมด (ไม่แตกแถว)
        r = await client.post(url, headers=h, json={"condition_on_return": "lost", "damage_photo_urls": photo})
        assert r.status_code == 200, r.text

        async with AsyncSessionLocal() as db:
            items = (await db.execute(select(BorrowItem).where(BorrowItem.borrow_request_id == req_id))
                     ).scalars().all()
            by_cond = {i.condition_on_return: i for i in items}
            assert sum(i.quantity for i in items) == 10 and all(i.returned for i in items)
            assert {c: i.quantity for c, i in by_cond.items()} == {"ok": 7, "damaged": 2, "lost": 1}
            assert by_cond["lost"].id == item_id and by_cond["ok"].split_from_id == item_id
            # ล่าช้า 3 วัน × 10 = 30 บาท คิดครั้งเดียวทั้งรายการ (ตกที่รอบแรก) ไม่ใช่ 90
            assert sum(float(i.fine_late_amount) for i in items) == 30.0
            assert float(by_cond["ok"].fine_late_amount) == 30.0
            # ค่าเสียหาย = มูลค่าต่อหน่วย 100 × จำนวนที่เสีย
            assert float(by_cond["damaged"].fine_damage_amount) == 200.0
            assert float(by_cond["lost"].fine_damage_amount) == 100.0
            assert float(by_cond["ok"].fine_damage_amount) == 0.0

            eq = await db.get(Equipment, eq_id)
            assert eq.quantity_available == 7   # คืนเข้าสต็อกเฉพาะที่ดี
            assert (await db.get(BorrowRequest, req_id)).status == "completed"
            # สถิติ: แถวเดิมแถวเดียวเป็นตัวแทนการยืมครั้งนี้ — ไม่บวกวันซ้ำ 3 แถว
            assert (await equipment_service.usage_days_map(db, [eq_id]))[eq_id] == 1
    finally:
        async with AsyncSessionLocal() as db:
            for row in (await db.execute(select(Setting).where(Setting.key.in_(before)))).scalars():
                row.value = before[row.key]
            ids = (await db.execute(select(BorrowItem.id).where(BorrowItem.borrow_request_id == req_id))
                   ).scalars().all()
            await db.execute(delete(AuditLog).where(AuditLog.target_id.in_([*ids, req_id, eq_id])))
            await db.execute(delete(Notification).where(Notification.borrow_request_id == req_id))
            await db.execute(delete(BorrowItem).where(BorrowItem.borrow_request_id == req_id))
            await db.execute(delete(BorrowRequest).where(BorrowRequest.id == req_id))
            await db.execute(delete(Equipment).where(Equipment.id == eq_id))
            await db.commit()
