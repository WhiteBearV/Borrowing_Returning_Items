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


# ── validate จำนวนที่ขอยืม ────────────────────────────────────────────────────

async def test_reject_non_positive_quantity(
    client: AsyncClient, student_token: str, test_equipment: Equipment
):
    """จำนวนติดลบ/ศูนย์ต้องถูกปฏิเสธตั้งแต่ schema และสต็อกต้องไม่ขยับ

    ถ้าปล่อยผ่าน: เช็คสต็อก `available < -5` เป็นเท็จเสมอ แล้วตอนอนุมัติ
    `quantity_available -= -5` จะกลายเป็นเพิ่มสต็อกให้ตัวเอง
    """
    async with AsyncSessionLocal() as db:
        before = (await db.get(Equipment, test_equipment.id)).quantity_available

    for bad in (-5, 0):
        r = await client.post("/borrow-requests", headers=auth(student_token), json={
            "purpose": f"จำนวนไม่ถูกต้อง {bad}",
            "items": [{"equipment_id": str(test_equipment.id), "quantity": bad}],
        })
        assert r.status_code == 422, f"quantity={bad} ต้องถูกปฏิเสธ แต่ได้ {r.status_code}"

    async with AsyncSessionLocal() as db:
        assert (await db.get(Equipment, test_equipment.id)).quantity_available == before


# ── #7 request code ───────────────────────────────────────────────────────────

async def test_request_code_contains_student_id_and_is_running_number(
    client: AsyncClient, student_token: str, test_student: User, test_equipment: Equipment
):
    """เลขคำขอต้อง (1) มี student_id เพื่อระบุตัวผู้ยืม (2) ลงท้ายด้วยเลขรันต่อผู้ใช้
    (นับต่อเนื่อง atomic ผ่าน UPDATE...RETURNING) — อ่านง่ายและยังกัน race ได้"""
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
        assert code.startswith(f"REQ-2026-{test_student.student_id}-"), code
        # suffix = เลขรันไม่ต่ำกว่า 4 หลัก (padding) → พิสูจน์ว่าเป็น running number ไม่ใช่ hex สุ่ม
        suffix = code.rsplit("-", 1)[1]
        assert suffix.isdigit() and len(suffix) >= 4, f"suffix {suffix} ต้องเป็นเลขรัน"
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

async def test_approved_request_exposes_approver_name(
    client: AsyncClient, admin_token: str, student_token: str,
    test_admin: User, test_equipment: Equipment
):
    """หลังอนุมัติ คำขอต้องคืน approver_name (ชื่อผู้อนุมัติ) เพื่อโชว์ในใบยืม —
    ต้อง eager-load relationship approver ไม่งั้น lazy-load ใต้ async จะพัง"""
    req_id = (await client.post("/borrow-requests", headers=auth(student_token), json={
        "purpose": "ทดสอบชื่อผู้อนุมัติ",
        "items": [{"equipment_id": str(test_equipment.id), "quantity": 1}],
    })).json()["id"]
    try:
        assert (await client.patch(f"/borrow-requests/{req_id}/approve",
                                   headers=auth(admin_token))).status_code == 200
        body = (await client.get(f"/borrow-requests/{req_id}", headers=auth(admin_token))).json()
        assert body["approver_name"] == test_admin.full_name, body
    finally:
        await _cleanup_request(req_id, test_equipment.id)


async def test_returned_request_exposes_receiver_name(
    client: AsyncClient, admin_token: str, student_token: str,
    test_admin: User, test_equipment: Equipment
):
    """หลังรับคืน คำขอต้องคืน receiver_name (ชื่อผู้รับคืน) เพื่อโชว์ในใบคืน —
    ต้องรู้ว่า admin คนไหนเป็นคนรับของกลับมา ไม่ใช่แค่คนอนุมัติ"""
    req_id = (await client.post("/borrow-requests", headers=auth(student_token), json={
        "purpose": "ทดสอบชื่อผู้รับคืน",
        "items": [{"equipment_id": str(test_equipment.id), "quantity": 1}],
    })).json()["id"]
    try:
        assert (await client.patch(f"/borrow-requests/{req_id}/approve",
                                   headers=auth(admin_token))).status_code == 200
        body = (await client.get(f"/borrow-requests/{req_id}", headers=auth(admin_token))).json()
        assert body["receiver_name"] is None, "ยังไม่รับคืน ต้องยังไม่มีผู้รับคืน"

        assert (await client.post(f"/borrow-requests/{req_id}/return-all",
                                  headers=auth(admin_token))).status_code == 200
        body = (await client.get(f"/borrow-requests/{req_id}", headers=auth(admin_token))).json()
        assert body["receiver_name"] == test_admin.full_name, body
    finally:
        await _cleanup_request(req_id, test_equipment.id)


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


async def test_equipment_requires_image_on_create_only(
    client: AsyncClient, admin_token: str, test_equipment: Equipment
):
    """อุปกรณ์ใหม่ต้องมีรูปอย่างน้อย 1 (advisor #4) แต่ของเดิมที่ไม่มีรูปต้องยังแก้ไขได้

    ของจากทะเบียน 704 แถวถูก seed มาโดย image_urls = [] ถ้าบังคับตอนแก้ไขด้วยจะแก้ข้อมูลไม่ได้เลย
    """
    h = auth(admin_token)
    suffix = uuid.uuid4().hex[:6]
    body = {"code": f"NOIMG-{suffix}", "name": "อุปกรณ์ไม่มีรูป",
            "category_ids": [], "item_type": "durable", "quantity_total": 1}

    assert (await client.post("/equipment", json=body, headers=h)).status_code == 422
    assert (await client.post("/equipment", json={**body, "image_urls": []}, headers=h)).status_code == 422

    # ของเดิม (fixture สร้างมาโดยไม่มีรูป) ต้องแก้ไขได้ตามปกติ
    async with AsyncSessionLocal() as db:
        assert not (await db.get(Equipment, test_equipment.id)).image_urls
    r = await client.patch(f"/equipment/{test_equipment.id}", json={"location": "ห้อง 15310"}, headers=h)
    assert r.status_code == 200, r.text


async def test_create_and_retire_equipment_write_audit(
    client: AsyncClient, admin_token: str, test_admin: User
):
    """สร้าง/ปลดระวางอุปกรณ์ต้องบันทึก audit ระบุ admin ผู้กระทำ"""
    h = auth(admin_token)
    suffix = uuid.uuid4().hex[:6]
    r = await client.post("/equipment", json={
        "code": f"AUD-{suffix}", "name": "อุปกรณ์ทดสอบ audit",
        "category_ids": [], "item_type": "durable", "quantity_total": 1,
        "image_urls": ["/uploads/test.jpg"],
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


async def test_delete_user_preserves_audit_trail(
    client: AsyncClient, admin_token: str
):
    """ลบ user แล้ว audit log ต้องยังอยู่ (ห้ามลบ audit trail ด้วยการลบบัญชี)

    หลังลบ: actor_id ถูก SET NULL แต่ actor_name/identifier snapshot ยังอยู่ → ยังรู้ว่าใครทำ
    """
    from app.core.security import hash_password  # local เพื่อไม่รบกวน import ส่วนบน

    uid = uuid.uuid4()
    target = uuid.uuid4()  # ใช้ระบุ log ตัวนี้หลัง actor_id ถูก null
    async with AsyncSessionLocal() as db:
        db.add(User(
            id=uid, full_name="ผู้ใช้โยนทิ้ง",
            email=f"tmpdel_{uid.hex[:6]}@cdti.ac.th",
            password_hash=hash_password("Test1234!"),
            role="admin", email_verified=True, is_active=False,  # inactive เพื่อให้ลบได้
        ))
        # audit log ที่อ้าง user นี้ พร้อม snapshot ชื่อ/รหัส (เหมือน log_action จริง)
        db.add(AuditLog(actor_id=uid, actor_name="ผู้ใช้โยนทิ้ง", actor_identifier="STAFF999",
                        action="update_equipment", target_table="equipment",
                        target_id=target, detail={"note": "regression"}))
        await db.commit()

    try:
        # ลบผ่าน API ด้วย admin จริง — ต้องได้ 204 ไม่ใช่ 500 FK error
        assert (await client.delete(f"/users/{uid}", headers=auth(admin_token))).status_code == 204
        async with AsyncSessionLocal() as db:
            assert await db.get(User, uid) is None
            log = (await db.execute(
                select(AuditLog).where(AuditLog.target_id == target)
            )).scalar_one_or_none()
            assert log is not None, "audit log ต้องยังอยู่หลังลบ user"
            assert log.actor_id is None, "actor_id ต้องถูก SET NULL"
            assert log.actor_name == "ผู้ใช้โยนทิ้ง", "snapshot ชื่อผู้ทำต้องยังอยู่"
            assert log.actor_identifier == "STAFF999"
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(AuditLog).where(AuditLog.target_id == target))
            await db.execute(delete(User).where(User.id == uid))
            await db.commit()
