"""Tests: ลบบัญชีผู้ใช้ (admin only, ต้องปิดใช้งานก่อน)

บั๊กที่เจอจริง: admin ที่เคย approve/รับคืนคำขอของ student คนอื่นไว้ ลบบัญชีไม่ได้ ชน FK
borrow_requests_approved_by_fkey/returned_by_fkey กลายเป็น 500 — เจอจากบัญชีทดสอบค้างจริงในคลัง
(เศษจาก pytest run เก่าที่ teardown ล้มเหลว) ที่ไม่มีปุ่มลบใน UI แต่ backend endpoint พังตอนเรียกตรง
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


async def _make_user(role: str) -> User:
    uid = uuid.uuid4()
    async with AsyncSessionLocal() as db:
        user = User(
            id=uid, full_name=f"ทดสอบลบบัญชี {role}",
            email=f"deltest_{uid.hex[:6]}@cdti.ac.th",
            password_hash=hash_password("Test1234!"),
            role=role, student_id=f"65{uid.hex[:8]}" if role == "student" else None,
            email_verified=True, is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return user


async def _cleanup_equipment(eq_id: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(BorrowItem).where(BorrowItem.equipment_id == uuid.UUID(eq_id)))
        await db.execute(delete(AuditLog).where(AuditLog.target_id == uuid.UUID(eq_id)))
        await db.execute(delete(Equipment).where(Equipment.id == uuid.UUID(eq_id)))
        await db.commit()


async def test_delete_admin_who_approved_other_students_request(client: AsyncClient, admin_token: str):
    """admin ที่เคย approve คำขอของ student คนอื่น (ไม่ใช่บัญชีตัวเอง) ต้องลบได้ ไม่ใช่ 500"""
    h_admin = auth(admin_token)
    throwaway_admin = await _make_user("admin")
    throwaway_student = await _make_user("student")
    student_token = create_access_token(str(throwaway_student.id), extra={"role": "student"})
    h_throwaway_admin = auth(create_access_token(str(throwaway_admin.id), extra={"role": "admin"}))
    h_student = auth(student_token)

    eq_id = None
    req_id = None
    try:
        r = await client.post("/equipment", json={
            "code": f"DELUSR-{uuid.uuid4().hex[:6].upper()}", "name": "อุปกรณ์ทดสอบลบบัญชี",
            "category_ids": [], "item_type": "durable", "quantity_total": 1,
            "image_urls": ["/uploads/test.jpg"],
        }, headers=h_admin)
        assert r.status_code == 201, r.text
        eq_id = r.json()["id"]

        r = await client.post("/borrow-requests", headers=h_student, json={
            "requested_due_date": "2028-06-01",
            "items": [{"equipment_id": eq_id, "quantity": 1}],
        })
        assert r.status_code == 201, r.text
        req_id = r.json()["id"]

        # throwaway_admin เป็นคนอนุมัติและรับคืน — ทำให้เป็น approved_by/returned_by ของคำขอ student คนอื่น
        assert (await client.patch(f"/borrow-requests/{req_id}/approve", headers=h_throwaway_admin)).status_code == 200
        item_id = (await client.get(f"/borrow-requests/{req_id}", headers=h_admin)).json()["items"][0]["id"]
        assert (await client.post(
            f"/borrow-requests/{req_id}/items/{item_id}/return",
            json={"condition_on_return": "ok"}, headers=h_throwaway_admin,
        )).status_code == 200

        # ลบ throwaway_student ก่อน (เจ้าของคำขอ) กันชน FK จากอีกทาง แล้วค่อยลบ admin ที่อนุมัติ/รับคืน
        assert (await client.patch(f"/users/{throwaway_student.id}/status", json={"is_active": False}, headers=h_admin)).status_code == 200
        assert (await client.delete(f"/users/{throwaway_student.id}", headers=h_admin)).status_code == 204
        req_id = None  # cascade ลบคำขอไปพร้อมกับ student แล้ว ไม่ต้อง cleanup ซ้ำ

        assert (await client.patch(f"/users/{throwaway_admin.id}/status", json={"is_active": False}, headers=h_admin)).status_code == 200
        r = await client.delete(f"/users/{throwaway_admin.id}", headers=h_admin)
        assert r.status_code == 204, r.text
    finally:
        if req_id:
            async with AsyncSessionLocal() as db:
                await db.execute(delete(Notification).where(Notification.borrow_request_id == uuid.UUID(req_id)))
                await db.execute(delete(BorrowItem).where(BorrowItem.borrow_request_id == uuid.UUID(req_id)))
                await db.execute(delete(BorrowRequest).where(BorrowRequest.id == uuid.UUID(req_id)))
                await db.commit()
        if eq_id:
            await _cleanup_equipment(eq_id)


async def test_delete_user_requires_deactivation_first(client: AsyncClient, admin_token: str):
    h_admin = auth(admin_token)
    throwaway = await _make_user("student")
    try:
        r = await client.delete(f"/users/{throwaway.id}", headers=h_admin)
        assert r.status_code == 400
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(User).where(User.id == throwaway.id))
            await db.commit()


async def test_delete_user_forbidden_for_student(client: AsyncClient, student_token: str, admin_token: str):
    h_admin = auth(admin_token)
    throwaway = await _make_user("student")
    try:
        r = await client.delete(f"/users/{throwaway.id}", headers=auth(student_token))
        assert r.status_code == 403
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(User).where(User.id == throwaway.id))
            await db.commit()
