"""ต่อเวลาแบบขออนุมัติ — นักศึกษาขอ (วันที่+เหตุผล) แล้ว admin อนุมัติ/ปฏิเสธ ไม่ต่อทันทีเหมือนเดิม

หมายเหตุ: conftest.py มี PYTEST_ALLOW_DB=1 รันใส่ DB dev จริง — ทุกเทสต้อง cleanup ใน finally เสมอ
"""
import uuid
from datetime import date, timedelta

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
        "code": f"{uuid.uuid4().int % 10**15:015d}", "name": f"อุปกรณ์ทดสอบต่อเวลา {suffix}",
        "category_ids": [], "item_type": "durable", "quantity_total": 1,
        "image_urls": ["/uploads/test.jpg"],
    }, headers=admin_header)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _make_approved_request(client: AsyncClient, admin_header: dict, student_header: dict, eq_id: str) -> tuple[str, str]:
    r = await client.post("/borrow-requests", headers=student_header, json={
        "requested_due_date": "2028-06-01",
        "items": [{"equipment_id": eq_id, "quantity": 1}],
    })
    assert r.status_code == 201, r.text
    req_id = r.json()["id"]
    assert (await client.patch(f"/borrow-requests/{req_id}/approve", headers=admin_header)).status_code == 200
    item_id = (await client.get(f"/borrow-requests/{req_id}", headers=admin_header)).json()["items"][0]["id"]
    return req_id, item_id


async def _cleanup(eq_id: str, req_id: str, item_id: str | None = None) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Notification).where(Notification.borrow_request_id == uuid.UUID(req_id)))
        if item_id:
            await db.execute(delete(AuditLog).where(AuditLog.target_id == uuid.UUID(item_id)))
        await db.execute(delete(BorrowItem).where(BorrowItem.borrow_request_id == uuid.UUID(req_id)))
        await db.execute(delete(BorrowRequest).where(BorrowRequest.id == uuid.UUID(req_id)))
        await db.execute(delete(AuditLog).where(AuditLog.target_id == uuid.UUID(eq_id)))
        await db.execute(delete(Equipment).where(Equipment.id == uuid.UUID(eq_id)))
        await db.commit()


async def test_renew_request_then_approve_extends_due_date(client: AsyncClient, admin_token: str, student_token: str):
    h_admin, h_student = auth(admin_token), auth(student_token)
    eq_id = await _make_equipment(client, h_admin)
    req_id, item_id = await _make_approved_request(client, h_admin, h_student, eq_id)
    try:
        new_date = (date.today() + timedelta(days=5)).isoformat()
        r = await client.post(
            f"/borrow-requests/{req_id}/items/{item_id}/renew-request",
            json={"requested_date": new_date, "reason": "งานยังไม่เสร็จ"}, headers=h_student,
        )
        assert r.status_code == 200, r.text

        # ยื่นคำขอแล้วยังไม่ต่อจริง — renewed_count ต้องยังเป็น 0
        item = (await client.get(f"/borrow-requests/{req_id}", headers=h_admin)).json()["items"][0]
        assert item["renew_requested"] is True
        assert item["renewed_count"] == 0
        assert item["extended_due_date"] is None

        r = await client.post(f"/borrow-requests/{req_id}/items/{item_id}/renew-approve", headers=h_admin)
        assert r.status_code == 200, r.text

        item = (await client.get(f"/borrow-requests/{req_id}", headers=h_admin)).json()["items"][0]
        assert item["renew_requested"] is False
        assert item["renewed_count"] == 1
        assert item["extended_due_date"] == new_date
    finally:
        await _cleanup(eq_id, req_id, item_id)


async def test_renew_reject_does_not_change_renewed_count(client: AsyncClient, admin_token: str, student_token: str):
    h_admin, h_student = auth(admin_token), auth(student_token)
    eq_id = await _make_equipment(client, h_admin)
    req_id, item_id = await _make_approved_request(client, h_admin, h_student, eq_id)
    try:
        new_date = (date.today() + timedelta(days=3)).isoformat()
        assert (await client.post(
            f"/borrow-requests/{req_id}/items/{item_id}/renew-request",
            json={"requested_date": new_date, "reason": "ขอลองปฏิเสธ"}, headers=h_student,
        )).status_code == 200

        r = await client.post(
            f"/borrow-requests/{req_id}/items/{item_id}/renew-reject",
            json={"rejection_reason": "ของต้องใช้ต่อ"}, headers=h_admin,
        )
        assert r.status_code == 200, r.text

        item = (await client.get(f"/borrow-requests/{req_id}", headers=h_admin)).json()["items"][0]
        assert item["renew_requested"] is False
        assert item["renewed_count"] == 0
        assert item["extended_due_date"] is None
        assert item["renew_rejected_reason"] == "ของต้องใช้ต่อ"
    finally:
        await _cleanup(eq_id, req_id, item_id)


async def test_renew_request_rejects_past_date(client: AsyncClient, admin_token: str, student_token: str):
    h_admin, h_student = auth(admin_token), auth(student_token)
    eq_id = await _make_equipment(client, h_admin)
    req_id, item_id = await _make_approved_request(client, h_admin, h_student, eq_id)
    try:
        past_date = (date.today() - timedelta(days=1)).isoformat()
        r = await client.post(
            f"/borrow-requests/{req_id}/items/{item_id}/renew-request",
            json={"requested_date": past_date, "reason": "ย้อนหลัง"}, headers=h_student,
        )
        assert r.status_code == 400
    finally:
        await _cleanup(eq_id, req_id, item_id)


async def test_renew_request_rejects_too_far_ahead(client: AsyncClient, admin_token: str, student_token: str):
    h_admin, h_student = auth(admin_token), auth(student_token)
    eq_id = await _make_equipment(client, h_admin)
    req_id, item_id = await _make_approved_request(client, h_admin, h_student, eq_id)
    try:
        # max_renew_days seed = 7 วัน — ขอ 30 วันข้างหน้าต้องเกินเพดาน
        far_date = (date.today() + timedelta(days=30)).isoformat()
        r = await client.post(
            f"/borrow-requests/{req_id}/items/{item_id}/renew-request",
            json={"requested_date": far_date, "reason": "ไกลเกินไป"}, headers=h_student,
        )
        assert r.status_code == 400
    finally:
        await _cleanup(eq_id, req_id, item_id)


async def test_renew_request_blocked_after_max_renew_count(client: AsyncClient, admin_token: str, student_token: str):
    h_admin, h_student = auth(admin_token), auth(student_token)
    eq_id = await _make_equipment(client, h_admin)
    req_id, item_id = await _make_approved_request(client, h_admin, h_student, eq_id)
    try:
        d1 = (date.today() + timedelta(days=2)).isoformat()
        assert (await client.post(
            f"/borrow-requests/{req_id}/items/{item_id}/renew-request",
            json={"requested_date": d1, "reason": "ครั้งที่ 1"}, headers=h_student,
        )).status_code == 200
        assert (await client.post(f"/borrow-requests/{req_id}/items/{item_id}/renew-approve", headers=h_admin)).status_code == 200

        # max_renew_count seed = 1 ครั้ง — ขอครั้งที่ 2 ต้องถูกบล็อกตั้งแต่ตอนยื่นคำขอ ไม่ใช่รอไปติดตอนอนุมัติ
        d2 = (date.today() + timedelta(days=3)).isoformat()
        r = await client.post(
            f"/borrow-requests/{req_id}/items/{item_id}/renew-request",
            json={"requested_date": d2, "reason": "ครั้งที่ 2"}, headers=h_student,
        )
        assert r.status_code == 400
    finally:
        await _cleanup(eq_id, req_id, item_id)


async def test_old_renew_endpoint_removed(client: AsyncClient, admin_token: str, student_token: str):
    h_admin, h_student = auth(admin_token), auth(student_token)
    eq_id = await _make_equipment(client, h_admin)
    req_id, item_id = await _make_approved_request(client, h_admin, h_student, eq_id)
    try:
        r = await client.post(f"/borrow-requests/{req_id}/items/{item_id}/renew", headers=h_student)
        assert r.status_code == 404
    finally:
        await _cleanup(eq_id, req_id, item_id)
