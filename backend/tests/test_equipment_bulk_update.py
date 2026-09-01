"""Tests: แก้ไขหลายหน่วยพร้อมกัน (Phase B feature 3 + ขยายเพิ่ม name/item_type/category_ids)

all-or-nothing ต่างจาก bulk-delete — การแก้ location/status ไม่มีเหตุผลที่ควร "แก้ได้บางชิ้น"
ฟิลด์ปลอดภัย (location/description/image_urls/unit/unit_value/low_stock_threshold/status/is_borrowable/
name/item_type/category_ids) เท่านั้น — code/serial_number/quantity_* (unique/นับสต็อกต่อหน่วย)
ต้อง reject เงียบ ๆ ผ่าน Pydantic (ไม่อยู่ใน schema)
"""
import uuid

from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.equipment import Equipment
from tests.conftest import auth


async def _make_equipment(client: AsyncClient, admin_header: dict, **overrides) -> str:
    suffix = uuid.uuid4().hex[:6].upper()
    body = {
        "code": f"{uuid.uuid4().int % 10**15:015d}", "name": f"อุปกรณ์ทดสอบแก้หลายรายการ {suffix}",
        "category_ids": [], "item_type": "durable", "quantity_total": 1,
        "location": "เดิม", "image_urls": ["/uploads/test.jpg"],
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


async def test_bulk_update_location_succeeds_with_single_audit_entry(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    ids = [await _make_equipment(client, h) for _ in range(2)]
    try:
        r = await client.patch("/equipment/bulk-update", json={
            "equipment_ids": ids, "update": {"location": "ตู้ใหม่"},
        }, headers=h)
        assert r.status_code == 200, r.text
        body = r.json()
        assert {u["id"] for u in body["updated"]} == set(ids)
        assert all(u["location"] == "ตู้ใหม่" for u in body["updated"])

        async with AsyncSessionLocal() as db:
            log = (await db.execute(
                select(AuditLog).where(
                    AuditLog.action == "bulk_update_equipment", AuditLog.target_id == uuid.UUID(ids[0])
                )
            )).scalars().first()
            assert log is not None
            assert log.detail["count"] == 2
            assert set(log.detail["equipment_ids"]) == set(ids)
    finally:
        await _cleanup(*ids)


async def test_bulk_update_unselected_fields_untouched(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    eq_id = await _make_equipment(client, h, description="คำอธิบายเดิม")
    try:
        r = await client.patch("/equipment/bulk-update", json={
            "equipment_ids": [eq_id], "update": {"location": "ตู้ใหม่"},
        }, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["updated"][0]["description"] == "คำอธิบายเดิม"
    finally:
        await _cleanup(eq_id)


async def test_bulk_update_unsafe_field_silently_dropped(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    eq_id = await _make_equipment(client, h)
    original_code = (await client.get(f"/equipment/{eq_id}", headers=h)).json()["code"]
    try:
        r = await client.patch("/equipment/bulk-update", json={
            "equipment_ids": [eq_id], "update": {"location": "ตู้ใหม่", "code": "SHOULD-NOT-APPLY"},
        }, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["updated"][0]["code"] == original_code
    finally:
        await _cleanup(eq_id)


async def test_bulk_update_nonexistent_id_returns_404(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    eq_id = await _make_equipment(client, h)
    try:
        r = await client.patch("/equipment/bulk-update", json={
            "equipment_ids": [eq_id, str(uuid.uuid4())], "update": {"location": "ตู้ใหม่"},
        }, headers=h)
        assert r.status_code == 404
    finally:
        await _cleanup(eq_id)


async def test_bulk_update_nothing_to_change_rejected(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    eq_id = await _make_equipment(client, h)
    try:
        r = await client.patch("/equipment/bulk-update", json={
            "equipment_ids": [eq_id], "update": {},
        }, headers=h)
        assert r.status_code == 400
    finally:
        await _cleanup(eq_id)


async def test_bulk_update_name_and_item_type_succeeds(client: AsyncClient, admin_token: str):
    """name/item_type ปลอดภัยเพราะไม่มี unique constraint — ตั้งค่าเดียวกันให้หลายแถวได้เหมือน location"""
    h = auth(admin_token)
    ids = [await _make_equipment(client, h, item_type="material") for _ in range(2)]
    try:
        r = await client.patch("/equipment/bulk-update", json={
            "equipment_ids": ids, "update": {"name": "ชื่อใหม่รวม", "item_type": "durable"},
        }, headers=h)
        assert r.status_code == 200, r.text
        assert all(u["name"] == "ชื่อใหม่รวม" and u["item_type"] == "durable" for u in r.json()["updated"])
    finally:
        await _cleanup(*ids)


async def test_bulk_update_category_ids_replaces_existing(
    client: AsyncClient, admin_token: str, test_category,
):
    """category_ids แทนที่ชุดหมวดหมู่เดิมทั้งหมด (เหมือน update_equipment แก้ทีละหน่วย) ไม่ใช่เพิ่มเข้าไป"""
    h = auth(admin_token)
    old_cat = (await client.post("/equipment-categories", json={"name": f"cat_old_{uuid.uuid4().hex[:6]}"}, headers=h)).json()
    ids = [await _make_equipment(client, h, category_ids=[old_cat["id"]]) for _ in range(2)]
    try:
        r = await client.patch("/equipment/bulk-update", json={
            "equipment_ids": ids, "update": {"category_ids": [str(test_category.id)]},
        }, headers=h)
        assert r.status_code == 200, r.text
        for u in r.json()["updated"]:
            cat_ids = {c["id"] for c in u["categories"]}
            assert cat_ids == {str(test_category.id)}, "ต้องแทนที่ทั้งหมด ไม่ใช่หมวดเดิมค้างอยู่"
    finally:
        await _cleanup(*ids)
        async with AsyncSessionLocal() as db:
            from app.models.equipment_category import EquipmentCategory
            await db.execute(delete(EquipmentCategory).where(EquipmentCategory.id == uuid.UUID(old_cat["id"])))
            await db.commit()


async def test_bulk_update_forbidden_for_student(client: AsyncClient, admin_token: str, student_token: str):
    h_admin = auth(admin_token)
    h_student = auth(student_token)
    eq_id = await _make_equipment(client, h_admin)
    try:
        r = await client.patch("/equipment/bulk-update", json={
            "equipment_ids": [eq_id], "update": {"location": "ตู้ใหม่"},
        }, headers=h_student)
        assert r.status_code == 403
    finally:
        await _cleanup(eq_id)
