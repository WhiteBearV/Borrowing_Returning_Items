"""Tests: ลบอุปกรณ์ถาวรได้จริงแม้เคยมีประวัติการยืม (ปลดระวาง+ไม่มีการยืมค้าง)

Bug เดิม: delete_equipment เช็ค "มีประวัติการยืมไหม" แบบนับทุกแถวไม่แยกสถานะ ทำให้อุปกรณ์ที่เคยถูกยืม
แม้แต่ครั้งเดียว (แม้ปลดระวางไปแล้ว) ลบถาวรไม่ได้ตลอดกาล — เช่น DH-11 ที่ admin รายงานว่ากดลบไม่ได้เลย

แก้ด้วยการเก็บ equipment_name/code/unit เป็น snapshot คอลัมน์จริงใน BorrowItem (ไม่ใช่ live join ผ่าน
equipment_id อีกต่อไป) แล้วเปลี่ยน FK เป็น ON DELETE SET NULL — ประวัติการยืมจึงไม่พังแม้แถว equipment
จะถูกลบถาวรไปแล้ว จากนั้นผ่อนคลาย guard ให้เช็คเฉพาะ "การยืมที่ยังไม่จบ" (pending/approved) แทน "เคยมีประวัติ"

จุดที่ทดสอบเน้นเป็นพิเศษ: reject/cancel ไม่เคยเซ็ต returned=True เลย (ไม่มี flow คืนของ) ถ้า guard เช็คแค่
returned==False เฉยๆ จะพังผิดเป็นบล็อกลบตลอดกาลเหมือนบั๊กเดิม — ต้อง join ไป BorrowRequest.status ด้วย
"""
import uuid

from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.borrow_item import BorrowItem
from app.models.borrow_request import BorrowRequest
from app.models.bundle import Bundle, BundleItem
from app.models.equipment import Equipment
from app.models.notification import Notification
from tests.conftest import auth


async def _make_equipment(client: AsyncClient, admin_header: dict) -> str:
    suffix = uuid.uuid4().hex[:6].upper()
    r = await client.post("/equipment", json={
        "code": f"DEL-{suffix}", "name": f"อุปกรณ์ทดสอบลบถาวร {suffix}",
        "category_ids": [], "item_type": "durable", "quantity_total": 1,
        "image_urls": ["/uploads/test.jpg"],
    }, headers=admin_header)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _make_request(client: AsyncClient, student_header: dict, eq_id: str) -> str:
    r = await client.post("/borrow-requests", headers=student_header, json={
        "purpose": "ทดสอบลบอุปกรณ์ถาวร",
        "requested_due_date": "2028-06-01",
        "items": [{"equipment_id": eq_id, "quantity": 1}],
    })
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _cleanup(eq_id: str, req_id: str | None = None) -> None:
    async with AsyncSessionLocal() as db:
        if req_id:
            await db.execute(delete(Notification).where(Notification.borrow_request_id == uuid.UUID(req_id)))
            await db.execute(delete(BorrowItem).where(BorrowItem.borrow_request_id == uuid.UUID(req_id)))
            await db.execute(delete(BorrowRequest).where(BorrowRequest.id == uuid.UUID(req_id)))
        await db.execute(delete(BorrowItem).where(BorrowItem.equipment_id == uuid.UUID(eq_id)))
        await db.execute(delete(AuditLog).where(AuditLog.target_id == uuid.UUID(eq_id)))
        await db.execute(delete(Equipment).where(Equipment.id == uuid.UUID(eq_id)))
        await db.commit()


async def test_delete_equipment_blocked_when_not_retired(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    eq_id = await _make_equipment(client, h)
    try:
        r = await client.delete(f"/equipment/{eq_id}/permanent", headers=h)
        assert r.status_code == 400
        assert "ปลดระวาง" in r.json()["detail"]
    finally:
        await _cleanup(eq_id)


async def test_delete_equipment_blocked_with_pending_request(
    client: AsyncClient, admin_token: str, student_token: str
):
    h = auth(admin_token)
    eq_id = await _make_equipment(client, h)
    req_id = await _make_request(client, auth(student_token), eq_id)
    try:
        assert (await client.delete(f"/equipment/{eq_id}", headers=h)).status_code == 204  # retire
        r = await client.delete(f"/equipment/{eq_id}/permanent", headers=h)
        assert r.status_code == 400
        assert "ยังไม่คืน" in r.json()["detail"]
    finally:
        await _cleanup(eq_id, req_id)


async def test_delete_equipment_blocked_with_approved_unreturned_request(
    client: AsyncClient, admin_token: str, student_token: str
):
    h = auth(admin_token)
    eq_id = await _make_equipment(client, h)
    req_id = await _make_request(client, auth(student_token), eq_id)
    try:
        assert (await client.patch(f"/borrow-requests/{req_id}/approve", headers=h)).status_code == 200
        assert (await client.delete(f"/equipment/{eq_id}", headers=h)).status_code == 204  # retire
        r = await client.delete(f"/equipment/{eq_id}/permanent", headers=h)
        assert r.status_code == 400
        assert "ยังไม่คืน" in r.json()["detail"]
    finally:
        await _cleanup(eq_id, req_id)


async def test_delete_equipment_succeeds_after_completed_request(
    client: AsyncClient, admin_token: str, student_token: str
):
    """ยืมจนคืนครบ (completed) แล้วปลดระวาง → ลบถาวรได้จริง และประวัติการยืมต้องยังอ่านชื่อ/รหัสเดิมได้"""
    h = auth(admin_token)
    eq_id = await _make_equipment(client, h)
    req_id = await _make_request(client, auth(student_token), eq_id)
    try:
        assert (await client.patch(f"/borrow-requests/{req_id}/approve", headers=h)).status_code == 200
        assert (await client.post(f"/borrow-requests/{req_id}/return-all", headers=h)).status_code == 200
        assert (await client.delete(f"/equipment/{eq_id}", headers=h)).status_code == 204  # retire

        r = await client.delete(f"/equipment/{eq_id}/permanent", headers=h)
        assert r.status_code == 204, r.text

        async with AsyncSessionLocal() as db:
            assert await db.get(Equipment, uuid.UUID(eq_id)) is None, "แถว equipment ต้องหายจริง"
            item = (await db.execute(
                select(BorrowItem).where(BorrowItem.borrow_request_id == uuid.UUID(req_id))
            )).scalar_one()
            assert item.equipment_id is None, "FK ต้องถูก SET NULL"
            assert item.equipment_name is not None
            assert item.equipment_code is not None
            actions = (await db.execute(
                select(AuditLog.action).where(AuditLog.target_id == uuid.UUID(eq_id))
            )).scalars().all()
            assert "delete_equipment" in actions

        # เช็คผ่าน API จริงด้วย ไม่ใช่แค่ ORM ตรงๆ — บั๊กจริงที่เจอ (equipment_id ใน response schema ไม่ยอมรับ
        # None ทำให้ Pydantic validation พังเป็น 500 ทั้งหน้า "ดูคำขอ" และ "รายการคำขอทั้งหมด") จะไม่ถูกจับ
        # ถ้าเทสแค่ระดับ ORM เพราะ SQLAlchemy คืนค่า None ได้ปกติ ไม่ผ่าน Pydantic response_model เลย
        r = await client.get(f"/borrow-requests/{req_id}", headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["items"][0]["equipment_id"] is None
        assert r.json()["items"][0]["equipment_name"]

        r = await client.get("/borrow-requests?page=1&page_size=20", headers=h)
        assert r.status_code == 200, r.text
    finally:
        await _cleanup(eq_id, req_id)


async def test_delete_equipment_succeeds_after_rejected_request(
    client: AsyncClient, admin_token: str, student_token: str
):
    """reject ไม่เคยเซ็ต returned=True — ถ้า guard เช็คแค่ returned==False จะพังผิดเป็นบล็อกตลอดกาล"""
    h = auth(admin_token)
    eq_id = await _make_equipment(client, h)
    req_id = await _make_request(client, auth(student_token), eq_id)
    try:
        r = await client.patch(f"/borrow-requests/{req_id}/reject", headers=h,
                                json={"rejection_reason": "ทดสอบ"})
        assert r.status_code == 200, r.text
        assert (await client.delete(f"/equipment/{eq_id}", headers=h)).status_code == 204  # retire

        r = await client.delete(f"/equipment/{eq_id}/permanent", headers=h)
        assert r.status_code == 204, r.text
    finally:
        await _cleanup(eq_id, req_id)


async def test_delete_equipment_succeeds_after_cancelled_request(
    client: AsyncClient, admin_token: str, student_token: str
):
    """cancel (นักศึกษายกเลิกเอง) ก็ไม่เคยเซ็ต returned=True เหมือนกัน — ต้องลบได้เช่นกัน"""
    h_admin = auth(admin_token)
    h_student = auth(student_token)
    eq_id = await _make_equipment(client, h_admin)
    req_id = await _make_request(client, h_student, eq_id)
    try:
        assert (await client.patch(f"/borrow-requests/{req_id}/cancel", headers=h_student)).status_code == 200
        assert (await client.delete(f"/equipment/{eq_id}", headers=h_admin)).status_code == 204  # retire

        r = await client.delete(f"/equipment/{eq_id}/permanent", headers=h_admin)
        assert r.status_code == 204, r.text
    finally:
        await _cleanup(eq_id, req_id)


async def test_delete_equipment_blocked_when_referenced_by_bundle(
    client: AsyncClient, admin_token: str
):
    """อุปกรณ์ที่เป็นสมาชิกชุดอุปกรณ์ (bundle) ต้องลบไม่ได้ ด้วย 400 อ่านเข้าใจ ไม่ใช่ 500"""
    h = auth(admin_token)
    eq_id = await _make_equipment(client, h)
    bundle_id = None
    try:
        r = await client.post("/bundles", headers=h, json={
            "name": "ชุดทดสอบกันลบ",
            "items": [{"equipment_id": eq_id, "quantity": 1}],
        })
        assert r.status_code == 201, r.text
        bundle_id = r.json()["id"]

        assert (await client.delete(f"/equipment/{eq_id}", headers=h)).status_code == 204  # retire
        r = await client.delete(f"/equipment/{eq_id}/permanent", headers=h)
        assert r.status_code == 400
        assert "ชุดอุปกรณ์" in r.json()["detail"]
    finally:
        if bundle_id:
            async with AsyncSessionLocal() as db:
                await db.execute(delete(AuditLog).where(AuditLog.target_id == uuid.UUID(bundle_id)))
                await db.execute(delete(BundleItem).where(BundleItem.bundle_id == uuid.UUID(bundle_id)))
                await db.execute(delete(Bundle).where(Bundle.id == uuid.UUID(bundle_id)))
                await db.commit()
        await _cleanup(eq_id)


async def test_borrow_item_snapshot_set_at_creation_and_refreshed_at_approval(
    client: AsyncClient, admin_token: str, student_token: str
):
    """snapshot ต้องมีค่าตั้งแต่สร้างคำขอ (pending) และเขียนทับเป็นค่าของหน่วยที่จัดสรรจริงตอนอนุมัติ

    ใช้กลุ่มอุปกรณ์ 2 หน่วยชื่อ/ประเภทเดียวกัน — เมื่อสองคำขอผูกหน่วยรหัสต่ำสุดตัวเดียวกันตอนยื่น
    (พฤติกรรมจริงตอนยื่นพร้อมกัน) คำขอที่สองต้องถูกจัดสรรหน่วยอื่นตอนอนุมัติ (chosen.id != eq.id)
    ยืนยันว่า snapshot คอลัมน์เปลี่ยนตาม chosen ไม่ใช่ eq เดิมที่ผูกไว้ตอนยื่น
    """
    h_admin = auth(admin_token)
    h_student = auth(student_token)
    tag = uuid.uuid4().hex[:6].upper()
    group_name = f"กลุ่มทดสอบ snapshot {tag}"
    eq_ids: list[str] = []
    async with AsyncSessionLocal() as db:
        for i in range(1, 3):
            r_id = uuid.uuid4()
            db.add(Equipment(
                id=r_id, code=f"SNAP-{tag}-{i:03d}", name=group_name,
                item_type="durable", quantity_total=1, quantity_available=1, status="available",
            ))
            eq_ids.append(str(r_id))
        await db.commit()

    req_ids: list[str] = []
    try:
        for _ in range(2):
            req_ids.append(await _make_request(client, h_student, eq_ids[0]))

        async with AsyncSessionLocal() as db:
            item = (await db.execute(
                select(BorrowItem).where(BorrowItem.borrow_request_id == uuid.UUID(req_ids[0]))
            )).scalar_one()
            assert item.equipment_name == group_name
            assert item.equipment_code is not None  # snapshot ตั้งแต่สร้างคำขอ ไม่ใช่ None

        for req_id in req_ids:
            assert (await client.patch(f"/borrow-requests/{req_id}/approve", headers=h_admin)).status_code == 200

        async with AsyncSessionLocal() as db:
            item_a = (await db.execute(
                select(BorrowItem).where(BorrowItem.borrow_request_id == uuid.UUID(req_ids[0]))
            )).scalar_one()
            item_b = (await db.execute(
                select(BorrowItem).where(BorrowItem.borrow_request_id == uuid.UUID(req_ids[1]))
            )).scalar_one()
            assert item_a.equipment_id != item_b.equipment_id, "สองคำขอต้องได้คนละหน่วยหลังอนุมัติ"
            # snapshot ของแต่ละ item ต้องตรงกับหน่วยที่ได้จริง (chosen) ไม่ใช่หน่วยที่ผูกไว้ตอนยื่น
            eq_map = {eq_ids[0]: f"SNAP-{tag}-001", eq_ids[1]: f"SNAP-{tag}-002"}
            assert item_a.equipment_code == eq_map[str(item_a.equipment_id)]
            assert item_b.equipment_code == eq_map[str(item_b.equipment_id)]
    finally:
        async with AsyncSessionLocal() as db:
            for req_id in req_ids:
                await db.execute(delete(Notification).where(Notification.borrow_request_id == uuid.UUID(req_id)))
                await db.execute(delete(BorrowItem).where(BorrowItem.borrow_request_id == uuid.UUID(req_id)))
                await db.execute(delete(BorrowRequest).where(BorrowRequest.id == uuid.UUID(req_id)))
            await db.execute(delete(Equipment).where(Equipment.id.in_([uuid.UUID(i) for i in eq_ids])))
            await db.commit()
