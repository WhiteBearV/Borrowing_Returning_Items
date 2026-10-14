"""ยอดคงเหลือต้องหักของที่ยังอยู่กับผู้ยืมเสมอ (QA-18 / QA-19 — 30 ก.ย. 69)

- เครื่องที่ถูกยืมอยู่ สลับสถานะ ซ่อม → พร้อมใช้ ต้องไม่กลับมาว่าง (เดิมตั้ง avail = total → ยืมซ้อน)
- ลด quantity_total ต่ำกว่าที่ยังยืมอยู่ = 400 · ติดลบ = 422 (เดิม 500)
- ปรับยอดคงเหลือเกิน total − ที่ยืมอยู่ = 400

หมายเหตุ: conftest.py มี PYTEST_ALLOW_DB=1 รันใส่ DB dev จริง — ลบทุกอย่างที่สร้าง + audit ใน finally
"""
import uuid
from datetime import date, datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.borrow_item import BorrowItem
from app.models.borrow_request import BorrowRequest
from app.models.equipment import Equipment
from app.models.user import User
from tests.conftest import auth


async def test_stock_cannot_be_released_while_on_loan(
    client: AsyncClient, admin_token: str, test_admin: User, test_student: User,
):
    unit_id, pool_id, req_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    tag = unit_id.hex[:6].upper()
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        db.add(Equipment(id=unit_id, code=f"TEST-LOAN-{tag}-U", name=f"เครื่องทดสอบยืมซ้อน {tag}", item_type="durable",
                         quantity_total=1, quantity_available=0, status="available", unit_value=100,
                         acquired_at=date.today()))
        db.add(Equipment(id=pool_id, code=f"TEST-LOAN-{tag}-P", name=f"สายทดสอบยอดรวม {tag}", item_type="consumable",
                         quantity_total=100, quantity_available=40, status="available", unit_value=1,
                         acquired_at=date.today()))
        db.add(BorrowRequest(id=req_id, request_code=f"REQ-LOAN-{req_id.hex[:6]}", student_id=test_student.id,
                             status="approved", purpose="ทดสอบยอดคงเหลือ", approved_at=now, approved_by=test_admin.id,
                             requested_due_date=date.today() + timedelta(days=3),
                             due_date=date.today() + timedelta(days=3)))
        for eq_id, qty in ((unit_id, 1), (pool_id, 60)):
            db.add(BorrowItem(borrow_request_id=req_id, equipment_id=eq_id, item_type_snapshot="durable",
                              quantity=qty, item_status="approved", due_date=date.today() + timedelta(days=3)))
        await db.commit()
    h = auth(admin_token)
    try:
        # QA-18: ซ่อม → พร้อมใช้ ขณะยังถูกยืมอยู่ ต้องไม่ปล่อยให้ว่าง
        for st in ("under_repair", "available"):
            r = await client.patch(f"/equipment/{unit_id}", headers=h, json={"status": st, "status_reason": "ทดสอบ"})
            assert r.status_code == 200, r.text
        assert r.json()["quantity_available"] == 0

        # QA-19: ลด total ต่ำกว่าที่ยืมอยู่ (60) / ติดลบ
        r = await client.patch(f"/equipment/{pool_id}", headers=h, json={"quantity_total": 59})
        assert r.status_code == 400, r.text
        r = await client.patch(f"/equipment/{pool_id}", headers=h, json={"quantity_total": -1})
        assert r.status_code == 422, r.text
        r = await client.patch(f"/equipment/{pool_id}", headers=h, json={"quantity_total": 70})
        assert r.status_code == 200, r.text
        assert r.json()["quantity_available"] == 10  # ลดของบนชั้นลงตาม ไม่แตะส่วนที่ยืมอยู่

        # ปรับยอดคงเหลือเกิน total − ที่ยืมอยู่
        r = await client.post(f"/equipment/{pool_id}/adjust-stock", headers=h, json={"new_available": 11, "reason": "นับ"})
        assert r.status_code == 400, r.text
        r = await client.post(f"/equipment/{pool_id}/adjust-stock", headers=h, json={"new_available": 10, "reason": "นับ"})
        assert r.status_code == 200, r.text
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(AuditLog).where(AuditLog.target_id.in_([unit_id, pool_id, req_id])))
            await db.execute(delete(BorrowItem).where(BorrowItem.borrow_request_id == req_id))
            await db.execute(delete(BorrowRequest).where(BorrowRequest.id == req_id))
            await db.execute(delete(Equipment).where(Equipment.id.in_([unit_id, pool_id])))
            await db.commit()
