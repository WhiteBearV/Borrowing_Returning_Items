"""SKGRent ข้อ 5 + 6 (24 ก.ย. 69)

ข้อ 5: ผู้ดูแลคลังยกเว้นค่าปรับเองได้เฉพาะยอด ≤ fine_waive_limit_admin (0 = ไม่ได้เลย ตามเดิม) · superadmin ทุกยอด
ข้อ 6: ยอดค้างชำระรวมต่อผู้ใช้ (unpaid_fine_total) โผล่ใน /users/me และรายการผู้ใช้ ลดลงเมื่อยกเว้น/ชำระ

หมายเหตุ: conftest.py มี PYTEST_ALLOW_DB=1 รันใส่ DB dev จริง — ลบทุกอย่างที่สร้าง + audit + คืนค่า setting ใน finally
"""
import uuid
from datetime import date, datetime, timezone

from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.borrow_item import BorrowItem
from app.models.borrow_request import BorrowRequest
from app.models.notification import Notification
from app.models.setting import Setting
from app.models.user import User
from tests.conftest import auth


async def _set_limit(value: str) -> None:
    async with AsyncSessionLocal() as db:
        (await db.execute(select(Setting).where(Setting.key == "fine_waive_limit_admin"))).scalar_one().value = value
        await db.commit()


async def test_admin_waive_limit_and_unpaid_total(
    client: AsyncClient, admin_token: str, superadmin_token: str, student_token: str, test_student: User,
):
    req_id, small, big = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        before = (await db.execute(select(Setting.value).where(Setting.key == "fine_waive_limit_admin"))).scalar_one()
        db.add(BorrowRequest(id=req_id, request_code=f"REQ-WVL-{req_id.hex[:6]}", student_id=test_student.id,
                             status="completed", purpose="ทดสอบเพดานยกเว้น", approved_at=now, returned_at=now,
                             requested_due_date=date.today(), due_date=date.today()))
        for iid, amount in ((small, 50), (big, 150)):
            db.add(BorrowItem(id=iid, borrow_request_id=req_id, item_type_snapshot="durable", quantity=1,
                              item_status="approved", returned=True, returned_at=now, condition_on_return="ok",
                              fine_late_amount=amount, fine_damage_amount=0, fine_status="unpaid"))
        await db.commit()
    waive = lambda iid: f"/borrow-requests/{req_id}/items/{iid}/fine/waive"  # noqa: E731
    try:
        me = (await client.get("/users/me", headers=auth(student_token))).json()
        assert me["unpaid_fine_total"] == 200

        await _set_limit("0")
        r = await client.patch(waive(small), headers=auth(admin_token), json={"reason": "เคสเล็ก"})
        assert r.status_code == 403, r.text
        await _set_limit("100")
        r = await client.patch(waive(big), headers=auth(admin_token), json={"reason": "เกินเพดาน"})
        assert r.status_code == 403, r.text
        r = await client.patch(waive(small), headers=auth(admin_token), json={"reason": "เคสเล็ก"})
        assert r.status_code == 200, r.text
        r = await client.patch(waive(big), headers=auth(superadmin_token), json={"reason": "ผู้ดูแลระบบอนุมัติ"})
        assert r.status_code == 200, r.text

        me = (await client.get("/users/me", headers=auth(student_token))).json()
        assert me["unpaid_fine_total"] == 0

        # QA-11 (30 ก.ย. 69): หลังยกเว้น ผู้ยืม (ไม่ใช่คนที่ยกเว้น) ต้องเปิดคำขอ/รายการ/PDF ได้ — เดิม 500 เพราะ
        # fine_waiver_name lazy-load นอก async (ผู้ยกเว้นไม่อยู่ใน identity map ของ request นั้น)
        r = await client.get(f"/borrow-requests/{req_id}", headers=auth(student_token))
        assert r.status_code == 200, r.text
        assert {i["fine_waiver_name"] for i in r.json()["items"]} - {None}
        r = await client.get("/borrow-requests", headers=auth(student_token))
        assert r.status_code == 200, r.text
        r = await client.get(f"/borrow-requests/{req_id}/return-pdf", headers=auth(student_token))
        assert r.status_code == 200, r.text
    finally:
        await _set_limit(before)
        async with AsyncSessionLocal() as db:
            await db.execute(delete(AuditLog).where(AuditLog.target_id.in_([req_id, small, big])))
            await db.execute(delete(Notification).where(Notification.borrow_request_id == req_id))
            await db.execute(delete(BorrowItem).where(BorrowItem.borrow_request_id == req_id))
            await db.execute(delete(BorrowRequest).where(BorrowRequest.id == req_id))
            await db.commit()
