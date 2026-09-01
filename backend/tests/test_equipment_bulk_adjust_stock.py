"""Tests: PATCH /equipment/bulk-adjust-stock — ปรับยอดคงเหลือหลายรายการพร้อมกันแบบ delta (บวก/ลบเท่ากันทุกแถว)

ต่างจาก adjust_stock เดี่ยวที่ SET ค่า absolute — อันนี้บวก/ลบเท่ากันทุกแถว แล้ว clamp อิสระต่อแถวเอง
(0 <= quantity_available <= quantity_total - outstanding_qty) ไม่ error ทั้งชุดถ้าบางแถวชนขอบเขต — id ที่ไม่มี
จริงถูกข้ามแบบ best-effort (ใส่ลง failed) ไม่ abort ทั้ง batch, id ซ้ำถูก dedupe ไม่โดน delta ซ้ำ

หมายเหตุ: conftest.py มี PYTEST_ALLOW_DB=1 รันใส่ DB dev จริง — ทุกเทสต้อง cleanup ใน finally เสมอ
"""
import uuid
from datetime import date

from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.borrow_item import BorrowItem
from app.models.borrow_request import BorrowRequest
from app.models.equipment import Equipment
from app.models.user import User
from tests.conftest import auth


async def _make_equipment(client: AsyncClient, admin_header: dict, **overrides) -> str:
    suffix = uuid.uuid4().hex[:6].upper()
    body = {
        "code": f"{uuid.uuid4().int % 10**15:015d}", "name": f"อุปกรณ์ทดสอบปรับยอดหลายรายการ {suffix}",
        "category_ids": [], "item_type": "durable", "quantity_total": 10,
        "image_urls": ["/uploads/test.jpg"],
    }
    body.update(overrides)
    r = await client.post("/equipment", json=body, headers=admin_header)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _cleanup(*eq_ids: str) -> None:
    async with AsyncSessionLocal() as db:
        for eq_id in eq_ids:
            await db.execute(delete(AuditLog).where(AuditLog.target_id == uuid.UUID(eq_id)))
            await db.execute(delete(Equipment).where(Equipment.id == uuid.UUID(eq_id)))
        await db.commit()


async def test_bulk_adjust_stock_positive_delta_adds_to_every_row(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    ids = [await _make_equipment(client, h, quantity_total=10) for _ in range(2)]
    try:
        # ลดยอดว่างเหลือ 5 ก่อน (ตอนสร้างใหม่ available == total เต็มอยู่แล้ว ไม่มีที่ว่างให้บวกเพิ่ม)
        for eq_id in ids:
            assert (await client.post(f"/equipment/{eq_id}/adjust-stock", json={
                "new_available": 5, "reason": "เตรียมทดสอบ",
            }, headers=h)).status_code == 200

        r = await client.patch("/equipment/bulk-adjust-stock", json={
            "equipment_ids": ids, "delta": 3, "reason": "นับเจอเพิ่ม",
        }, headers=h)
        assert r.status_code == 200, r.text
        rows = {row["id"]: row for row in r.json()["updated"]}
        for eq_id in ids:
            assert rows[eq_id]["quantity_available"] == 5 + 3
    finally:
        await _cleanup(*ids)


async def test_bulk_adjust_stock_negative_delta_clamps_at_zero_per_row(client: AsyncClient, admin_token: str):
    """แต่ละแถว clamp อิสระ — แถวที่เหลือน้อยกว่าที่จะลบ ต้องปัดเหลือ 0 ไม่ error ทั้งชุด แถวอื่นที่พอยังลบได้ปกติ"""
    h = auth(admin_token)
    low_id = await _make_equipment(client, h, quantity_total=10)
    high_id = await _make_equipment(client, h, quantity_total=10)
    try:
        # ปรับ low_id ให้เหลือ available แค่ 2 ก่อน (ผ่าน adjust-stock เดี่ยวที่มีอยู่แล้ว)
        assert (await client.post(f"/equipment/{low_id}/adjust-stock", json={
            "new_available": 2, "reason": "เตรียมทดสอบ",
        }, headers=h)).status_code == 200

        r = await client.patch("/equipment/bulk-adjust-stock", json={
            "equipment_ids": [low_id, high_id], "delta": -5, "reason": "นับพบของหาย",
        }, headers=h)
        assert r.status_code == 200, r.text
        rows = {row["id"]: row for row in r.json()["updated"]}
        assert rows[low_id]["quantity_available"] == 0, "เหลือ 2 ลบ 5 ต้อง clamp ที่ 0 ไม่ติดลบ"
        assert rows[high_id]["quantity_available"] == 5, "เหลือ 10 ลบ 5 = 5 ปกติ"
    finally:
        await _cleanup(low_id, high_id)


async def test_bulk_adjust_stock_positive_delta_clamps_at_quantity_total_per_row(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    eq_id = await _make_equipment(client, h, quantity_total=10)
    try:
        r = await client.patch("/equipment/bulk-adjust-stock", json={
            "equipment_ids": [eq_id], "delta": 100, "reason": "ทดสอบ clamp บน",
        }, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["updated"][0]["quantity_available"] == 10, "ห้ามเกิน quantity_total ของแถวนั้น"
    finally:
        await _cleanup(eq_id)


async def test_bulk_adjust_stock_writes_audit_log_per_row(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    ids = [await _make_equipment(client, h, quantity_total=10) for _ in range(2)]
    try:
        r = await client.patch("/equipment/bulk-adjust-stock", json={
            "equipment_ids": ids, "delta": -1, "reason": "เหตุผลทดสอบ log",
        }, headers=h)
        assert r.status_code == 200, r.text

        async with AsyncSessionLocal() as db:
            for eq_id in ids:
                log = (await db.execute(
                    select(AuditLog).where(
                        AuditLog.target_id == uuid.UUID(eq_id), AuditLog.action == "bulk_adjust_stock",
                    )
                )).scalars().first()
                assert log is not None, f"ต้องมี audit log แยกต่อแถว ({eq_id})"
                assert log.detail["delta"] == -1
                assert log.detail["reason"] == "เหตุผลทดสอบ log"
                assert log.detail["old_available"] == 10
                assert log.detail["new_available"] == 9
    finally:
        await _cleanup(*ids)


async def test_bulk_adjust_stock_rejects_zero_delta(client: AsyncClient, admin_token: str):
    """delta=0 ผ่าน pydantic ได้ (เป็น int ปกติ) แต่ไม่มีความหมายทางธุรกิจ — ปล่อยผ่าน service ก็ไม่พังอะไร
    (ทุกแถวได้ค่าเดิม) แต่เทสนี้ยืนยันพฤติกรรมจริง ไม่ error ไม่เปลี่ยนอะไร"""
    h = auth(admin_token)
    eq_id = await _make_equipment(client, h, quantity_total=10)
    try:
        r = await client.patch("/equipment/bulk-adjust-stock", json={
            "equipment_ids": [eq_id], "delta": 0, "reason": "เหตุผล",
        }, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["updated"][0]["quantity_available"] == 10
    finally:
        await _cleanup(eq_id)


async def test_bulk_adjust_stock_rejects_blank_reason(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    eq_id = await _make_equipment(client, h, quantity_total=10)
    try:
        r = await client.patch("/equipment/bulk-adjust-stock", json={
            "equipment_ids": [eq_id], "delta": 1, "reason": "",
        }, headers=h)
        assert r.status_code == 422
    finally:
        await _cleanup(eq_id)


async def test_bulk_adjust_stock_forbidden_for_student(client: AsyncClient, admin_token: str, student_token: str):
    h_admin = auth(admin_token)
    eq_id = await _make_equipment(client, h_admin, quantity_total=10)
    try:
        r = await client.patch("/equipment/bulk-adjust-stock", json={
            "equipment_ids": [eq_id], "delta": 1, "reason": "ทดสอบสิทธิ์",
        }, headers=auth(student_token))
        assert r.status_code == 403
    finally:
        await _cleanup(eq_id)


async def test_bulk_adjust_stock_nonexistent_id_partial_success(client: AsyncClient, admin_token: str):
    """id ที่ไม่มีจริงต้องไม่บล็อกทั้ง batch (best-effort เหมือน bulk-delete/bulk-retire/bulk-update) —
    แถวที่ถูกต้องยังถูกปรับและ commit จริง ส่วน id ที่ไม่มีจริงโผล่ใน failed แทนการ abort ทั้งชุดด้วย 404"""
    h = auth(admin_token)
    eq_id = await _make_equipment(client, h, quantity_total=10)
    bad_id = str(uuid.uuid4())
    try:
        assert (await client.post(f"/equipment/{eq_id}/adjust-stock", json={
            "new_available": 5, "reason": "เตรียมทดสอบ",
        }, headers=h)).status_code == 200

        r = await client.patch("/equipment/bulk-adjust-stock", json={
            "equipment_ids": [eq_id, bad_id], "delta": 3, "reason": "ทดสอบ id ผิด",
        }, headers=h)
        assert r.status_code == 200, r.text
        body = r.json()
        assert [row["id"] for row in body["updated"]] == [eq_id]
        assert body["updated"][0]["quantity_available"] == 8, "แถวที่ถูกต้องต้องยังถูกปรับและ commit จริง"
        assert len(body["failed"]) == 1 and body["failed"][0]["equipment_id"] == bad_id

        # ยืนยันว่า commit จริงลง DB ไม่ใช่แค่ค่าที่ตอบกลับ (all-or-nothing แบบเดิมจะ abort ทั้ง transaction)
        async with AsyncSessionLocal() as db:
            eq = await db.get(Equipment, uuid.UUID(eq_id))
            assert eq.quantity_available == 8
    finally:
        await _cleanup(eq_id)


async def test_bulk_adjust_stock_duplicate_id_applies_delta_once(client: AsyncClient, admin_token: str):
    """id ซ้ำกันในคำขอเดียวต้องถูก dedupe — โดน delta แค่ครั้งเดียว ไม่ใช่ทบกันตามจำนวนที่ซ้ำ"""
    h = auth(admin_token)
    eq_id = await _make_equipment(client, h, quantity_total=10)
    try:
        assert (await client.post(f"/equipment/{eq_id}/adjust-stock", json={
            "new_available": 5, "reason": "เตรียมทดสอบ",
        }, headers=h)).status_code == 200

        r = await client.patch("/equipment/bulk-adjust-stock", json={
            "equipment_ids": [eq_id, eq_id], "delta": 2, "reason": "ทดสอบ id ซ้ำ",
        }, headers=h)
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body["updated"]) == 1
        assert body["updated"][0]["quantity_available"] == 7, (
            "id ซ้ำต้องบวก delta แค่ครั้งเดียว (5+2=7) ไม่ใช่ 2 ครั้ง (5+2+2=9)"
        )

        async with AsyncSessionLocal() as db:
            logs = (await db.execute(
                select(AuditLog).where(
                    AuditLog.target_id == uuid.UUID(eq_id), AuditLog.action == "bulk_adjust_stock",
                )
            )).scalars().all()
            assert len(logs) == 1, "id ซ้ำต้องเขียน audit log แค่แถวเดียว ไม่ใช่ต่อ id ที่ส่งมา"
    finally:
        await _cleanup(eq_id)


async def test_bulk_adjust_stock_clamps_to_total_minus_outstanding_not_total(
    client: AsyncClient, admin_token: str, test_student: User,
):
    """เพดานบนต้องหัก outstanding (จำนวนที่ถูกยืมออกไปจริง approved+ยังไม่คืน) ออกจาก quantity_total ก่อน —
    ไม่ใช่ clamp ที่ quantity_total เฉยๆ ไม่งั้นแอดมินปรับยอดว่างขึ้นไปทับจำนวนที่ยังค้างอยู่ในมือคนยืมได้
    (total=10, ยืมออกจริง 3 หน่วย available=7 ก่อนปรับ, +3 ต้อง clamp ที่ 7 (10-3) ไม่ใช่ 10) พอมีคนคืนของ
    3 หน่วยที่ยืมอยู่จริงเข้ามาทีหลัง quantity_available += quantity จะทะลุ quantity_total ชน CHECK constraint
    ถ้า bug นี้ไม่ถูกแก้"""
    h = auth(admin_token)
    eq_id = await _make_equipment(client, h, quantity_total=10)
    req_id = uuid.uuid4()
    try:
        # จำลอง 3 หน่วยถูกยืมออกไปจริง (approved, ยังไม่คืน) → available เหลือ 7 ก่อนปรับ
        assert (await client.post(f"/equipment/{eq_id}/adjust-stock", json={
            "new_available": 7, "reason": "เตรียมทดสอบ (จำลองมีของออกไป 3 ชิ้น)",
        }, headers=h)).status_code == 200
        async with AsyncSessionLocal() as db:
            db.add(BorrowRequest(
                id=req_id, request_code=f"REQ-BULKADJ-{req_id.hex[:6]}",
                student_id=test_student.id, status="approved",
                purpose="ทดสอบ bulk_adjust_stock หัก outstanding qty",
                requested_due_date=date(2099, 1, 1), due_date=date(2099, 1, 1),
            ))
            db.add(BorrowItem(
                id=uuid.uuid4(), borrow_request_id=req_id, equipment_id=uuid.UUID(eq_id),
                item_type_snapshot="durable", quantity=3,
            ))
            await db.commit()

        r = await client.patch("/equipment/bulk-adjust-stock", json={
            "equipment_ids": [eq_id], "delta": 3, "reason": "นับเจอเพิ่ม",
        }, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["updated"][0]["quantity_available"] == 7, (
            "ต้อง clamp ที่ quantity_total - outstanding (10-3=7) ไม่ใช่ quantity_total (10) เฉยๆ"
        )
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(BorrowItem).where(BorrowItem.borrow_request_id == req_id))
            await db.execute(delete(BorrowRequest).where(BorrowRequest.id == req_id))
            await db.commit()
        await _cleanup(eq_id)
