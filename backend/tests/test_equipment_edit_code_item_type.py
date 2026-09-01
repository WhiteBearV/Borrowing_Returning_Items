"""Tests: แก้ไข code/item_type ของอุปกรณ์ได้หลังสร้างแล้ว (Phase B feature 1)

เดิม EquipmentUpdate ไม่มี code/item_type เลย — บังคับ disabled ที่ฟอร์ม ทำให้กรอกผิดแล้วต้องลบสร้างใหม่
(ปัญหา DH-11 และอื่น ๆ ที่ report มา) แก้ได้อย่างปลอดภัยเพราะ BorrowItem เก็บ equipment_name/code/unit/
item_type_snapshot เป็น snapshot คอลัมน์จริง ไม่ใช่ live join — ประวัติการยืมเก่าไม่พังแม้แก้ทีหลัง

หมายเหตุ: conftest.py มี PYTEST_ALLOW_DB=1 รันใส่ DB dev จริง (ไม่ใช่ DB แยกต่างหาก) — ทุกเทสในไฟล์นี้ต้อง
ลบข้อมูลที่สร้างเองใน finally เสมอ ไม่งั้นจะกลายเป็นขยะค้างถาวรในคลังจริง (เจอปัญหานี้มาแล้วรอบหนึ่ง)
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
from tests.conftest import auth


async def _make_equipment(client: AsyncClient, admin_header: dict, **overrides) -> str:
    suffix = uuid.uuid4().hex[:6].upper()
    body = {
        "code": f"{uuid.uuid4().int % 10**15:015d}", "name": f"อุปกรณ์ทดสอบแก้ไข {suffix}",
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


async def test_update_equipment_code_success(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    eq_id = await _make_equipment(client, h)
    try:
        new_code = f"NEW-{uuid.uuid4().hex[:6].upper()}"

        r = await client.patch(f"/equipment/{eq_id}", json={"code": new_code}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["code"] == new_code

        async with AsyncSessionLocal() as db:
            log = (await db.execute(
                select(AuditLog).where(AuditLog.target_id == uuid.UUID(eq_id), AuditLog.action == "update_equipment")
            )).scalars().first()
            assert log.detail["changes"]["code"][1] == new_code
    finally:
        await _cleanup(eq_id)


async def test_update_equipment_code_duplicate_conflict(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    eq_id_a = await _make_equipment(client, h)
    eq_id_b = await _make_equipment(client, h)
    try:
        code_a = (await client.get(f"/equipment/{eq_id_a}", headers=h)).json()["code"]

        r = await client.patch(f"/equipment/{eq_id_b}", json={"code": code_a}, headers=h)
        assert r.status_code == 409
    finally:
        await _cleanup(eq_id_a, eq_id_b)


async def test_update_equipment_item_type_regroups(client: AsyncClient, admin_token: str):
    """แก้ item_type ของ 1 หน่วยในกลุ่ม 2 หน่วย -> ต้องแยกออกจากกลุ่มเดิม"""
    h = auth(admin_token)
    tag = uuid.uuid4().hex[:6].upper()
    group_name = f"กลุ่มทดสอบแก้ item_type {tag}"
    eq_a = await _make_equipment(client, h, name=group_name, item_type="durable")
    eq_b = await _make_equipment(client, h, name=group_name, item_type="durable")
    try:
        r = await client.get("/equipment/grouped", params={"search": group_name}, headers=h)
        group = next(g for g in r.json()["items"] if g["name"] == group_name)
        assert group["unit_count"] == 2

        assert (await client.patch(f"/equipment/{eq_b}", json={"item_type": "material"}, headers=h)).status_code == 200

        r = await client.get("/equipment/grouped", params={"search": group_name}, headers=h)
        matching = [g for g in r.json()["items"] if g["name"] == group_name]
        assert len(matching) == 2, "ต้องแยกเป็น 2 กลุ่ม (durable 1 หน่วย, material 1 หน่วย)"
        assert {g["unit_count"] for g in matching} == {1, 1}
    finally:
        await _cleanup(eq_a, eq_b)


async def test_update_equipment_increase_quantity_total_grows_available(
    client: AsyncClient, admin_token: str, student_token: str
):
    """เพิ่ม quantity_total ของวัสดุที่มีของถูกยืมอยู่บางส่วน -> quantity_available ต้องขยับตามส่วนต่างที่เพิ่ม
    ไม่ใช่ค้างที่เดิม (เจอบั๊กจริง — แอดมินนับของใหม่แล้วแก้ quantity_total ขึ้น แต่ของที่เพิ่มมาไม่เคยพร้อมยืม
    เพราะไม่มีช่องแก้ quantity_available ตรง ๆ ที่ไหนเลย ต้องพึ่ง service reconcile ให้)"""
    h_admin = auth(admin_token)
    h_student = auth(student_token)
    eq_id = await _make_equipment(client, h_admin, item_type="material", quantity_total=5)
    req_id = None
    try:
        r = await client.post("/borrow-requests", headers=h_student, json={
            "requested_due_date": "2028-06-01",
            "items": [{"equipment_id": eq_id, "quantity": 2}],
        })
        assert r.status_code == 201, r.text
        req_id = r.json()["id"]
        assert (await client.patch(f"/borrow-requests/{req_id}/approve", headers=h_admin)).status_code == 200

        eq = (await client.get(f"/equipment/{eq_id}", headers=h_admin)).json()
        assert eq["quantity_total"] == 5 and eq["quantity_available"] == 3  # 2 ถูกยืมอยู่

        r = await client.patch(f"/equipment/{eq_id}", json={"quantity_total": 8}, headers=h_admin)
        assert r.status_code == 200, r.text
        assert r.json()["quantity_total"] == 8
        assert r.json()["quantity_available"] == 6  # 3 เดิม + 3 ที่เพิ่มมาใหม่ ยังคง 2 ที่ถูกยืมอยู่แยกไว้
    finally:
        await _cleanup(eq_id, req_id=req_id)


async def test_update_equipment_can_clear_wrong_serial_number(client: AsyncClient, admin_token: str):
    """แอดมินกรอก SN ผิด ต้องลบออกได้ (ส่ง null) ไม่ใช่แค่แก้เป็นค่าอื่น (เจอบั๊กจริง: exclude_none
    เดิมตัด null ทิ้งเหมือนไม่ได้ส่งมา ล้างค่าที่เคยตั้งไว้ไม่ได้เลย)"""
    h = auth(admin_token)
    eq_id = await _make_equipment(client, h, serial_number=f"SN-{uuid.uuid4().hex[:8].upper()}")
    try:
        r = await client.patch(f"/equipment/{eq_id}", json={"serial_number": None}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["serial_number"] is None
    finally:
        await _cleanup(eq_id)


async def test_update_equipment_clear_serial_number_not_blocked_by_other_null_rows(
    client: AsyncClient, admin_token: str
):
    """หลาย equipment ที่ SN เป็น null พร้อมกันได้ (partial unique index เจาะจง WHERE NOT NULL) —
    ล้าง SN ของแถวหนึ่งต้องไม่ไปชน 409 กับแถวอื่นที่ก็เป็น null อยู่แล้ว"""
    h = auth(admin_token)
    eq_a = await _make_equipment(client, h)  # ไม่มี SN ตั้งแต่สร้าง
    eq_b = await _make_equipment(client, h, serial_number=f"SN-{uuid.uuid4().hex[:8].upper()}")
    try:
        r = await client.patch(f"/equipment/{eq_b}", json={"serial_number": None}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["serial_number"] is None
    finally:
        await _cleanup(eq_a, eq_b)


async def test_update_equipment_serial_number_still_rejects_real_duplicate(client: AsyncClient, admin_token: str):
    """แก้ไข SN ให้ซ้ำกับของชิ้นอื่นที่มี SN จริง (ไม่ใช่ null) ยังต้องโดน 409 เหมือนเดิม"""
    h = auth(admin_token)
    sn = f"SN-{uuid.uuid4().hex[:8].upper()}"
    eq_a = await _make_equipment(client, h, serial_number=sn)
    eq_b = await _make_equipment(client, h)
    try:
        r = await client.patch(f"/equipment/{eq_b}", json={"serial_number": sn}, headers=h)
        assert r.status_code == 409
    finally:
        await _cleanup(eq_a, eq_b)


async def test_update_equipment_item_type_does_not_break_active_loan_snapshot(
    client: AsyncClient, admin_token: str, student_token: str
):
    """แก้ equipment.item_type หลังยืมไปแล้ว -> item_type_snapshot เดิมไม่เปลี่ยน คืนของด้วย condition set เดิมได้"""
    h_admin = auth(admin_token)
    h_student = auth(student_token)
    eq_id = await _make_equipment(client, h_admin, item_type="durable")
    req_id = None
    try:
        r = await client.post("/borrow-requests", headers=h_student, json={
            "requested_due_date": "2028-06-01",
            "items": [{"equipment_id": eq_id, "quantity": 1}],
        })
        assert r.status_code == 201, r.text
        req_id = r.json()["id"]
        assert (await client.patch(f"/borrow-requests/{req_id}/approve", headers=h_admin)).status_code == 200

        # แก้ item_type ของอุปกรณ์เป็น consumable หลังอนุมัติไปแล้ว
        assert (await client.patch(f"/equipment/{eq_id}", json={"item_type": "consumable"}, headers=h_admin)).status_code == 200

        # item ยังต้อง validate ด้วย DURABLE_CONDITIONS เดิม (item_type_snapshot="durable") ไม่ใช่ consumable conditions
        item_id = (await client.get(f"/borrow-requests/{req_id}", headers=h_admin)).json()["items"][0]["id"]
        r2 = await client.post(
            f"/borrow-requests/{req_id}/items/{item_id}/return",
            json={"condition_on_return": "ok"}, headers=h_admin,
        )
        assert r2.status_code == 200, r2.text
    finally:
        await _cleanup(eq_id, req_id=req_id)
