"""นักศึกษาแจ้งขอคืนอุปกรณ์เอง (request_return_items) — แค่ตั้ง flag แจ้ง admin

การคืนจริง (returned/quantity_available) ยังต้องผ่าน return_item/return_all_items (admin only)
เหมือนเดิมทุกประการ — เทสชุดนี้เช็คว่า flag ทำงานถูก ไม่ใช่เช็คกลไกคืนจริงซ้ำ (มีเทสอยู่แล้วที่อื่น)

MAIL_USERNAME ใน .env test เป็น placeholder → send_email() แค่ print แทนส่งจริง จึงตรวจผลจาก stdout ผ่าน capsys
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
from app.models.equipment_category import EquipmentCategory
from app.models.notification import Notification
from app.models.user import User
from tests.conftest import auth


async def _cleanup_request(req_id: str, eq_ids: list[uuid.UUID]) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(AuditLog).where(AuditLog.target_id == uuid.UUID(req_id)))
        await db.execute(delete(Notification).where(Notification.borrow_request_id == req_id))
        await db.execute(delete(BorrowItem).where(BorrowItem.borrow_request_id == req_id))
        await db.execute(delete(BorrowRequest).where(BorrowRequest.id == req_id))
        for eq_id in eq_ids:
            eq = await db.get(Equipment, eq_id)
            if eq:
                eq.quantity_available = eq.quantity_total
                eq.status = "available"
        await db.commit()


async def _create_request(client: AsyncClient, student_token: str, equipment_ids: list[uuid.UUID], purpose: str) -> dict:
    r = await client.post("/borrow-requests", headers=auth(student_token), json={
        "purpose": purpose,
        "requested_due_date": "2099-01-01", "items": [{"equipment_id": str(eid), "quantity": 1} for eid in equipment_ids],
    })
    assert r.status_code == 201, r.text
    return r.json()


async def test_student_can_request_return_single_item(
    client: AsyncClient, capsys, student_token: str, admin_token: str,
    test_admin: User, test_equipment: Equipment,
):
    req = await _create_request(client, student_token, [test_equipment.id], "ทดสอบแจ้งขอคืน 1 ชิ้น")
    assert (await client.patch(f"/borrow-requests/{req['id']}/approve", headers=auth(admin_token))).status_code == 200
    item_id = req["items"][0]["id"]
    capsys.readouterr()  # ล้าง output จากอีเมลตอนสร้างคำขอ/อนุมัติ

    r = await client.post(f"/borrow-requests/{req['id']}/request-return",
                          headers=auth(student_token), json={"item_ids": [item_id]})
    assert r.status_code == 200

    body = (await client.get(f"/borrow-requests/{req['id']}", headers=auth(student_token))).json()
    item = body["items"][0]
    assert item["return_requested"] is True
    assert item["return_requested_at"] is not None

    out = capsys.readouterr().out
    assert f"[DEV EMAIL] To: {test_admin.email}" in out
    assert req["request_code"] in out

    await _cleanup_request(req["id"], [test_equipment.id])


async def test_student_can_request_return_multiple_items_in_one_call(
    client: AsyncClient, capsys, student_token: str, admin_token: str,
    test_admin: User, test_equipment: Equipment, test_category: EquipmentCategory,
):
    eq2_id = uuid.uuid4()
    async with AsyncSessionLocal() as db:
        cat = await db.get(EquipmentCategory, test_category.id)
        db.add(Equipment(
            id=eq2_id, code=f"TEST-{eq2_id.hex[:6].upper()}", name="อุปกรณ์ทดสอบชิ้นที่ 2",
            categories=[cat], item_type="durable", quantity_total=5, quantity_available=5, status="available",
        ))
        await db.commit()

    req = await _create_request(client, student_token, [test_equipment.id, eq2_id], "ทดสอบแจ้งขอคืนหลายชิ้น")
    assert (await client.patch(f"/borrow-requests/{req['id']}/approve", headers=auth(admin_token))).status_code == 200
    item_ids = [i["id"] for i in req["items"]]
    assert len(item_ids) == 2
    capsys.readouterr()

    r = await client.post(f"/borrow-requests/{req['id']}/request-return",
                          headers=auth(student_token), json={"item_ids": item_ids})
    assert r.status_code == 200

    body = (await client.get(f"/borrow-requests/{req['id']}", headers=auth(student_token))).json()
    assert all(i["return_requested"] for i in body["items"])

    out = capsys.readouterr().out
    # แจ้งครั้งเดียวรวม 2 รายการ ไม่ใช่แจ้งแยกทีละชิ้น (นับจำนวนบรรทัด [DEV EMAIL] ที่ถึง admin คนนี้)
    assert out.count(f"[DEV EMAIL] To: {test_admin.email}") == 1
    assert "2 รายการ" in out

    await _cleanup_request(req["id"], [test_equipment.id, eq2_id])
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Equipment).where(Equipment.id == eq2_id))
        await db.commit()


async def test_non_owner_cannot_request_return(
    client: AsyncClient, student_token: str, admin_token: str, test_equipment: Equipment,
):
    req = await _create_request(client, student_token, [test_equipment.id], "ทดสอบเจ้าของคำขอ")
    assert (await client.patch(f"/borrow-requests/{req['id']}/approve", headers=auth(admin_token))).status_code == 200
    item_id = req["items"][0]["id"]

    other_id = uuid.uuid4()
    async with AsyncSessionLocal() as db:
        db.add(User(
            id=other_id, full_name="นักศึกษาอีกคน",
            email=f"other_{other_id.hex[:6]}@cdti.ac.th",
            password_hash=hash_password("Test1234!"),
            role="student", email_verified=True, is_active=True,
        ))
        await db.commit()
    other_token = create_access_token(str(other_id), extra={"role": "student"})

    r = await client.post(f"/borrow-requests/{req['id']}/request-return",
                          headers=auth(other_token), json={"item_ids": [item_id]})
    assert r.status_code == 403

    await _cleanup_request(req["id"], [test_equipment.id])
    async with AsyncSessionLocal() as db:
        await db.execute(delete(User).where(User.id == other_id))
        await db.commit()


async def test_cannot_request_return_before_approved(
    client: AsyncClient, student_token: str, test_equipment: Equipment,
):
    req = await _create_request(client, student_token, [test_equipment.id], "ทดสอบยังไม่อนุมัติ")
    item_id = req["items"][0]["id"]

    r = await client.post(f"/borrow-requests/{req['id']}/request-return",
                          headers=auth(student_token), json={"item_ids": [item_id]})
    assert r.status_code == 400

    await _cleanup_request(req["id"], [test_equipment.id])


async def test_cannot_request_return_already_returned_item(
    client: AsyncClient, student_token: str, admin_token: str, test_equipment: Equipment,
):
    req = await _create_request(client, student_token, [test_equipment.id], "ทดสอบคืนไปแล้ว")
    assert (await client.patch(f"/borrow-requests/{req['id']}/approve", headers=auth(admin_token))).status_code == 200
    item_id = req["items"][0]["id"]

    assert (await client.post(
        f"/borrow-requests/{req['id']}/items/{item_id}/return",
        headers=auth(admin_token), json={"condition_on_return": "ok"},
    )).status_code == 200

    r = await client.post(f"/borrow-requests/{req['id']}/request-return",
                          headers=auth(student_token), json={"item_ids": [item_id]})
    assert r.status_code == 400

    await _cleanup_request(req["id"], [test_equipment.id])


async def test_return_requested_flag_cleared_after_real_return(
    client: AsyncClient, student_token: str, admin_token: str, test_equipment: Equipment,
):
    req = await _create_request(client, student_token, [test_equipment.id], "ทดสอบเคลียร์ flag")
    assert (await client.patch(f"/borrow-requests/{req['id']}/approve", headers=auth(admin_token))).status_code == 200
    item_id = req["items"][0]["id"]

    assert (await client.post(f"/borrow-requests/{req['id']}/request-return",
                              headers=auth(student_token), json={"item_ids": [item_id]})).status_code == 200

    assert (await client.post(
        f"/borrow-requests/{req['id']}/items/{item_id}/return",
        headers=auth(admin_token), json={"condition_on_return": "ok"},
    )).status_code == 200

    body = (await client.get(f"/borrow-requests/{req['id']}", headers=auth(admin_token))).json()
    item = body["items"][0]
    assert item["returned"] is True
    assert item["return_requested"] is False
    assert item["return_requested_at"] is None

    await _cleanup_request(req["id"], [test_equipment.id])
