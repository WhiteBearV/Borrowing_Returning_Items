"""ปรับยอดคงเหลือ (adjust_stock) — POST /equipment/{id}/adjust-stock

ต่างจาก restock (บวกเพิ่ม, ซื้อของใหม่) ตรงที่ตัวนี้ SET quantity_available ตรง ๆ ให้ตรงกับที่นับได้จริง
(เช่นของหายไปโดยไม่มีบันทึกยืม) — quantity_total ต้องไม่เปลี่ยน

หมายเหตุ: conftest.py มี PYTEST_ALLOW_DB=1 รันใส่ DB dev จริง — ทุกเทสต้อง cleanup ใน finally เสมอ
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
        "code": f"ADJ-{suffix}", "name": f"อุปกรณ์ทดสอบปรับยอด {suffix}",
        "category_ids": [], "item_type": "consumable", "quantity_total": 10,
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
        await db.execute(delete(AuditLog).where(AuditLog.target_id.in_(eq_ids)))
        await db.execute(delete(Equipment).where(Equipment.id.in_(eq_ids)))
        await db.commit()


async def test_adjust_stock_sets_available_without_touching_total(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    name = f"วัสดุทดสอบปรับยอดลง {uuid.uuid4().hex[:6]}"
    eq_id = await _make_equipment(client, h, name=name, quantity_total=10)
    try:
        r = await client.post(
            f"/equipment/{eq_id}/adjust-stock",
            json={"new_available": 6, "reason": "นับจริงแล้วขาด 4 ชิ้น"}, headers=h,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["quantity_available"] == 6
        assert body["quantity_total"] == 10
    finally:
        await _cleanup_by_name(name)


async def test_adjust_stock_rejects_above_total(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    name = f"วัสดุทดสอบปรับยอดเกิน {uuid.uuid4().hex[:6]}"
    eq_id = await _make_equipment(client, h, name=name, quantity_total=10)
    try:
        r = await client.post(
            f"/equipment/{eq_id}/adjust-stock",
            json={"new_available": 11, "reason": "เกินยอดรวม"}, headers=h,
        )
        assert r.status_code == 400
    finally:
        await _cleanup_by_name(name)


async def test_adjust_stock_requires_reason(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    name = f"วัสดุทดสอบไม่มีเหตุผล {uuid.uuid4().hex[:6]}"
    eq_id = await _make_equipment(client, h, name=name, quantity_total=10)
    try:
        r = await client.post(
            f"/equipment/{eq_id}/adjust-stock",
            json={"new_available": 5, "reason": ""}, headers=h,
        )
        assert r.status_code == 422
    finally:
        await _cleanup_by_name(name)


async def test_adjust_stock_forbidden_for_student(client: AsyncClient, admin_token: str, student_token: str):
    h_admin = auth(admin_token)
    name = f"วัสดุทดสอบปรับยอดสิทธิ์ {uuid.uuid4().hex[:6]}"
    eq_id = await _make_equipment(client, h_admin, name=name, quantity_total=10)
    try:
        r = await client.post(
            f"/equipment/{eq_id}/adjust-stock",
            json={"new_available": 5, "reason": "ทดสอบสิทธิ์"}, headers=auth(student_token),
        )
        assert r.status_code == 403
    finally:
        await _cleanup_by_name(name)
