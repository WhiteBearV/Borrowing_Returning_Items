"""ซ่อนประวัติการยืมแทนการลบถาวร (SKGRent ข้อ 3 — 24 ก.ย. 69)

- บังคับเหตุผล · superadmin เท่านั้น · คำขอที่มีประวัติค่าปรับซ่อนไม่ได้ (รายงานเงินต้องครบ)
- ซ่อนแล้วหายจากรายการ/รายละเอียด/สถิติ (listener ตัวเดียว) แต่แถวยังอยู่ กู้คืนแล้วกลับมาครบ

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
from app.services import equipment_service
from tests.conftest import auth


async def test_hide_restore_request(
    client: AsyncClient, admin_token: str, superadmin_token: str, test_student: User,
):
    eq_id, req_id, fined_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    code = f"REQ-HIDE-{req_id.hex[:6]}"
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        db.add(Equipment(id=eq_id, code=f"TEST-HIDE-{eq_id.hex[:6].upper()}", name=f"ทดสอบซ่อน {eq_id.hex[:6]}",
                         item_type="durable", quantity_total=1, quantity_available=1, status="available"))
        for rid, rcode, fine in ((req_id, code, "none"), (fined_id, f"REQ-HIDE-{fined_id.hex[:6]}", "paid")):
            db.add(BorrowRequest(id=rid, request_code=rcode, student_id=test_student.id, status="completed",
                                 purpose="ทดสอบซ่อน", approved_at=now - timedelta(days=3), returned_at=now,
                                 requested_due_date=date.today(), due_date=date.today()))
            db.add(BorrowItem(borrow_request_id=rid, equipment_id=eq_id, item_type_snapshot="durable",
                              quantity=1, item_status="approved", returned=True, returned_at=now,
                              condition_on_return="ok", fine_status=fine))
        await db.commit()
    sa = auth(superadmin_token)
    try:
        async with AsyncSessionLocal() as db:
            days_before = (await equipment_service.usage_days_map(db, [eq_id]))[eq_id]

        assert (await client.request("DELETE", f"/borrow-requests/{req_id}", headers=auth(admin_token),
                                     json={"reason": "ทดสอบ"})).status_code == 403
        assert (await client.request("DELETE", f"/borrow-requests/{req_id}", headers=sa,
                                     json={"reason": "   "})).status_code == 422
        r = await client.request("DELETE", f"/borrow-requests/{fined_id}", headers=sa, json={"reason": "ทดสอบ"})
        assert r.status_code == 400, r.text   # มีประวัติค่าปรับ
        r = await client.request("DELETE", f"/borrow-requests/{req_id}", headers=sa, json={"reason": "คีย์ซ้ำ"})
        assert r.status_code == 204, r.text

        # หายจากทุกทาง: รายละเอียด · รายการ · สถิติ
        assert (await client.get(f"/borrow-requests/{req_id}", headers=sa)).status_code == 404
        listed = (await client.get("/borrow-requests", headers=sa, params={"search": code})).json()["items"]
        assert not listed
        async with AsyncSessionLocal() as db:
            assert (await equipment_service.usage_days_map(db, [eq_id]))[eq_id] < days_before
        hidden = (await client.get("/borrow-requests/hidden", headers=sa)).json()
        row = next(h for h in hidden if h["id"] == str(req_id))
        assert row["delete_reason"] == "คีย์ซ้ำ" and row["deleted_by_name"]

        assert (await client.post(f"/borrow-requests/{req_id}/restore", headers=sa)).status_code == 204
        assert (await client.get(f"/borrow-requests/{req_id}", headers=sa)).status_code == 200
        async with AsyncSessionLocal() as db:
            assert (await equipment_service.usage_days_map(db, [eq_id]))[eq_id] == days_before
    finally:
        async with AsyncSessionLocal() as db:
            ids = [req_id, fined_id]
            await db.execute(delete(AuditLog).where(AuditLog.target_id.in_(ids)))
            await db.execute(delete(BorrowItem).where(BorrowItem.borrow_request_id.in_(ids)))
            await db.execute(delete(BorrowRequest).where(BorrowRequest.id.in_(ids)))
            await db.execute(delete(Equipment).where(Equipment.id == eq_id))
            await db.commit()
