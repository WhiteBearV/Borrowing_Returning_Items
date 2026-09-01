"""เติมของเข้าคลัง (restock_equipment) — POST /equipment/{id}/restock

เดิมมีแต่ฟอร์มแก้ไขที่ต้องพิมพ์ยอดรวมใหม่ทั้งหมด (ไม่ใช่จำนวนที่ซื้อเพิ่ม) พิมพ์ผิดแล้วต่ำกว่าเดิมจะโดน
down-clamp ใน update_equipment ทำสต็อกหายจริง (ผู้ใช้เจอเอง: พิมพ์ "7" หวังจะบวกเพิ่ม กลายเป็นตั้งยอดรวม
เป็น 7 แทน) endpoint นี้รับแค่ "จะเพิ่มกี่ชิ้น" แล้วให้ backend ตัดสินเองว่าบวกเข้าแถวเดิม (ก้อน/สิ้นเปลือง)
หรือสร้างแถวใหม่แยกรหัส (ครุภัณฑ์/วัสดุที่แยกรายชิ้นแล้ว)

หมายเหตุ: conftest.py มี PYTEST_ALLOW_DB=1 รันใส่ DB dev จริง — ทุกเทสต้อง cleanup ใน finally เสมอ
"""
import uuid

from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.borrow_item import BorrowItem
from app.models.equipment import Equipment
from tests.conftest import auth


async def _make_equipment(client: AsyncClient, admin_header: dict, **overrides) -> str:
    suffix = uuid.uuid4().hex[:6].upper()
    body = {
        "code": f"{uuid.uuid4().int % 10**15:015d}", "name": f"อุปกรณ์ทดสอบเติมของ {suffix}",
        "category_ids": [], "item_type": "durable", "quantity_total": 1,
        "image_urls": ["/uploads/test.jpg"],
    }
    body.update(overrides)
    r = await client.post("/equipment", json=body, headers=admin_header)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _cleanup_by_name(name: str) -> None:
    async with AsyncSessionLocal() as db:
        eq_ids = (await db.execute(select(Equipment.id).where(Equipment.name == name))).scalars().all()
        if not eq_ids:
            return
        await db.execute(delete(BorrowItem).where(BorrowItem.equipment_id.in_(eq_ids)))
        await db.execute(delete(AuditLog).where(AuditLog.target_id.in_(eq_ids)))
        await db.execute(delete(Equipment).where(Equipment.id.in_(eq_ids)))
        await db.commit()


async def test_restock_consumable_adds_to_same_row(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    name = f"วัสดุสิ้นเปลืองทดสอบเติม {uuid.uuid4().hex[:6]}"
    eq_id = await _make_equipment(client, h, name=name, item_type="consumable", quantity_total=12)
    try:
        # จำลองว่าถูกใช้ไปแล้ว 4 (คงเหลือ 8/12) ก่อนซื้อมาเพิ่ม
        assert (await client.patch(f"/equipment/{eq_id}", json={"quantity_total": 8}, headers=h)).status_code == 200

        r = await client.post(f"/equipment/{eq_id}/restock", json={"count": 7}, headers=h)
        assert r.status_code == 200, r.text
        rows = r.json()
        assert len(rows) == 1 and rows[0]["id"] == eq_id
        assert rows[0]["quantity_total"] == 15 and rows[0]["quantity_available"] == 15
    finally:
        await _cleanup_by_name(name)


async def test_restock_unsplit_material_bulk_adds_to_same_row(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    name = f"วัสดุก้อนทดสอบเติม {uuid.uuid4().hex[:6]}"
    eq_id = await _make_equipment(client, h, name=name, item_type="material", quantity_total=5)
    try:
        r = await client.post(f"/equipment/{eq_id}/restock", json={"count": 3}, headers=h)
        assert r.status_code == 200, r.text
        rows = r.json()
        assert len(rows) == 1 and rows[0]["id"] == eq_id
        assert rows[0]["quantity_total"] == 8 and rows[0]["quantity_available"] == 8
    finally:
        await _cleanup_by_name(name)


async def test_restock_already_split_material_creates_new_rows(client: AsyncClient, admin_token: str, test_category):
    h = auth(admin_token)
    name = f"วัสดุแยกชิ้นทดสอบเติม {uuid.uuid4().hex[:6]}"
    eq_id = await _make_equipment(
        client, h, name=name, item_type="material", quantity_total=1,
        category_ids=[str(test_category.id)], location="15310", unit="ชิ้น",
    )
    try:
        r = await client.post(f"/equipment/{eq_id}/restock", json={"count": 3}, headers=h)
        assert r.status_code == 200, r.text
        rows = r.json()
        assert len(rows) == 3, "ต้องได้แถวใหม่ 3 แถวแยกรหัส ไม่ใช่บวกเข้าแถวเดิม"
        codes = {row["code"] for row in rows}
        assert len(codes) == 3  # รหัสไม่ซ้ำกัน
        for row in rows:
            assert row["id"] != eq_id
            assert row["quantity_total"] == 1 and row["quantity_available"] == 1
            assert row["name"] == name and row["item_type"] == "material"
            assert row["location"] == "15310" and row["unit"] == "ชิ้น"
            assert row["status"] == "available"

        # แถวเดิม (หน่วยที่ 1) ต้องไม่ถูกแตะ ยังเป็น 1/1 เหมือนเดิม
        original = (await client.get(f"/equipment/{eq_id}", headers=h)).json()
        assert original["quantity_total"] == 1 and original["quantity_available"] == 1
    finally:
        await _cleanup_by_name(name)


async def test_restock_durable_always_creates_new_rows(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    name = f"ครุภัณฑ์ทดสอบเติม {uuid.uuid4().hex[:6]}"
    eq_id = await _make_equipment(client, h, name=name, item_type="durable", quantity_total=1)
    try:
        r = await client.post(f"/equipment/{eq_id}/restock", json={"count": 2}, headers=h)
        assert r.status_code == 200, r.text
        rows = r.json()
        assert len(rows) == 2
        assert all(row["quantity_total"] == 1 for row in rows)
    finally:
        await _cleanup_by_name(name)


async def test_restock_rejects_zero_or_negative_count(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    name = f"อุปกรณ์ทดสอบเติมของผิด {uuid.uuid4().hex[:6]}"
    eq_id = await _make_equipment(client, h, name=name)
    try:
        r = await client.post(f"/equipment/{eq_id}/restock", json={"count": 0}, headers=h)
        assert r.status_code == 422
    finally:
        await _cleanup_by_name(name)


async def test_restock_forbidden_for_student(client: AsyncClient, admin_token: str, student_token: str):
    h_admin = auth(admin_token)
    name = f"อุปกรณ์ทดสอบเติมสิทธิ์ {uuid.uuid4().hex[:6]}"
    eq_id = await _make_equipment(client, h_admin, name=name)
    try:
        r = await client.post(f"/equipment/{eq_id}/restock", json={"count": 1}, headers=auth(student_token))
        assert r.status_code == 403
    finally:
        await _cleanup_by_name(name)
