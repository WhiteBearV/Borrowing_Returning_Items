"""GET /borrow-requests?own_only=true — หน้า "คำขอยืมของฉัน" ของ admin ต้องเห็นแค่คำขอของตัวเอง
ไม่ปนของนักศึกษาคนอื่น (ต่างจาก endpoint เดิมที่ role=admin เห็นทุกคนเสมอ)

หมายเหตุ: conftest.py มี PYTEST_ALLOW_DB=1 รันใส่ DB dev จริง — ทุกเทสต้อง cleanup ใน finally เสมอ
"""
import uuid

from httpx import AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token, hash_password
from app.models.borrow_item import BorrowItem
from app.models.borrow_request import BorrowRequest
from app.models.notification import Notification
from app.models.user import User
from tests.conftest import _delete_user_cascade, auth


async def _make_student() -> User:
    """สร้างนักศึกษาทดสอบแยกใหม่ทุกครั้ง — เลี่ยงชน max_active_requests_per_student ของ test_student
    (fixture ระดับ session ที่ไฟล์เทสอื่นในรันเดียวกันอาจสร้างคำขอค้างไว้โดยไม่ cleanup ทัน)"""
    uid = uuid.uuid4()
    async with AsyncSessionLocal() as db:
        user = User(
            id=uid, full_name=f"นักศึกษาทดสอบ own_only {uid.hex[:6]}",
            email=f"ownonly_{uid.hex[:6]}@cdti.ac.th",
            password_hash=hash_password("Test1234!"),
            role="student", student_id=f"65{uid.hex[:8]}",
            email_verified=True, is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


async def _create_pending(client: AsyncClient, token: str, equipment_id: uuid.UUID, purpose: str) -> str:
    r = await client.post("/borrow-requests", headers=auth(token), json={
        "purpose": purpose,
        "requested_due_date": "2028-06-01", "items": [{"equipment_id": str(equipment_id), "quantity": 1}],
    })
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_own_only_hides_other_users_requests_from_admin(client: AsyncClient, admin_token: str, test_equipment):
    student = await _make_student()
    student_token = create_access_token(str(student.id), extra={"role": "student"})
    student_req_id = await _create_pending(client, student_token, test_equipment.id, "ทดสอบ own_only (student)")
    admin_req_id = await _create_pending(client, admin_token, test_equipment.id, "ทดสอบ own_only (admin)")
    try:
        own_only = (await client.get("/borrow-requests", params={"own_only": "true", "page_size": 100}, headers=auth(admin_token))).json()
        own_only_ids = {item["id"] for item in own_only["items"]}
        assert admin_req_id in own_only_ids
        assert student_req_id not in own_only_ids

        everyone = (await client.get("/borrow-requests", params={"page_size": 100}, headers=auth(admin_token))).json()
        everyone_ids = {item["id"] for item in everyone["items"]}
        assert admin_req_id in everyone_ids
        assert student_req_id in everyone_ids
    finally:
        req_ids = [uuid.UUID(student_req_id), uuid.UUID(admin_req_id)]
        async with AsyncSessionLocal() as db:
            await db.execute(delete(Notification).where(Notification.borrow_request_id.in_(req_ids)))
            await db.execute(delete(BorrowItem).where(BorrowItem.borrow_request_id.in_(req_ids)))
            await db.execute(delete(BorrowRequest).where(BorrowRequest.id.in_(req_ids)))
            await db.commit()
        await _delete_user_cascade(student.id)
