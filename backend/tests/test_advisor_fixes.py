"""Tests สำหรับข้อแก้ตามบันทึกการปรึกษา 30 มิ.ย.
- #7 รูปแบบเลขคำขอยืม (ไม่ชนกัน + ระบุตัวผู้ยืม)
- #8 audit log บันทึกการกระทำของ admin (approve/return/create/update/retire equipment)
"""
import uuid

from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.borrow_item import BorrowItem
from app.models.borrow_request import BorrowRequest
from app.models.equipment import Equipment
from app.models.notification import Notification
from app.models.user import User
from tests.conftest import auth


async def _cleanup_request(req_id: str, eq_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(AuditLog).where(AuditLog.target_id == uuid.UUID(req_id)))
        await db.execute(delete(Notification).where(Notification.borrow_request_id == req_id))
        await db.execute(delete(BorrowItem).where(BorrowItem.borrow_request_id == req_id))
        await db.execute(delete(BorrowRequest).where(BorrowRequest.id == req_id))
        eq = await db.get(Equipment, eq_id)
        if eq:
            eq.quantity_available = eq.quantity_total
            eq.status = "available"
        await db.commit()


# ── #7 request code ───────────────────────────────────────────────────────────

async def test_request_code_contains_student_id_and_is_uuid_derived(
    client: AsyncClient, student_token: str, test_student: User, test_equipment: Equipment
):
    """เลขคำขอต้อง (1) มี student_id เพื่อระบุตัวผู้ยืม (2) suffix มาจาก uuid ของคำขอ
    ทำให้กันชนกันได้เองโดยไม่พึ่ง count+1 (ต้นเหตุ race เดิม)"""
    r = await client.post("/borrow-requests", headers=auth(student_token), json={
        "purpose": "ทดสอบเลขคำขอ",
        "items": [{"equipment_id": str(test_equipment.id), "quantity": 1}],
    })
    assert r.status_code == 201, r.text
    body = r.json()
    req_id = body["id"]
    try:
        code = body["request_code"]
        assert test_student.student_id in code, f"code {code} ต้องมี student_id"
        # suffix = 6 ตัวท้าย ต้องตรงกับ hex ของ id คำขอ → พิสูจน์ว่าไม่ได้มาจาก counter ที่ชนกันได้
        assert code.endswith(uuid.UUID(req_id).hex[:6])
        assert code.startswith("REQ-")
    finally:
        await _cleanup_request(req_id, test_equipment.id)


async def test_two_requests_get_distinct_codes(
    client: AsyncClient, student_token: str, test_equipment: Equipment
):
    """สองคำขอจากคนเดียวกันต้องได้เลขคนละอัน (unique constraint ไม่พัง)"""
    ids, codes = [], []
    try:
        for i in range(2):
            r = await client.post("/borrow-requests", headers=auth(student_token), json={
                "purpose": f"distinct {i}",
                "items": [{"equipment_id": str(test_equipment.id), "quantity": 1}],
            })
            assert r.status_code == 201, r.text
            ids.append(r.json()["id"])
            codes.append(r.json()["request_code"])
        assert codes[0] != codes[1]
    finally:
        for req_id in ids:
            await _cleanup_request(req_id, test_equipment.id)


# ── #8 audit log ──────────────────────────────────────────────────────────────

async def test_approve_writes_audit_log(
    client: AsyncClient, admin_token: str, student_token: str,
    test_admin: User, test_equipment: Equipment
):
    """อนุมัติคำขอต้องบันทึก audit log ระบุ admin ผู้อนุมัติ"""
    req_id = (await client.post("/borrow-requests", headers=auth(student_token), json={
        "purpose": "ทดสอบ audit approve",
        "items": [{"equipment_id": str(test_equipment.id), "quantity": 1}],
    })).json()["id"]
    try:
        r = await client.patch(f"/borrow-requests/{req_id}/approve", headers=auth(admin_token))
        assert r.status_code == 200, r.text

        async with AsyncSessionLocal() as db:
            log = (await db.execute(
                select(AuditLog).where(
                    AuditLog.action == "approve_request",
                    AuditLog.target_id == uuid.UUID(req_id),
                )
            )).scalar_one_or_none()
        assert log is not None, "ต้องมี audit log หลังอนุมัติ"
        assert log.actor_id == test_admin.id
        assert log.target_table == "borrow_requests"
    finally:
        await _cleanup_request(req_id, test_equipment.id)


async def test_audit_log_visible_via_api_and_admin_only(
    client: AsyncClient, admin_token: str, student_token: str,
    test_admin: User, test_equipment: Equipment
):
    """audit log ที่เขียนแล้วต้องดึงผ่าน API ได้ (ไม่ใช่ตารางว่างเหมือนเดิม) และ student เข้าไม่ได้"""
    req_id = (await client.post("/borrow-requests", headers=auth(student_token), json={
        "purpose": "ทดสอบ audit api",
        "items": [{"equipment_id": str(test_equipment.id), "quantity": 1}],
    })).json()["id"]
    try:
        await client.patch(f"/borrow-requests/{req_id}/approve", headers=auth(admin_token))

        # student ห้ามดู audit log
        assert (await client.get("/audit-logs", headers=auth(student_token))).status_code == 403

        r = await client.get("/audit-logs", params={"action": "approve_request"}, headers=auth(admin_token))
        assert r.status_code == 200
        row = next((i for i in r.json()["items"] if i["target_id"] == req_id), None)
        assert row is not None
        # ต้องรู้ว่า "ใคร" เป็นคนทำ ไม่ใช่แค่ UUID
        assert row["actor_name"] == test_admin.full_name
        assert row["actor_id"] == str(test_admin.id)
    finally:
        await _cleanup_request(req_id, test_equipment.id)


async def test_create_and_retire_equipment_write_audit(
    client: AsyncClient, admin_token: str, test_admin: User
):
    """สร้าง/ปลดระวางอุปกรณ์ต้องบันทึก audit ระบุ admin ผู้กระทำ"""
    h = auth(admin_token)
    suffix = uuid.uuid4().hex[:6]
    r = await client.post("/equipment", json={
        "code": f"AUD-{suffix}", "name": "อุปกรณ์ทดสอบ audit",
        "category_ids": [], "item_type": "durable", "quantity_total": 1,
    }, headers=h)
    assert r.status_code == 201, r.text
    eq_id = r.json()["id"]
    try:
        # ปลดระวาง
        assert (await client.delete(f"/equipment/{eq_id}", headers=h)).status_code == 204

        async with AsyncSessionLocal() as db:
            actions = (await db.execute(
                select(AuditLog.action).where(AuditLog.target_id == uuid.UUID(eq_id))
            )).scalars().all()
        assert "create_equipment" in actions
        assert "retire_equipment" in actions
        async with AsyncSessionLocal() as db:
            log = (await db.execute(
                select(AuditLog).where(AuditLog.target_id == uuid.UUID(eq_id)).limit(1)
            )).scalar_one()
            assert log.actor_id == test_admin.id
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(AuditLog).where(AuditLog.target_id == uuid.UUID(eq_id)))
            await db.execute(delete(Equipment).where(Equipment.id == uuid.UUID(eq_id)))
            await db.commit()


async def test_delete_user_with_audit_logs_does_not_break_fk(
    client: AsyncClient, admin_token: str
):
    """ลบ user ที่มี audit log อ้างอยู่ต้องไม่ติด FK (regression: audit ทำงานแล้ว actor_id ถูกอ้าง)

    ใช้ user โยนทิ้งที่ใส่ audit log ตรงๆ ไม่ต้องสร้าง admin ใหม่
    """
    from app.core.security import hash_password  # local เพื่อไม่รบกวน import ส่วนบน

    uid = uuid.uuid4()
    async with AsyncSessionLocal() as db:
        db.add(User(
            id=uid, full_name="ผู้ใช้โยนทิ้ง",
            email=f"tmpdel_{uid.hex[:6]}@cdti.ac.th",
            password_hash=hash_password("Test1234!"),
            role="admin", email_verified=True, is_active=False,  # inactive เพื่อให้ลบได้
        ))
        # จำลอง audit log ที่อ้าง user นี้เป็น actor
        db.add(AuditLog(actor_id=uid, action="update_equipment", target_table="equipment",
                        target_id=uuid.uuid4(), detail={"note": "regression"}))
        await db.commit()

    try:
        # ลบผ่าน API ด้วย admin จริง — ต้องได้ 204 ไม่ใช่ 500 FK error
        assert (await client.delete(f"/users/{uid}", headers=auth(admin_token))).status_code == 204
        async with AsyncSessionLocal() as db:
            assert await db.get(User, uid) is None
            assert (await db.execute(
                select(AuditLog).where(AuditLog.actor_id == uid)
            )).scalar_one_or_none() is None
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(AuditLog).where(AuditLog.actor_id == uid))
            await db.execute(delete(User).where(User.id == uid))
            await db.commit()
