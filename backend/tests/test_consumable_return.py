"""Test flow วัสดุสิ้นเปลือง 3 สถานะ (#3) + บังคับรูปความเสียหาย (#1)"""
import uuid

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.borrow_item import BorrowItem
from app.models.borrow_request import BorrowRequest
from app.models.equipment import Equipment
from app.models.notification import Notification
from tests.conftest import auth


@pytest_asyncio.fixture(loop_scope="session")
async def consumable_eq():
    eq_id = uuid.uuid4()
    async with AsyncSessionLocal() as db:
        eq = Equipment(
            id=eq_id, code=f"CONS-{eq_id.hex[:6].upper()}", name="สายไฟทดสอบ",
            item_type="consumable", unit="เมตร",
            quantity_total=10, quantity_available=10, status="available",
        )
        db.add(eq)
        await db.commit()
    yield eq_id
    async with AsyncSessionLocal() as db:
        await db.execute(delete(BorrowItem).where(BorrowItem.equipment_id == eq_id))
        await db.execute(delete(Equipment).where(Equipment.id == eq_id))
        await db.commit()


async def _make_approved(client, student_token, admin_token, eq_id, qty=2):
    """สร้างคำขอวัสดุ + อนุมัติ คืน (req_id, item_id)"""
    r = await client.post("/borrow-requests", headers=auth(student_token), json={
        "purpose": "ทดสอบวัสดุ", "requested_due_date": "2028-06-01", "items": [{"equipment_id": str(eq_id), "quantity": qty}],
    })
    req = r.json()
    await client.patch(f"/borrow-requests/{req['id']}/approve", headers=auth(admin_token))
    return req["id"], req["items"][0]["id"]


async def _cleanup(req_id, eq_id):
    async with AsyncSessionLocal() as db:
        await db.execute(delete(AuditLog).where(AuditLog.target_id == uuid.UUID(req_id)))
        await db.execute(delete(Notification).where(Notification.borrow_request_id == req_id))
        await db.execute(delete(BorrowItem).where(BorrowItem.borrow_request_id == req_id))
        await db.execute(delete(BorrowRequest).where(BorrowRequest.id == req_id))
        eq = await db.get(Equipment, eq_id)
        eq.quantity_available = eq.quantity_total
        await db.commit()


async def test_approve_consumable_not_auto_returned(
    client: AsyncClient, student_token: str, admin_token: str, consumable_eq
):
    """อนุมัติวัสดุ: ต้องยังไม่ 'คืนแล้ว' (returned=False) และหักสต็อกแล้ว — bug เดิมขึ้นคืนแล้วทันที"""
    req_id, item_id = await _make_approved(client, student_token, admin_token, consumable_eq)
    try:
        r = await client.get(f"/borrow-requests/{req_id}", headers=auth(admin_token))
        item = r.json()["items"][0]
        assert item["returned"] is False, "วัสดุต้องยังไม่ถูก mark คืนตอนอนุมัติ"
        async with AsyncSessionLocal() as db:
            eq = await db.get(Equipment, consumable_eq)
            assert eq.quantity_available == 8  # 10 - 2
    finally:
        await _cleanup(req_id, consumable_eq)


async def test_consumable_used_up_keeps_stock_deducted(
    client: AsyncClient, student_token: str, admin_token: str, consumable_eq
):
    req_id, item_id = await _make_approved(client, student_token, admin_token, consumable_eq)
    try:
        r = await client.post(f"/borrow-requests/{req_id}/items/{item_id}/return",
                              headers=auth(admin_token), json={"condition_on_return": "used_up"})
        assert r.status_code == 200, r.text
        async with AsyncSessionLocal() as db:
            eq = await db.get(Equipment, consumable_eq)
            assert eq.quantity_available == 8, "ใช้หมด → สต็อกไม่คืน"
        # settle ครบ → completed
        assert (await client.get(f"/borrow-requests/{req_id}", headers=auth(admin_token))).json()["status"] == "completed"
    finally:
        await _cleanup(req_id, consumable_eq)


async def test_consumable_returned_full_restores_stock(
    client: AsyncClient, student_token: str, admin_token: str, consumable_eq
):
    req_id, item_id = await _make_approved(client, student_token, admin_token, consumable_eq)
    try:
        r = await client.post(f"/borrow-requests/{req_id}/items/{item_id}/return",
                              headers=auth(admin_token), json={"condition_on_return": "returned_full"})
        assert r.status_code == 200, r.text
        async with AsyncSessionLocal() as db:
            eq = await db.get(Equipment, consumable_eq)
            assert eq.quantity_available == 10, "คืนครบ → สต็อกกลับเต็ม"
    finally:
        await _cleanup(req_id, consumable_eq)


async def test_consumable_discarded_requires_photo(
    client: AsyncClient, student_token: str, admin_token: str, consumable_eq
):
    req_id, item_id = await _make_approved(client, student_token, admin_token, consumable_eq)
    try:
        # ไม่มีรูป → 400
        r = await client.post(f"/borrow-requests/{req_id}/items/{item_id}/return",
                              headers=auth(admin_token), json={"condition_on_return": "discarded"})
        assert r.status_code == 400
        # มีรูป → 200, สต็อกไม่คืน
        r = await client.post(f"/borrow-requests/{req_id}/items/{item_id}/return",
                              headers=auth(admin_token),
                              json={"condition_on_return": "discarded",
                                    "damage_photo_urls": ["/uploads/x.png"], "damage_note": "ไหม้"})
        assert r.status_code == 200, r.text
        async with AsyncSessionLocal() as db:
            eq = await db.get(Equipment, consumable_eq)
            assert eq.quantity_available == 8
    finally:
        await _cleanup(req_id, consumable_eq)


async def test_consumable_rejects_durable_condition(
    client: AsyncClient, student_token: str, admin_token: str, consumable_eq
):
    """วัสดุห้ามใช้สถานะของครุภัณฑ์ (ok/damaged/lost)"""
    req_id, item_id = await _make_approved(client, student_token, admin_token, consumable_eq)
    try:
        r = await client.post(f"/borrow-requests/{req_id}/items/{item_id}/return",
                              headers=auth(admin_token), json={"condition_on_return": "ok"})
        assert r.status_code == 400
    finally:
        await _cleanup(req_id, consumable_eq)


async def test_durable_damaged_requires_photo(
    client: AsyncClient, student_token: str, admin_token: str, test_equipment
):
    """ครุภัณฑ์เสียหายต้องแนบรูป (#1)"""
    r = await client.post("/borrow-requests", headers=auth(student_token), json={
        "purpose": "ทดสอบรูปเสียหาย", "requested_due_date": "2028-06-01", "items": [{"equipment_id": str(test_equipment.id), "quantity": 1}],
    })
    req_id = r.json()["id"]
    item_id = r.json()["items"][0]["id"]
    await client.patch(f"/borrow-requests/{req_id}/approve", headers=auth(admin_token))
    try:
        # damaged ไม่มีรูป → 400
        r = await client.post(f"/borrow-requests/{req_id}/items/{item_id}/return",
                              headers=auth(admin_token), json={"condition_on_return": "damaged"})
        assert r.status_code == 400
        # มีรูป → 200
        r = await client.post(f"/borrow-requests/{req_id}/items/{item_id}/return",
                              headers=auth(admin_token),
                              json={"condition_on_return": "damaged", "damage_photo_urls": ["/uploads/d.png"]})
        assert r.status_code == 200, r.text
        item = (await client.get(f"/borrow-requests/{req_id}", headers=auth(admin_token))).json()["items"][0]
        assert item["damage_photo_urls"] == ["/uploads/d.png"]
    finally:
        await _cleanup(req_id, test_equipment.id)
