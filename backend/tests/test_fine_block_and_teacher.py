"""2 พ.ย. 69 — ระงับการยืมเมื่อค่าปรับค้าง ≥ fine_block_threshold · บัญชีอาจารย์ที่ยืมอย่างเดียว (role student ไม่มีรหัสนักศึกษา)

conftest.py รันใส่ DB dev จริง (PYTEST_ALLOW_DB=1) — ลบทุกอย่างที่สร้าง + audit + คืนค่า setting ใน finally
"""
import uuid
from datetime import date, datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.borrow_item import BorrowItem
from app.models.borrow_request import BorrowRequest
from app.models.setting import Setting
from app.models.user import User
from tests.conftest import auth


async def _set_threshold(value: str) -> None:
    async with AsyncSessionLocal() as db:
        (await db.execute(select(Setting).where(Setting.key == "fine_block_threshold"))).scalar_one().value = value
        await db.commit()


async def test_fine_block_threshold(client: AsyncClient, student_token: str, test_student: User):
    req_id, item_id = uuid.uuid4(), uuid.uuid4()
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        before = (await db.execute(select(Setting.value).where(Setting.key == "fine_block_threshold"))).scalar_one()
        db.add(BorrowRequest(id=req_id, request_code=f"REQ-FBK-{req_id.hex[:6]}", student_id=test_student.id,
                             status="completed", purpose="ทดสอบระงับการยืม", approved_at=now, returned_at=now,
                             requested_due_date=date.today(), due_date=date.today()))
        db.add(BorrowItem(id=item_id, borrow_request_id=req_id, item_type_snapshot="durable", quantity=1,
                          item_status="approved", returned=True, returned_at=now, condition_on_return="ok",
                          fine_late_amount=200, fine_damage_amount=0, fine_status="unpaid"))
        await db.commit()
    body = {"purpose": "ทดสอบ", "requested_due_date": str(date.today() + timedelta(days=3)),
            "items": [{"equipment_id": str(uuid.uuid4()), "quantity": 1}]}
    try:
        await _set_threshold("200")
        me = (await client.get("/users/me", headers=auth(student_token))).json()
        assert me["fine_blocked"] is True and me["fine_block_threshold"] == 200
        r = await client.post("/borrow-requests", headers=auth(student_token), json=body)
        assert r.status_code == 403 and "ค่าปรับค้างชำระ" in r.json()["detail"], r.text

        await _set_threshold("201")  # ยอดต่ำกว่าเกณฑ์ → ผ่านด่านค่าปรับ ไปติดเรื่องอุปกรณ์ไม่มีจริงแทน
        r = await client.post("/borrow-requests", headers=auth(student_token), json=body)
        assert r.status_code != 403, r.text
        await _set_threshold("0")  # 0 = ไม่ระงับ
        assert (await client.get("/users/me", headers=auth(student_token))).json()["fine_blocked"] is False
    finally:
        await _set_threshold(before)
        async with AsyncSessionLocal() as db:
            await db.execute(delete(BorrowItem).where(BorrowItem.borrow_request_id == req_id))
            await db.execute(delete(BorrowRequest).where(BorrowRequest.id == req_id))
            await db.commit()


async def test_teacher_borrower_counts_as_staff_label(client: AsyncClient, admin_token: str):
    tag = uuid.uuid4().hex[:6]
    r = await client.post("/users", headers=auth(admin_token), json={
        "email": f"teacher-{tag}@cdti.ac.th", "full_name": "อาจารย์ ทดสอบ", "password": "secret123",
        "role": "student", "username": f"T{tag}",
    })
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    try:
        assert r.json()["role"] == "student"
        assert r.json()["study_year_label"] == "บุคลากร"  # ไม่ใช่ "ไม่ทราบชั้นปี"
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(AuditLog).where(AuditLog.target_id == uuid.UUID(uid)))
            await db.execute(delete(User).where(User.id == uuid.UUID(uid)))
            await db.commit()
