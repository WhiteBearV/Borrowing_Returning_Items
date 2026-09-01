"""Tests: get_holders_map คืนผู้ยืมทุกคนต่อ equipment ไม่ใช่แค่คนสุดท้าย (บั๊กเดิม: dict comprehension
ทับ key ซ้ำ) — วัสดุสิ้นเปลืองแถวเดียวยืมพร้อมกันได้หลายคนคนละจำนวน ต้องเห็นชื่อ+รหัสนักศึกษาครบทุกคน

หมายเหตุ: conftest.py มี PYTEST_ALLOW_DB=1 รันใส่ DB dev จริง — ทุกเทสต้อง cleanup ใน finally เสมอ
"""
import uuid

from httpx import AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token, hash_password
from app.models.audit_log import AuditLog
from app.models.borrow_item import BorrowItem
from app.models.borrow_request import BorrowRequest
from app.models.equipment import Equipment
from app.models.notification import Notification
from app.models.user import User
from tests.conftest import auth


async def _make_second_student() -> User:
    uid = uuid.uuid4()
    async with AsyncSessionLocal() as db:
        user = User(
            id=uid, full_name=f"นักศึกษาทดสอบผู้ยืมคนที่สอง {uid.hex[:6]}",
            email=f"holder2_{uid.hex[:6]}@cdti.ac.th",
            password_hash=hash_password("Test1234!"),
            role="student", student_id=f"65{uid.hex[:8]}",
            email_verified=True, is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


async def _make_equipment(client: AsyncClient, admin_header: dict, **overrides) -> str:
    suffix = uuid.uuid4().hex[:6].upper()
    body = {
        "code": f"{uuid.uuid4().int % 10**15:015d}", "name": f"วัสดุสิ้นเปลืองทดสอบผู้ยืมหลายคน {suffix}",
        "category_ids": [], "item_type": "consumable", "quantity_total": 50,
        "image_urls": ["/uploads/test.jpg"],
    }
    body.update(overrides)
    r = await client.post("/equipment", json=body, headers=admin_header)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _cleanup(eq_id: str, req_ids: list[str], student_ids: list[uuid.UUID]) -> None:
    async with AsyncSessionLocal() as db:
        for req_id in req_ids:
            await db.execute(delete(Notification).where(Notification.borrow_request_id == uuid.UUID(req_id)))
            await db.execute(delete(BorrowItem).where(BorrowItem.borrow_request_id == uuid.UUID(req_id)))
            await db.execute(delete(BorrowRequest).where(BorrowRequest.id == uuid.UUID(req_id)))
        await db.execute(delete(AuditLog).where(AuditLog.target_id == uuid.UUID(eq_id)))
        await db.execute(delete(Equipment).where(Equipment.id == uuid.UUID(eq_id)))
        for sid in student_ids:
            await db.execute(delete(User).where(User.id == sid))
        await db.commit()


async def test_consumable_borrowed_by_two_students_shows_both_holders(
    client: AsyncClient, admin_token: str, student_token: str, test_student: User,
):
    h_admin = auth(admin_token)
    h_student1 = auth(student_token)
    student2 = await _make_second_student()
    h_student2 = auth(create_access_token(str(student2.id), extra={"role": "student"}))

    eq_id = await _make_equipment(client, h_admin)
    req_ids: list[str] = []
    try:
        r1 = await client.post("/borrow-requests", headers=h_student1, json={
            "requested_due_date": "2028-06-01", "items": [{"equipment_id": eq_id, "quantity": 5}],
        })
        assert r1.status_code == 201, r1.text
        req_ids.append(r1.json()["id"])
        assert (await client.patch(f"/borrow-requests/{req_ids[0]}/approve", headers=h_admin)).status_code == 200

        r2 = await client.post("/borrow-requests", headers=h_student2, json={
            "requested_due_date": "2028-06-01", "items": [{"equipment_id": eq_id, "quantity": 3}],
        })
        assert r2.status_code == 201, r2.text
        req_ids.append(r2.json()["id"])
        assert (await client.patch(f"/borrow-requests/{req_ids[1]}/approve", headers=h_admin)).status_code == 200

        # list_equipment (ตารางจัดการอุปกรณ์) ต้องเห็นผู้ยืมทั้งสองคน ไม่ใช่แค่คนสุดท้าย (บั๊กเดิม)
        code = (await client.get(f"/equipment/{eq_id}", headers=h_admin)).json()["code"]
        r = await client.get("/equipment", params={"search": code, "page_size": 20}, headers=h_admin)
        item = next(i for i in r.json()["items"] if i["id"] == eq_id)
        assert len(item["holders"]) == 2, "ต้องเห็นผู้ยืมครบทั้งสองคน ไม่ใช่แค่คนเดียว"
        names = {h["holder_name"] for h in item["holders"]}
        assert names == {test_student.full_name, student2.full_name}
        quantities = sorted(h["quantity"] for h in item["holders"])
        assert quantities == [3, 5]
        # holder เดี่ยว (ใช้กับ durable/material) ยังต้องมีค่า — เอาคนแรกไปโชว์แบบเดิม ไม่ error/None ทั้งที่มีคนยืม
        assert item["holder"] is not None

        # single-item detail (GET /equipment/{id}) ก็ต้องเห็นครบทั้งสองคน
        detail = (await client.get(f"/equipment/{eq_id}", headers=h_admin)).json()
        assert len(detail["holders"]) == 2

        # grouped detail (หน้าจัดการอุปกรณ์ใช้ตัวนี้ตอนกางดู) ก็ต้องครบเช่นกัน
        grouped = (await client.get(f"/equipment/grouped/{eq_id}", headers=h_admin)).json()
        assert len(grouped["holders"]) == 2
        grouped_names = {h["holder_name"] for h in grouped["holders"]}
        assert grouped_names == {test_student.full_name, student2.full_name}
    finally:
        await _cleanup(eq_id, req_ids, [student2.id])


async def test_durable_single_holder_unaffected_by_list_change(
    client: AsyncClient, admin_token: str, student_token: str, test_student: User,
):
    """ครุภัณฑ์ยืมทีละหน่วยจริง มีคนถือได้แค่คนเดียวต่อแถวอยู่แล้ว — ต้องยังโชว์ holder เดี่ยวถูกต้องเหมือนเดิม
    หลังเปลี่ยน get_holders_map เป็น list ไม่กระทบ"""
    h_admin = auth(admin_token)
    h_student = auth(student_token)
    r = await client.post("/equipment", json={
        "code": f"{uuid.uuid4().int % 10**15:015d}", "name": f"ครุภัณฑ์ทดสอบ holder เดี่ยว {uuid.uuid4().hex[:6]}",
        "category_ids": [], "item_type": "durable", "quantity_total": 1,
        "image_urls": ["/uploads/test.jpg"],
    }, headers=h_admin)
    assert r.status_code == 201, r.text
    eq_id = r.json()["id"]
    req_id = None
    try:
        r = await client.post("/borrow-requests", headers=h_student, json={
            "requested_due_date": "2028-06-01", "items": [{"equipment_id": eq_id, "quantity": 1}],
        })
        assert r.status_code == 201, r.text
        req_id = r.json()["id"]
        assert (await client.patch(f"/borrow-requests/{req_id}/approve", headers=h_admin)).status_code == 200

        detail = (await client.get(f"/equipment/{eq_id}", headers=h_admin)).json()
        assert len(detail["holders"]) == 1
        assert detail["holders"][0]["holder_name"] == test_student.full_name
        assert detail["holders"][0]["student_number"] == test_student.student_id

        # list_equipment (ตารางจัดการอุปกรณ์) ต้องเห็น holder เดี่ยวถูกต้องเหมือนเดิม (durable ยืมทีละหน่วยจริง)
        r = await client.get("/equipment", params={"search": detail["code"], "page_size": 20}, headers=h_admin)
        item = next(i for i in r.json()["items"] if i["id"] == eq_id)
        assert item["holder"]["holder_name"] == test_student.full_name
    finally:
        async with AsyncSessionLocal() as db:
            if req_id:
                await db.execute(delete(Notification).where(Notification.borrow_request_id == uuid.UUID(req_id)))
                await db.execute(delete(BorrowItem).where(BorrowItem.borrow_request_id == uuid.UUID(req_id)))
                await db.execute(delete(BorrowRequest).where(BorrowRequest.id == uuid.UUID(req_id)))
            await db.execute(delete(AuditLog).where(AuditLog.target_id == uuid.UUID(eq_id)))
            await db.execute(delete(Equipment).where(Equipment.id == uuid.UUID(eq_id)))
            await db.commit()
