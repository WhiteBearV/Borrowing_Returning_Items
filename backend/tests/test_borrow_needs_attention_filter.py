"""Tests: needs_attention filter รวม pending + approved ที่มี item แจ้งขอคืน (Phase B feature 4)

หน้า "อนุมัติคำขอ" ของ admin ต้องเห็นทั้งคำขอใหม่รออนุมัติ และคำขอที่นักศึกษาแจ้งขอคืนในหน้าเดียว
ไม่ต้องสลับไปหน้า "ประวัติทั้งหมด" แยกต่างหาก
"""
import uuid

from httpx import AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.borrow_item import BorrowItem
from app.models.borrow_request import BorrowRequest
from app.models.equipment import Equipment
from app.models.notification import Notification
from tests.conftest import auth


async def _make_equipment(client: AsyncClient, admin_header: dict) -> str:
    suffix = uuid.uuid4().hex[:6].upper()
    r = await client.post("/equipment", json={
        "code": f"NEEDS-{suffix}", "name": f"อุปกรณ์ทดสอบ needs_attention {suffix}",
        "category_ids": [], "item_type": "durable", "quantity_total": 1,
        "image_urls": ["/uploads/test.jpg"],
    }, headers=admin_header)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _make_request(client: AsyncClient, student_header: dict, eq_id: str) -> str:
    r = await client.post("/borrow-requests", headers=student_header, json={
        "requested_due_date": "2028-06-01",
        "items": [{"equipment_id": eq_id, "quantity": 1}],
    })
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _cleanup(eq_id: str, req_id: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Notification).where(Notification.borrow_request_id == uuid.UUID(req_id)))
        await db.execute(delete(BorrowItem).where(BorrowItem.borrow_request_id == uuid.UUID(req_id)))
        await db.execute(delete(BorrowRequest).where(BorrowRequest.id == uuid.UUID(req_id)))
        await db.execute(delete(AuditLog).where(AuditLog.target_id == uuid.UUID(eq_id)))
        await db.execute(delete(Equipment).where(Equipment.id == uuid.UUID(eq_id)))
        await db.commit()


async def _needs_attention_ids(client: AsyncClient, admin_header: dict) -> set[str]:
    r = await client.get("/borrow-requests", params={"needs_attention": "true", "page_size": 100}, headers=admin_header)
    assert r.status_code == 200, r.text
    return {item["id"] for item in r.json()["items"]}


async def test_needs_attention_includes_pending(client: AsyncClient, admin_token: str, student_token: str):
    h_admin = auth(admin_token)
    eq_id = await _make_equipment(client, h_admin)
    req_id = await _make_request(client, auth(student_token), eq_id)
    try:
        assert req_id in await _needs_attention_ids(client, h_admin)
    finally:
        await _cleanup(eq_id, req_id)


async def test_needs_attention_includes_approved_with_return_requested(
    client: AsyncClient, admin_token: str, student_token: str
):
    h_admin = auth(admin_token)
    h_student = auth(student_token)
    eq_id = await _make_equipment(client, h_admin)
    req_id = await _make_request(client, h_student, eq_id)
    try:
        assert (await client.patch(f"/borrow-requests/{req_id}/approve", headers=h_admin)).status_code == 200
        item_id = (await client.get(f"/borrow-requests/{req_id}", headers=h_admin)).json()["items"][0]["id"]
        r = await client.post(f"/borrow-requests/{req_id}/request-return",
                               headers=h_student, json={"item_ids": [item_id]})
        assert r.status_code == 200, r.text

        assert req_id in await _needs_attention_ids(client, h_admin)
    finally:
        await _cleanup(eq_id, req_id)


async def test_needs_attention_excludes_approved_without_return_requested(
    client: AsyncClient, admin_token: str, student_token: str
):
    h_admin = auth(admin_token)
    h_student = auth(student_token)
    eq_id = await _make_equipment(client, h_admin)
    req_id = await _make_request(client, h_student, eq_id)
    try:
        assert (await client.patch(f"/borrow-requests/{req_id}/approve", headers=h_admin)).status_code == 200
        assert req_id not in await _needs_attention_ids(client, h_admin)
    finally:
        await _cleanup(eq_id, req_id)


async def test_needs_attention_drops_after_return_confirmed(
    client: AsyncClient, admin_token: str, student_token: str
):
    h_admin = auth(admin_token)
    h_student = auth(student_token)
    eq_id = await _make_equipment(client, h_admin)
    req_id = await _make_request(client, h_student, eq_id)
    try:
        assert (await client.patch(f"/borrow-requests/{req_id}/approve", headers=h_admin)).status_code == 200
        item_id = (await client.get(f"/borrow-requests/{req_id}", headers=h_admin)).json()["items"][0]["id"]
        assert (await client.post(f"/borrow-requests/{req_id}/request-return",
                                   headers=h_student, json={"item_ids": [item_id]})).status_code == 200
        assert req_id in await _needs_attention_ids(client, h_admin)

        r = await client.post(
            f"/borrow-requests/{req_id}/items/{item_id}/return",
            json={"condition_on_return": "ok"}, headers=h_admin,
        )
        assert r.status_code == 200, r.text

        assert req_id not in await _needs_attention_ids(client, h_admin)
    finally:
        await _cleanup(eq_id, req_id)
