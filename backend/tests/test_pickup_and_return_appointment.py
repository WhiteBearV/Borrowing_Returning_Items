"""เฟส 4 — นัดรับของตอนอนุมัติ + นัดคืนตอนแจ้งขอคืน (feedback อาจารย์ 5 ก.ย. 69 ข้อ 10, 12)

หมายเหตุ: conftest.py มี PYTEST_ALLOW_DB=1 รันใส่ DB dev จริง — ทุกเทสต้อง cleanup ใน finally เสมอ
"""
import uuid
from datetime import date, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.config import TZ
from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.borrow_item import BorrowItem
from app.models.borrow_request import BorrowRequest
from app.models.equipment import Equipment
from app.models.notification import Notification
from tests.conftest import auth

DUE = (date.today() + timedelta(days=10)).isoformat()
# นัดหมายเป็นเวลาไทยที่ผู้ใช้กรอกจากหน้าเว็บ (ไม่มี timezone ติดมา)
TOMORROW_1PM = (datetime.now(TZ) + timedelta(days=1)).replace(
    hour=13, minute=0, second=0, microsecond=0).replace(tzinfo=None)


async def _make_equipment(client: AsyncClient, h_admin: dict) -> str:
    r = await client.post("/equipment", json={
        "code": f"{uuid.uuid4().int % 10**15:015d}",
        "name": f"อุปกรณ์ทดสอบนัดหมาย {uuid.uuid4().hex[:6]}",
        "category_ids": [], "item_type": "durable", "quantity_total": 1,
        "image_urls": ["/uploads/test.jpg"], "unit_value": 1000, "acquired_at": "2024-01-15",
    }, headers=h_admin)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _make_request(client: AsyncClient, h_student: dict, eq_id: str) -> dict:
    r = await client.post("/borrow-requests", headers=h_student, json={
        "purpose": "ทดสอบนัดหมาย", "requested_due_date": DUE,
        "items": [{"equipment_id": eq_id, "quantity": 1}],
    })
    assert r.status_code == 201, r.text
    return r.json()


async def _cleanup(eq_id: str, req_id: str | None) -> None:
    async with AsyncSessionLocal() as db:
        if req_id:
            rid = uuid.UUID(req_id)
            item_ids = (await db.execute(
                select(BorrowItem.id).where(BorrowItem.borrow_request_id == rid))).scalars().all()
            await db.execute(delete(Notification).where(Notification.borrow_request_id == rid))
            for iid in item_ids:
                await db.execute(delete(AuditLog).where(AuditLog.target_id == iid))
            await db.execute(delete(BorrowItem).where(BorrowItem.borrow_request_id == rid))
            await db.execute(delete(AuditLog).where(AuditLog.target_id == rid))
            await db.execute(delete(BorrowRequest).where(BorrowRequest.id == rid))
        await db.execute(delete(AuditLog).where(AuditLog.target_id == uuid.UUID(eq_id)))
        await db.execute(delete(Equipment).where(Equipment.id == uuid.UUID(eq_id)))
        await db.commit()


async def test_approve_stores_pickup_and_tells_student(
    client: AsyncClient, admin_token: str, student_token: str, test_student,
):
    """อนุมัติพร้อมนัดรับของ — เก็บครบ · เวลาไม่เพี้ยนโซน · แจ้งเตือนบอกวันเวลา/สถานที่ · ใบยืมพิมพ์ด้วย"""
    h_admin, h_student = auth(admin_token), auth(student_token)
    eq_id = await _make_equipment(client, h_admin)
    req_id = None
    try:
        req_id = (await _make_request(client, h_student, eq_id))["id"]
        r = await client.patch(f"/borrow-requests/{req_id}/approve", headers=h_admin, json={
            "pickup_at": TOMORROW_1PM.isoformat(),
            "pickup_location": "ห้อง 15310",
            "pickup_note": "ติดต่อพี่แอดมินหน้าห้อง",
        })
        assert r.status_code == 200, r.text

        body = (await client.get(f"/borrow-requests/{req_id}", headers=h_student)).json()
        assert body["pickup_location"] == "ห้อง 15310"
        assert body["pickup_note"] == "ติดต่อพี่แอดมินหน้าห้อง"
        # เวลาไทย 13:00 ที่กรอกไว้ ต้องอ่านกลับมาได้ 13:00 ตามเดิม (ไม่เลื่อนไป 20:00)
        got = datetime.fromisoformat(body["pickup_at"]).astimezone(TZ)
        assert (got.hour, got.minute) == (13, 0)
        assert got.date() == TOMORROW_1PM.date()

        # แจ้งเตือนนักศึกษาต้องบอกนัดรับของในบรรทัดเดียวกัน ไม่ต้องไปเปิดหาที่อื่น
        async with AsyncSessionLocal() as db:
            msg = (await db.execute(
                select(Notification.message).where(
                    Notification.borrow_request_id == uuid.UUID(req_id),
                    Notification.user_id == test_student.id,
                    Notification.type == "approved",
                ))).scalar_one()
        assert "รับของ" in msg and "ห้อง 15310" in msg and "13:00" in msg

        # ใบยืม PDF (เอกสารที่ผู้ยืมถือไปจริง) ต้องมีนัดรับของด้วย
        pdf = (await client.get(f"/borrow-requests/{req_id}/pdf", headers=h_student)).content
        import io
        from pypdf import PdfReader
        text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
        assert "นัดรับของ" in text
        assert "ห้อง 15310" in text.replace("\n", "").replace(" ", "").replace("ห้อง15310", "ห้อง 15310")
    finally:
        await _cleanup(eq_id, req_id)


async def test_approve_without_pickup_stays_empty(client: AsyncClient, admin_token: str, student_token: str):
    """ไม่นัดล่วงหน้า (จ่ายทันทีหน้าเคาน์เตอร์) ต้องอนุมัติได้ตามปกติ ไม่บังคับ"""
    h_admin, h_student = auth(admin_token), auth(student_token)
    eq_id = await _make_equipment(client, h_admin)
    req_id = None
    try:
        req_id = (await _make_request(client, h_student, eq_id))["id"]
        assert (await client.patch(f"/borrow-requests/{req_id}/approve", headers=h_admin)).status_code == 200
        body = (await client.get(f"/borrow-requests/{req_id}", headers=h_student)).json()
        assert body["pickup_at"] is None and body["pickup_location"] is None
    finally:
        await _cleanup(eq_id, req_id)


async def test_request_return_requires_appointment(client: AsyncClient, admin_token: str, student_token: str):
    """แจ้งขอคืนต้องนัดวัน-เวลา-สถานที่เสมอ และห้ามนัดย้อนหลัง"""
    h_admin, h_student = auth(admin_token), auth(student_token)
    eq_id = await _make_equipment(client, h_admin)
    req_id = None
    try:
        req = await _make_request(client, h_student, eq_id)
        req_id, item_id = req["id"], req["items"][0]["id"]
        assert (await client.patch(f"/borrow-requests/{req_id}/approve", headers=h_admin)).status_code == 200

        # ไม่ส่งนัดหมายเลย
        r = await client.post(f"/borrow-requests/{req_id}/request-return", headers=h_student,
                              json={"item_ids": [item_id]})
        assert r.status_code == 422

        # สถานที่เป็นช่องว่างล้วน
        r = await client.post(f"/borrow-requests/{req_id}/request-return", headers=h_student, json={
            "item_ids": [item_id], "return_appoint_at": TOMORROW_1PM.isoformat(),
            "return_appoint_location": "   "})
        assert r.status_code == 422

        # นัดย้อนหลังเป็นวัน ๆ (คิวของแอดมินจะเพี้ยน)
        past = (datetime.now(TZ) - timedelta(days=2)).replace(tzinfo=None).isoformat()
        r = await client.post(f"/borrow-requests/{req_id}/request-return", headers=h_student, json={
            "item_ids": [item_id], "return_appoint_at": past, "return_appoint_location": "ห้องพัสดุ"})
        assert r.status_code == 400
    finally:
        await _cleanup(eq_id, req_id)


async def test_return_appointment_saved_notified_and_cleared(
    client: AsyncClient, admin_token: str, student_token: str, test_admin,
):
    """นัดคืนถูกเก็บรายชิ้น · แอดมินได้รับแจ้งพร้อมรายละเอียดนัด · รับคืนจริงแล้วคิวต้องหาย"""
    h_admin, h_student = auth(admin_token), auth(student_token)
    eq_id = await _make_equipment(client, h_admin)
    req_id = None
    try:
        req = await _make_request(client, h_student, eq_id)
        req_id, item_id = req["id"], req["items"][0]["id"]
        assert (await client.patch(f"/borrow-requests/{req_id}/approve", headers=h_admin)).status_code == 200

        r = await client.post(f"/borrow-requests/{req_id}/request-return", headers=h_student, json={
            "item_ids": [item_id], "return_appoint_at": TOMORROW_1PM.isoformat(),
            "return_appoint_location": "ห้องพัสดุ ชั้น 3"})
        assert r.status_code == 200, r.text

        item = (await client.get(f"/borrow-requests/{req_id}", headers=h_student)).json()["items"][0]
        assert item["return_appoint_location"] == "ห้องพัสดุ ชั้น 3"
        got = datetime.fromisoformat(item["return_appoint_at"]).astimezone(TZ)
        assert (got.hour, got.minute) == (13, 0)

        async with AsyncSessionLocal() as db:
            msg = (await db.execute(
                select(Notification.message).where(
                    Notification.borrow_request_id == uuid.UUID(req_id),
                    Notification.user_id == test_admin.id,
                    Notification.type == "return_requested_admin",
                ))).scalar_one()
        assert "ห้องพัสดุ ชั้น 3" in msg and "13:00" in msg

        # รับคืนจริงแล้วต้องหายจากคิวนัด ไม่งั้นแอดมินเห็นนัดค้างของที่คืนไปแล้ว
        r = await client.post(f"/borrow-requests/{req_id}/items/{item_id}/return",
                              headers=h_admin, json={"condition_on_return": "ok"})
        assert r.status_code == 200, r.text
        item = (await client.get(f"/borrow-requests/{req_id}", headers=h_student)).json()["items"][0]
        assert item["return_appoint_at"] is None
    finally:
        await _cleanup(eq_id, req_id)
