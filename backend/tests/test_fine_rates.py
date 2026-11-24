"""ป้ายอัตราค่าปรับคืนเกินกำหนดรายรุ่น (23 พ.ย. 69, migration 0056)

- สร้าง/แก้/ลบป้าย = ผู้ดูแลสูงสุดเท่านั้น · เจ้าหน้าที่ดูรายการได้ (ใช้เลือกในฟอร์ม)
- ตั้งป้ายที่หน่วยเดียว = ทั้งรุ่น · หน่วยใหม่ของรุ่นเดิมได้ป้ายตามรุ่น
- อัตราล็อกตอนอนุมัติ — แก้ราคาป้ายระหว่างยืมแล้วค่าปรับยังใช้อัตราเดิม
- ลบป้ายที่ยังใช้อยู่/ป้ายค่าเริ่มต้นไม่ได้
"""
import uuid
from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, or_, select

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.borrow_item import BorrowItem
from app.models.borrow_request import BorrowRequest
from app.models.equipment import Equipment
from app.models.equipment_category import EquipmentCategory
from app.models.fine_rate import FineRate
from app.models.notification import Notification
from app.models.user import User
from app.services import borrow_service
from tests.conftest import auth


@pytest.mark.asyncio(loop_scope="session")
async def test_fine_rate_tiers(
    client: AsyncClient, admin_token: str, superadmin_token: str, test_admin: User, test_student: User,
    test_category: EquipmentCategory,
):
    tag = uuid.uuid4().hex[:6]
    name = f"อุปกรณ์ทดสอบป้ายค่าปรับ {tag}"
    rate_name = f"ทดสอบ 50 บาท {tag}"
    rate_id = None
    eq_ids: list[uuid.UUID] = []
    req_id = None
    try:
        # ── สิทธิ์ + รายการ ──
        listed = (await client.get("/fine-rates", headers=auth(admin_token))).json()
        seeds = {r["amount_per_day"] for r in listed}
        assert {5.0, 10.0, 20.0, 30.0} <= seeds
        default = next(r for r in listed if r["is_default"])
        assert (await client.post("/fine-rates", headers=auth(admin_token),
                                  json={"name": rate_name, "amount_per_day": 50})).status_code == 403
        r = await client.post("/fine-rates", headers=auth(superadmin_token), json={"name": rate_name, "amount_per_day": 50})
        assert r.status_code == 201, r.text
        rate_id = r.json()["id"]
        assert (await client.post("/fine-rates", headers=auth(superadmin_token),
                                  json={"name": rate_name.upper(), "amount_per_day": 1})).status_code == 409

        # ── ตั้งที่หน่วยเดียว = ทั้งรุ่น ──
        async with AsyncSessionLocal() as db:
            for k in range(2):
                e = Equipment(id=uuid.uuid4(), code=f"TEST-FR-{tag}-{k}", name=name, item_type="durable",
                              quantity_total=1, quantity_available=1, status="available",
                              unit_value=1000, acquired_at=date.today(), fine_rate_id=uuid.UUID(default["id"]))
                db.add(e)
                eq_ids.append(e.id)
            await db.commit()
        r = await client.patch(f"/equipment/{eq_ids[0]}", headers=auth(admin_token), json={"fine_rate_id": rate_id})
        assert r.status_code == 200, r.text
        assert r.json()["fine_rate_per_day"] == 50.0 and r.json()["fine_rate_name"] == rate_name
        other = (await client.get(f"/equipment/{eq_ids[1]}", headers=auth(admin_token))).json()
        assert other["fine_rate_per_day"] == 50.0, "หน่วยอื่นในรุ่นต้องได้ป้ายเดียวกัน"

        # หน่วยใหม่ของรุ่นเดิมได้ป้ายตามรุ่น
        r = await client.post("/equipment", headers=auth(admin_token), json={
            "name": name, "category_ids": [str(test_category.id)], "item_type": "durable",
            "image_urls": ["/uploads/x.jpg"], "unit_value": 1000, "acquired_at": str(date.today())})
        assert r.status_code == 201, r.text
        eq_ids.append(uuid.UUID(r.json()["id"]))
        assert r.json()["fine_rate_per_day"] == 50.0

        # ── ล็อกอัตราตอนอนุมัติ ──
        req_id, item_id = uuid.uuid4(), uuid.uuid4()
        async with AsyncSessionLocal() as db:
            db.add(BorrowRequest(id=req_id, request_code=f"REQ-FR-{tag}", student_id=test_student.id, status="pending",
                                 purpose="ทดสอบป้ายค่าปรับ", requested_due_date=date(2099, 1, 1)))
            db.add(BorrowItem(id=item_id, borrow_request_id=req_id, equipment_id=eq_ids[0],
                              item_type_snapshot="durable", quantity=1))
            await db.commit()
        async with AsyncSessionLocal() as db:
            await borrow_service.approve_request(db, await db.get(User, test_admin.id), req_id)
        async with AsyncSessionLocal() as db:
            item = await db.get(BorrowItem, item_id)
            assert float(item.fine_rate_snapshot) == 50.0
            item.due_date = date.today() - timedelta(days=3)
            await db.commit()
        # ผู้ดูแลสูงสุดขึ้นราคาป้ายระหว่างยืม → ของที่ยืมอยู่ยังใช้ 50
        r = await client.patch(f"/fine-rates/{rate_id}", headers=auth(superadmin_token), json={"amount_per_day": 70})
        assert r.status_code == 200 and r.json()["amount_per_day"] == 70.0
        r = await client.post(f"/borrow-requests/{req_id}/items/{item_id}/return",
                              json={"condition_on_return": "ok"}, headers=auth(admin_token))
        assert r.status_code == 200, r.text
        async with AsyncSessionLocal() as db:
            item = await db.get(BorrowItem, item_id)
            assert float(item.fine_late_amount) == 150.0 and item.fine_basis["rate_per_day"] == 50.0

        # ── ลบ ──
        assert (await client.delete(f"/fine-rates/{rate_id}", headers=auth(superadmin_token))).status_code == 409
        assert (await client.delete(f"/fine-rates/{default['id']}", headers=auth(superadmin_token))).status_code == 409
        r = await client.patch(f"/equipment/{eq_ids[0]}", headers=auth(admin_token), json={"fine_rate_id": default["id"]})
        assert r.json()["fine_rate_per_day"] == default["amount_per_day"]
        assert (await client.delete(f"/fine-rates/{rate_id}", headers=auth(admin_token))).status_code == 403
        assert (await client.delete(f"/fine-rates/{rate_id}", headers=auth(superadmin_token))).status_code == 204
        rate_id = None
    finally:
        async with AsyncSessionLocal() as db:
            if req_id:
                item_ids = (await db.execute(select(BorrowItem.id).where(BorrowItem.borrow_request_id == req_id))).scalars().all()
                await db.execute(delete(AuditLog).where(AuditLog.target_id.in_([req_id, *item_ids])))
                await db.execute(delete(Notification).where(Notification.borrow_request_id == req_id))
                await db.execute(delete(BorrowItem).where(BorrowItem.borrow_request_id == req_id))
                await db.execute(delete(BorrowRequest).where(BorrowRequest.id == req_id))
            await db.execute(delete(AuditLog).where(or_(AuditLog.target_id.in_(eq_ids),
                                                        AuditLog.detail["name"].astext.in_([rate_name, name]))))
            await db.execute(delete(Equipment).where(Equipment.id.in_(eq_ids)))
            await db.execute(delete(FineRate).where(FineRate.name.in_([rate_name, rate_name.upper()])))
            await db.commit()


@pytest.mark.asyncio(loop_scope="session")
async def test_rename_into_other_model_takes_its_fine_rate(client: AsyncClient, admin_token: str):
    """เปลี่ยนชื่อจนย้ายรุ่น = ใช้ป้ายของรุ่นปลายทาง (ไม่กระทบหน่วยอื่นในรุ่นปลายทาง) · ชื่อใหม่ล้วน = คงป้ายเดิม
    · แก้หลายรายการก็เหมือนกัน · ลง audit ทุกครั้ง"""
    H = auth(admin_token)
    tag = uuid.uuid4().hex[:6]
    model_a, model_b = f"รุ่นทดสอบป้าย A {tag}", f"รุ่นทดสอบป้าย B {tag}"
    rates = {r["amount_per_day"]: uuid.UUID(r["id"]) for r in (await client.get("/fine-rates", headers=H)).json()}
    ids: list[uuid.UUID] = []
    try:
        async with AsyncSessionLocal() as db:
            # รุ่น B ใช้ป้าย 30 อยู่ 1 หน่วย · รุ่น A ป้าย 10 อยู่ 3 หน่วย
            for k, (name, rate) in enumerate([(model_b, 30.0), (model_a, 10.0), (model_a, 10.0), (model_a, 10.0)]):
                e = Equipment(id=uuid.uuid4(), code=f"TEST-FRM-{tag}-{k}", name=name, item_type="durable",
                              quantity_total=1, quantity_available=1, status="available", fine_rate_id=rates[rate])
                db.add(e)
                ids.append(e.id)
            await db.commit()
        b0, a1, a2, a3 = ids

        # แก้รายชิ้น: A1 เปลี่ยนชื่อเป็นรุ่น B → ได้ 30 · A ที่เหลือยังเป็น 10 · B0 ไม่โดนอะไร
        # ส่งป้ายเดิม (10) มาด้วยแบบที่ฟอร์มหน้าเว็บส่งทุกครั้ง — ค่าเดิมไม่นับว่า "เลือกเอง"
        r = await client.patch(f"/equipment/{a1}", headers=H, json={"name": model_b, "fine_rate_id": str(rates[10.0])})
        assert r.status_code == 200, r.text
        assert r.json()["fine_rate_per_day"] == 30.0
        assert (await client.get(f"/equipment/{a2}", headers=H)).json()["fine_rate_per_day"] == 10.0
        # ชื่อใหม่ล้วน (ยังไม่มีรุ่นนี้) = คงป้ายเดิม
        r = await client.patch(f"/equipment/{a2}", headers=H, json={"name": f"รุ่นใหม่ล้วน {tag}"})
        assert r.json()["fine_rate_per_day"] == 10.0
        # แก้หลายรายการ: A3 ย้ายเข้ารุ่น B → 30
        r = await client.patch("/equipment/bulk-update", headers=H,
                               json={"equipment_ids": [str(a3)], "update": {"name": model_b}})
        assert r.status_code == 200, r.text
        assert (await client.get(f"/equipment/{a3}", headers=H)).json()["fine_rate_per_day"] == 30.0

        async with AsyncSessionLocal() as db:
            logs = (await db.execute(select(AuditLog).where(AuditLog.target_id.in_([a1, a3])))).scalars().all()
        assert any((l.detail.get("changes") or {}).get("fine_rate") == ["10 บาท/วัน", "30 บาท/วัน"] for l in logs)
        assert any(l.detail.get("set", {}).get("fine_rate_inherited") for l in logs)
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(AuditLog).where(AuditLog.target_id.in_(ids)))
            await db.execute(delete(Equipment).where(Equipment.id.in_(ids)))
            await db.commit()
