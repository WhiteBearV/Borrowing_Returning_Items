"""เฟส 3 — วันครบกำหนดคืนรายชิ้น + อนุมัติ/ปฏิเสธบางชิ้น (feedback อาจารย์ 5 ก.ย. 69 ข้อ 6, 8)

หมายเหตุ: conftest.py มี PYTEST_ALLOW_DB=1 รันใส่ DB dev จริง — ทุกเทสต้อง cleanup ใน finally เสมอ
"""
import uuid
from datetime import date, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.borrow_item import BorrowItem
from app.models.borrow_request import BorrowRequest
from app.models.equipment import Equipment
from app.models.notification import Notification
from tests.conftest import auth

# นัดคืนบังคับกรอกตั้งแต่เฟส 4 — ใช้พรุ่งนี้บ่ายโมงเป็นค่ามาตรฐานของไฟล์นี้
APPOINT_AT = (datetime.now() + timedelta(days=1)).replace(hour=13, minute=0, second=0,
                                                          microsecond=0).isoformat()

D = lambda n: (date.today() + timedelta(days=n)).isoformat()  # noqa: E731


async def _make_equipment(client: AsyncClient, h_admin: dict, label: str) -> str:
    r = await client.post("/equipment", json={
        "code": f"{uuid.uuid4().int % 10**15:015d}",
        "name": f"อุปกรณ์ทดสอบอนุมัติบางชิ้น {label} {uuid.uuid4().hex[:6]}",
        "category_ids": [], "item_type": "durable", "quantity_total": 1,
        "image_urls": ["/uploads/test.jpg"], "unit_value": 1000, "acquired_at": "2024-01-15",
    }, headers=h_admin)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _available(eq_id: str) -> int:
    async with AsyncSessionLocal() as db:
        return (await db.execute(
            select(Equipment.quantity_available).where(Equipment.id == uuid.UUID(eq_id))
        )).scalar_one()


async def _cleanup(eq_ids: list[str], req_ids: list[str]) -> None:
    async with AsyncSessionLocal() as db:
        for req_id in req_ids:
            rid = uuid.UUID(req_id)
            item_ids = (await db.execute(
                select(BorrowItem.id).where(BorrowItem.borrow_request_id == rid)
            )).scalars().all()
            await db.execute(delete(Notification).where(Notification.borrow_request_id == rid))
            for iid in item_ids:
                await db.execute(delete(AuditLog).where(AuditLog.target_id == iid))
            await db.execute(delete(BorrowItem).where(BorrowItem.borrow_request_id == rid))
            await db.execute(delete(AuditLog).where(AuditLog.target_id == rid))
            await db.execute(delete(BorrowRequest).where(BorrowRequest.id == rid))
        for eq_id in eq_ids:
            await db.execute(delete(AuditLog).where(AuditLog.target_id == uuid.UUID(eq_id)))
            await db.execute(delete(Equipment).where(Equipment.id == uuid.UUID(eq_id)))
        await db.commit()


async def test_approve_two_of_three_items(client: AsyncClient, admin_token: str, student_token: str):
    """อนุมัติ 2 จาก 3 ชิ้น — สต็อกลดแค่ 2 · ชิ้นที่ไม่อนุมัติมีเหตุผล · คำขอปิดได้เมื่อคืนครบเฉพาะที่อนุมัติ"""
    h_admin, h_student = auth(admin_token), auth(student_token)
    eq = [await _make_equipment(client, h_admin, str(i)) for i in range(3)]
    req_id = None
    try:
        r = await client.post("/borrow-requests", headers=h_student, json={
            "purpose": "ทดสอบอนุมัติบางชิ้น",
            "requested_due_date": D(10),
            "items": [
                {"equipment_id": eq[0], "quantity": 1, "requested_due_date": D(5)},
                {"equipment_id": eq[1], "quantity": 1},           # ไม่ระบุ = ใช้วันของทั้งใบ
                {"equipment_id": eq[2], "quantity": 1, "requested_due_date": D(20)},
            ],
        })
        assert r.status_code == 201, r.text
        req_id = r.json()["id"]
        items = {i["equipment_id"]: i for i in r.json()["items"]}
        assert items[eq[0]]["requested_due_date"] == D(5)
        assert items[eq[1]]["requested_due_date"] == D(10)      # เติมวันของทั้งใบให้เอง

        r = await client.patch(f"/borrow-requests/{req_id}/approve", headers=h_admin, json={"items": [
            {"item_id": items[eq[0]]["id"], "approved": True, "due_date": D(7)},   # แอดมินแก้วันเอง
            {"item_id": items[eq[2]]["id"], "approved": False, "rejection_reason": "เครื่องส่งซ่อม"},
        ]})
        assert r.status_code == 200, r.text

        # ตัดสต็อกเฉพาะชิ้นที่อนุมัติ
        assert await _available(eq[0]) == 0
        assert await _available(eq[1]) == 0
        assert await _available(eq[2]) == 1

        req = (await client.get(f"/borrow-requests/{req_id}", headers=h_admin)).json()
        assert req["status"] == "approved"
        assert req["due_date"] == D(10)          # ช้าสุดของชิ้นที่อนุมัติ ไม่ใช่ของชิ้นที่ถูกปฏิเสธ (D20)
        by_eq = {i["equipment_id"]: i for i in req["items"]}
        assert by_eq[eq[0]]["item_status"] == "approved" and by_eq[eq[0]]["due_date"] == D(7)
        assert by_eq[eq[1]]["item_status"] == "approved" and by_eq[eq[1]]["due_date"] == D(10)
        assert by_eq[eq[2]]["item_status"] == "rejected"
        assert by_eq[eq[2]]["rejection_reason"] == "เครื่องส่งซ่อม"
        assert by_eq[eq[2]]["due_date"] is None

        # ชิ้นที่ไม่อนุมัติแตะอะไรไม่ได้ — ไม่เคยได้ของไป
        r = await client.post(f"/borrow-requests/{req_id}/request-return", headers=h_student,
                              json={"item_ids": [by_eq[eq[2]]["id"]], "return_appoint_at": APPOINT_AT, "return_appoint_location": "ห้องพัสดุ"})
        assert r.status_code == 400

        # คืนครบ "เฉพาะชิ้นที่อนุมัติ" ต้องปิดคำขอได้ (ไม่งั้นคำขอจะค้างตลอดไป)
        for e in (eq[0], eq[1]):
            r = await client.post(
                f"/borrow-requests/{req_id}/items/{by_eq[e]['id']}/return",
                headers=h_admin, json={"condition_on_return": "ok"})
            assert r.status_code == 200, r.text
        req = (await client.get(f"/borrow-requests/{req_id}", headers=h_admin)).json()
        assert req["status"] == "completed"
        assert await _available(eq[0]) == 1 and await _available(eq[1]) == 1
    finally:
        await _cleanup(eq, [req_id] if req_id else [])


async def test_reject_all_items_rejects_whole_request(client: AsyncClient, admin_token: str, student_token: str):
    """ปฏิเสธครบทุกชิ้น = ทั้งใบถูกปฏิเสธ ไม่มีของออกจากคลัง"""
    h_admin, h_student = auth(admin_token), auth(student_token)
    eq = [await _make_equipment(client, h_admin, "all")]
    req_id = None
    try:
        r = await client.post("/borrow-requests", headers=h_student, json={
            "purpose": "ทดสอบปฏิเสธทั้งใบ", "requested_due_date": D(10),
            "items": [{"equipment_id": eq[0], "quantity": 1}],
        })
        req_id = r.json()["id"]
        item_id = r.json()["items"][0]["id"]

        r = await client.patch(f"/borrow-requests/{req_id}/approve", headers=h_admin, json={
            "items": [{"item_id": item_id, "approved": False, "rejection_reason": "ของไม่พร้อมจ่าย"}]})
        assert r.status_code == 200, r.text

        req = (await client.get(f"/borrow-requests/{req_id}", headers=h_admin)).json()
        assert req["status"] == "rejected"
        assert "ของไม่พร้อมจ่าย" in req["rejection_reason"]
        assert await _available(eq[0]) == 1
    finally:
        await _cleanup(eq, [req_id] if req_id else [])


async def test_reject_item_requires_reason(client: AsyncClient, admin_token: str, student_token: str):
    """ไม่อนุมัติต้องมีเหตุผลเสมอ — ไม่งั้นนักศึกษาไม่รู้ว่าทำไมไม่ได้ของ"""
    h_admin, h_student = auth(admin_token), auth(student_token)
    eq = [await _make_equipment(client, h_admin, "reason")]
    req_id = None
    try:
        r = await client.post("/borrow-requests", headers=h_student, json={
            "purpose": "ทดสอบเหตุผลบังคับ", "requested_due_date": D(10),
            "items": [{"equipment_id": eq[0], "quantity": 1}],
        })
        req_id = r.json()["id"]
        item_id = r.json()["items"][0]["id"]

        r = await client.patch(f"/borrow-requests/{req_id}/approve", headers=h_admin, json={
            "items": [{"item_id": item_id, "approved": False, "rejection_reason": "   "}]})
        assert r.status_code == 400
        # ยังไม่ถูกตัดสิน สต็อกต้องไม่ขยับ
        assert await _available(eq[0]) == 1
        assert (await client.get(f"/borrow-requests/{req_id}", headers=h_admin)).json()["status"] == "pending"
    finally:
        await _cleanup(eq, [req_id] if req_id else [])


async def test_approve_without_body_keeps_old_behaviour(client: AsyncClient, admin_token: str, student_token: str):
    """ไม่ส่ง body = อนุมัติทั้งใบตามวันที่นักศึกษาขอ (พฤติกรรมเดิมต้องไม่เปลี่ยน)"""
    h_admin, h_student = auth(admin_token), auth(student_token)
    eq = [await _make_equipment(client, h_admin, "plain")]
    req_id = None
    try:
        r = await client.post("/borrow-requests", headers=h_student, json={
            "purpose": "ทดสอบอนุมัติทั้งใบ", "requested_due_date": D(9),
            "items": [{"equipment_id": eq[0], "quantity": 1}],
        })
        req_id = r.json()["id"]
        assert (await client.patch(f"/borrow-requests/{req_id}/approve", headers=h_admin)).status_code == 200

        req = (await client.get(f"/borrow-requests/{req_id}", headers=h_admin)).json()
        assert req["status"] == "approved" and req["due_date"] == D(9)
        assert req["items"][0]["item_status"] == "approved"
        assert req["items"][0]["due_date"] == D(9)
        assert await _available(eq[0]) == 0
    finally:
        await _cleanup(eq, [req_id] if req_id else [])


async def test_item_due_date_respects_cap(client: AsyncClient, admin_token: str, student_token: str):
    """วันคืนรายชิ้นต้องผ่านด่านเดียวกับวันของทั้งใบ — ไม่ใช่ทางอ้อมข้ามเพดาน 3 ปี"""
    h_admin, h_student = auth(admin_token), auth(student_token)
    eq = [await _make_equipment(client, h_admin, "cap")]
    try:
        r = await client.post("/borrow-requests", headers=h_student, json={
            "purpose": "ทดสอบเพดานวัน", "requested_due_date": D(10),
            "items": [{"equipment_id": eq[0], "quantity": 1, "requested_due_date": D(365 * 4)}],
        })
        assert r.status_code == 400, r.text
    finally:
        await _cleanup(eq, [])
