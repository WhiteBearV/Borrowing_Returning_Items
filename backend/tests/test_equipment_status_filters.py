"""Tests: filter สถานะพิเศษ low_stock / borrowed ในหน้าจัดการอุปกรณ์ — เดิมต้องกดเข้ามาดูจาก dashboard เท่านั้น
ตอนนี้กรองตรงในหน้า /admin/equipment ได้เลย (mirror สูตร low_stock เดียวกับ dashboard_service.get_summary)

หมายเหตุ: conftest.py มี PYTEST_ALLOW_DB=1 รันใส่ DB dev จริง (ไม่ใช่ DB แยกต่างหาก) — ทุกเทสในไฟล์นี้ต้อง
ลบข้อมูลที่สร้างเองใน finally เสมอ ไม่งั้นจะกลายเป็นขยะค้างถาวรในคลังจริง (เจอปัญหานี้มาแล้วรอบหนึ่ง)
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


async def _make_equipment(client: AsyncClient, admin_header: dict, **overrides) -> str:
    suffix = uuid.uuid4().hex[:6].upper()
    body = {
        "code": f"STATFILT-{suffix}", "name": f"อุปกรณ์ทดสอบ filter {suffix}",
        "category_ids": [], "item_type": "durable", "quantity_total": 1,
        "image_urls": ["/uploads/test.jpg"],
    }
    body.update(overrides)
    r = await client.post("/equipment", json=body, headers=admin_header)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _cleanup(*eq_ids: str, req_id: str | None = None) -> None:
    async with AsyncSessionLocal() as db:
        if req_id:
            await db.execute(delete(Notification).where(Notification.borrow_request_id == uuid.UUID(req_id)))
            await db.execute(delete(BorrowItem).where(BorrowItem.borrow_request_id == uuid.UUID(req_id)))
            await db.execute(delete(BorrowRequest).where(BorrowRequest.id == uuid.UUID(req_id)))
        for eq_id in eq_ids:
            await db.execute(delete(BorrowItem).where(BorrowItem.equipment_id == uuid.UUID(eq_id)))
            await db.execute(delete(AuditLog).where(AuditLog.target_id == uuid.UUID(eq_id)))
            await db.execute(delete(Equipment).where(Equipment.id == uuid.UUID(eq_id)))
        await db.commit()


async def test_low_stock_filter_includes_consumable_below_threshold(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    low_id = await _make_equipment(client, h, item_type="consumable", quantity_total=2, low_stock_threshold=5)
    high_id = await _make_equipment(client, h, item_type="consumable", quantity_total=100, low_stock_threshold=5)
    durable_id = await _make_equipment(client, h, item_type="durable", quantity_total=1)
    try:
        r = await client.get("/equipment", params={"status": "low_stock", "page_size": 100}, headers=h)
        assert r.status_code == 200, r.text
        ids = {i["id"] for i in r.json()["items"]}
        assert low_id in ids
        assert high_id not in ids
        assert durable_id not in ids
    finally:
        await _cleanup(low_id, high_id, durable_id)


async def test_low_stock_filter_uses_default_threshold_when_unset(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    # ไม่ตั้ง low_stock_threshold รายชิ้น -> ใช้ default (seed migration 0018 = 5)
    below_default_id = await _make_equipment(client, h, item_type="consumable", quantity_total=3)
    try:
        r = await client.get("/equipment", params={"status": "low_stock", "page_size": 100}, headers=h)
        ids = {i["id"] for i in r.json()["items"]}
        assert below_default_id in ids
    finally:
        await _cleanup(below_default_id)


async def test_borrowed_filter_tracks_active_loan(client: AsyncClient, admin_token: str, student_token: str):
    h_admin = auth(admin_token)
    h_student = auth(student_token)
    eq_id = await _make_equipment(client, h_admin)
    req_id = None
    try:
        r = await client.get("/equipment", params={"status": "borrowed", "page_size": 100}, headers=h_admin)
        assert eq_id not in {i["id"] for i in r.json()["items"]}

        r = await client.post("/borrow-requests", headers=h_student, json={
            "requested_due_date": "2028-06-01",
            "items": [{"equipment_id": eq_id, "quantity": 1}],
        })
        req_id = r.json()["id"]
        assert (await client.patch(f"/borrow-requests/{req_id}/approve", headers=h_admin)).status_code == 200

        r = await client.get("/equipment", params={"status": "borrowed", "page_size": 100}, headers=h_admin)
        assert eq_id in {i["id"] for i in r.json()["items"]}

        item_id = (await client.get(f"/borrow-requests/{req_id}", headers=h_admin)).json()["items"][0]["id"]
        assert (await client.post(
            f"/borrow-requests/{req_id}/items/{item_id}/return",
            json={"condition_on_return": "ok"}, headers=h_admin,
        )).status_code == 200

        r = await client.get("/equipment", params={"status": "borrowed", "page_size": 100}, headers=h_admin)
        assert eq_id not in {i["id"] for i in r.json()["items"]}
    finally:
        await _cleanup(eq_id, req_id=req_id)


async def test_borrowed_filter_also_works_on_grouped_listing(client: AsyncClient, admin_token: str, student_token: str):
    h_admin = auth(admin_token)
    h_student = auth(student_token)
    eq_id = await _make_equipment(client, h_admin)
    req_id = None
    try:
        r = await client.post("/borrow-requests", headers=h_student, json={
            "requested_due_date": "2028-06-01",
            "items": [{"equipment_id": eq_id, "quantity": 1}],
        })
        req_id = r.json()["id"]
        assert (await client.patch(f"/borrow-requests/{req_id}/approve", headers=h_admin)).status_code == 200

        r = await client.get("/equipment/grouped", params={"status": "borrowed", "page_size": 100}, headers=h_admin)
        assert r.status_code == 200, r.text
        assert eq_id in {i["id"] for i in r.json()["items"]}
    finally:
        await _cleanup(eq_id, req_id=req_id)


async def test_return_damaged_syncs_equipment_status_for_single_unit(
    client: AsyncClient, admin_token: str, student_token: str
):
    """คืนของสภาพ damaged (หน่วยเดียว quantity_total=1) ต้องเปลี่ยน equipment.status ตามจริง
    ไม่ใช่ค้าง "available" ทั้งที่ของเสียไปแล้ว (บั๊กจริงที่เจอ — ดู test_is_currently_borrowed_... ด้านล่าง)
    """
    h_admin = auth(admin_token)
    h_student = auth(student_token)
    eq_id = await _make_equipment(client, h_admin)
    req_id = None
    try:
        r = await client.post("/borrow-requests", headers=h_student, json={
            "requested_due_date": "2028-06-01",
            "items": [{"equipment_id": eq_id, "quantity": 1}],
        })
        req_id = r.json()["id"]
        assert (await client.patch(f"/borrow-requests/{req_id}/approve", headers=h_admin)).status_code == 200
        item_id = (await client.get(f"/borrow-requests/{req_id}", headers=h_admin)).json()["items"][0]["id"]

        r = await client.post(
            f"/borrow-requests/{req_id}/items/{item_id}/return",
            json={"condition_on_return": "damaged", "damage_photo_urls": ["/uploads/dmg.jpg"]},
            headers=h_admin,
        )
        assert r.status_code == 200, r.text

        eq = (await client.get(f"/equipment/{eq_id}", headers=h_admin)).json()
        assert eq["status"] == "damaged"
    finally:
        await _cleanup(eq_id, req_id=req_id)


async def test_return_lost_syncs_equipment_status_to_unavailable(
    client: AsyncClient, admin_token: str, student_token: str
):
    """คืนของสภาพ lost (หน่วยเดียว) -> status="unavailable" (ตรงกับ import_service label "สูญหาย/เสื่อมสภาพ")"""
    h_admin = auth(admin_token)
    h_student = auth(student_token)
    eq_id = await _make_equipment(client, h_admin)
    req_id = None
    try:
        r = await client.post("/borrow-requests", headers=h_student, json={
            "requested_due_date": "2028-06-01",
            "items": [{"equipment_id": eq_id, "quantity": 1}],
        })
        req_id = r.json()["id"]
        assert (await client.patch(f"/borrow-requests/{req_id}/approve", headers=h_admin)).status_code == 200
        item_id = (await client.get(f"/borrow-requests/{req_id}", headers=h_admin)).json()["items"][0]["id"]

        r = await client.post(
            f"/borrow-requests/{req_id}/items/{item_id}/return",
            json={"condition_on_return": "lost", "damage_photo_urls": ["/uploads/lost.jpg"]},
            headers=h_admin,
        )
        assert r.status_code == 200, r.text

        eq = (await client.get(f"/equipment/{eq_id}", headers=h_admin)).json()
        assert eq["status"] == "unavailable"
    finally:
        await _cleanup(eq_id, req_id=req_id)


async def test_return_damaged_does_not_flip_status_for_unsplit_batch(
    client: AsyncClient, admin_token: str, student_token: str
):
    """ก้อนวัสดุ quantity_total>1 ที่ยังไม่แยกรายชิ้น — คืนเสีย 1 ชิ้นจากที่ยืมไป ต้องไม่ทำให้ทั้งก้อนโดนตีตรา
    "damaged" ไปด้วย (ก้อนยังมีของเหลืออีกหลายชิ้นที่ไม่เกี่ยวกับอันที่เสีย)"""
    h_admin = auth(admin_token)
    h_student = auth(student_token)
    eq_id = await _make_equipment(client, h_admin, item_type="material", quantity_total=5)
    req_id = None
    try:
        r = await client.post("/borrow-requests", headers=h_student, json={
            "requested_due_date": "2028-06-01",
            "items": [{"equipment_id": eq_id, "quantity": 1}],
        })
        req_id = r.json()["id"]
        assert (await client.patch(f"/borrow-requests/{req_id}/approve", headers=h_admin)).status_code == 200
        item_id = (await client.get(f"/borrow-requests/{req_id}", headers=h_admin)).json()["items"][0]["id"]

        r = await client.post(
            f"/borrow-requests/{req_id}/items/{item_id}/return",
            json={"condition_on_return": "damaged", "damage_photo_urls": ["/uploads/dmg.jpg"]},
            headers=h_admin,
        )
        assert r.status_code == 200, r.text

        eq = (await client.get(f"/equipment/{eq_id}", headers=h_admin)).json()
        assert eq["status"] == "available", "ก้อนที่เหลือ 4 ชิ้นยังยืมได้อยู่ ไม่ควรโดนตีตราเสียทั้งก้อน"
        assert eq["quantity_available"] == 4
    finally:
        await _cleanup(eq_id, req_id=req_id)


async def test_grouped_detail_shows_holder_name_and_student_number(
    client: AsyncClient, admin_token: str, student_token: str
):
    """หน้าจัดการอุปกรณ์ต้องเห็นว่าใครถือของอยู่ (ชื่อ+รหัสนักศึกษา) ไม่ใช่แค่รู้ว่า "ถูกยืมอยู่" เฉยๆ"""
    h_admin = auth(admin_token)
    h_student = auth(student_token)
    eq_id = await _make_equipment(client, h_admin)
    req_id = None
    try:
        r = await client.post("/borrow-requests", headers=h_student, json={
            "requested_due_date": "2028-06-01",
            "items": [{"equipment_id": eq_id, "quantity": 1}],
        })
        req_id = r.json()["id"]
        assert (await client.patch(f"/borrow-requests/{req_id}/approve", headers=h_admin)).status_code == 200

        r = await client.get(f"/equipment/grouped/{eq_id}", headers=h_admin)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["holder"]["holder_name"], "ต้องมีชื่อผู้ยืม"
        assert body["holder"]["student_number"] is not None, "ต้องมีรหัสนักศึกษาผู้ยืมด้วย ไม่ใช่แค่ชื่อ"
        assert len(body["holders"]) == 1
        assert body["members"][0]["holder"]["student_number"] == body["holder"]["student_number"]
    finally:
        await _cleanup(eq_id, req_id=req_id)


async def test_is_currently_borrowed_false_after_damaged_return_despite_stock_gap(
    client: AsyncClient, admin_token: str, student_token: str
):
    """บั๊กที่เจอจริง: คืนของสภาพ damaged ไม่คืนสต็อก (quantity_available < quantity_total ค้างถาวร)
    แต่ไม่มีใครถือของอยู่จริงแล้ว — is_currently_borrowed ต้องเป็น false ไม่ใช่ derive จากช่องว่างสต็อก
    (เคย derive แบบนั้นแล้วผิด: อุปกรณ์เก่าที่เคยเสียหาย/สูญหายขึ้น "ถูกยืม" ค้างตลอดไปทั้งที่คืนไปนานแล้ว)
    """
    h_admin = auth(admin_token)
    h_student = auth(student_token)
    eq_id = await _make_equipment(client, h_admin)
    req_id = None
    try:
        r = await client.post("/borrow-requests", headers=h_student, json={
            "requested_due_date": "2028-06-01",
            "items": [{"equipment_id": eq_id, "quantity": 1}],
        })
        req_id = r.json()["id"]
        assert (await client.patch(f"/borrow-requests/{req_id}/approve", headers=h_admin)).status_code == 200

        item_id = (await client.get(f"/borrow-requests/{req_id}", headers=h_admin)).json()["items"][0]["id"]
        r = await client.post(
            f"/borrow-requests/{req_id}/items/{item_id}/return",
            json={"condition_on_return": "damaged", "damage_photo_urls": ["/uploads/dmg.jpg"]},
            headers=h_admin,
        )
        assert r.status_code == 200, r.text

        eq = (await client.get(f"/equipment/{eq_id}", headers=h_admin)).json()
        assert eq["quantity_available"] < eq["quantity_total"], "damaged ไม่คืนสต็อก ต้องยังมีช่องว่างค้างอยู่"

        r = await client.get("/equipment/grouped", params={"search": eq["code"], "page_size": 100}, headers=h_admin)
        card = next(g for g in r.json()["items"] if g["id"] == eq_id)
        assert card["is_currently_borrowed"] is False, "คืนไปแล้ว (แม้สภาพ damaged) ต้องไม่ขึ้นว่าถูกยืมอยู่"
    finally:
        await _cleanup(eq_id, req_id=req_id)


async def test_borrowed_filter_grouped_totals_reflect_whole_group_not_just_borrowed_unit(
    client: AsyncClient, admin_token: str, student_token: str
):
    """บั๊กที่เจอจริง: กลุ่ม 2 หน่วย ยืมอยู่แค่ 1 หน่วย — การ์ดต้องโชว์ยอดรวมทั้งกลุ่ม (2 หน่วย เหลือ 1)
    ไม่ใช่แค่ยอดของหน่วยที่ถูกยืม (ซึ่งจะโชว์ผิดเป็น "0/1" เพราะ query เดิมกรองตัดหน่วยพี่น้องออกไปตั้งแต่ต้น)
    """
    h_admin = auth(admin_token)
    h_student = auth(student_token)
    tag = uuid.uuid4().hex[:6].upper()
    group_name = f"กลุ่มทดสอบยอดรวม {tag}"
    eq_a = await _make_equipment(client, h_admin, name=group_name, item_type="durable")
    eq_b = await _make_equipment(client, h_admin, name=group_name, item_type="durable")
    req_id = None
    try:
        r = await client.post("/borrow-requests", headers=h_student, json={
            "requested_due_date": "2028-06-01",
            "items": [{"equipment_id": eq_a, "quantity": 1}],
        })
        req_id = r.json()["id"]
        assert (await client.patch(f"/borrow-requests/{req_id}/approve", headers=h_admin)).status_code == 200

        r = await client.get(
            "/equipment/grouped", params={"status": "borrowed", "search": group_name, "page_size": 100}, headers=h_admin
        )
        assert r.status_code == 200, r.text
        matching = [g for g in r.json()["items"] if g["name"] == group_name]
        assert len(matching) == 1, "ต้องยุบเป็นการ์ดเดียว ไม่ใช่แยกเป็น 2 การ์ด"
        card = matching[0]
        assert card["unit_count"] == 2
        assert card["quantity_total"] == 2, "ต้องนับหน่วยพี่น้องที่ไม่ได้ถูกยืมด้วย ไม่ใช่แค่หน่วยที่ query เจอ"
        assert card["quantity_available"] == 1, "หน่วย eq_b ยังว่างอยู่ ต้องนับรวมด้วย"
    finally:
        await _cleanup(eq_a, eq_b, req_id=req_id)
