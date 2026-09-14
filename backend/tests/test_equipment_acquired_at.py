"""วันที่ได้มา (acquired_at) — อายุอุปกรณ์ต้องไม่รีเซ็ตตอนแยกรายชิ้น และของที่ซื้อเพิ่มต้องนับอายุใหม่

feedback อาจารย์: "ต้องรู้ว่าอุปกรณ์ชิ้นนั้นเข้ามาสู่ระบบตั้งแต่วันไหน" — created_at ใช้แทนไม่ได้เพราะ
split/restock สร้างแถวใหม่ทำให้วันที่รีเซ็ต ไฟล์นี้คือ regression ตรงของปัญหานั้น

หมายเหตุ: conftest.py มี PYTEST_ALLOW_DB=1 รันใส่ DB dev จริง — ทุกเทสต้อง cleanup ใน finally เสมอ
"""
import uuid
from datetime import date

from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.equipment import Equipment
from tests.conftest import auth

OLD_DATE = "2020-06-05"  # วันที่จริงจากไฟล์ทะเบียนคณะ (ล็อตแรกสุด)


async def _make(client: AsyncClient, h: dict, **overrides) -> dict:
    suffix = uuid.uuid4().hex[:6].upper()
    body = {
        "code": f"AGE-{suffix}", "name": f"อุปกรณ์ทดสอบอายุ {suffix}",
        "category_ids": [], "item_type": "material", "quantity_total": 1,
        "image_urls": ["/uploads/test.jpg"], "unit_value": 2000, "acquired_at": OLD_DATE,
    }
    body.update(overrides)
    r = await client.post("/equipment", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


async def _cleanup_by_name(name: str) -> None:
    async with AsyncSessionLocal() as db:
        eq_ids = (await db.execute(select(Equipment.id).where(Equipment.name == name))).scalars().all()
        if not eq_ids:
            return
        await db.execute(delete(AuditLog).where(AuditLog.target_id.in_(eq_ids)))
        await db.execute(delete(Equipment).where(Equipment.id.in_(eq_ids)))
        await db.commit()


async def test_create_stores_acquired_at_and_reports_age(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    name = f"อุปกรณ์ทดสอบอายุสร้าง {uuid.uuid4().hex[:6]}"
    eq = await _make(client, h, name=name)
    try:
        assert eq["acquired_at"] == OLD_DATE
        # created_at (วันที่บันทึกเข้าระบบ) ต้องเป็นคนละค่ากับวันที่ได้มา ไม่ใช่ตัวเดียวกัน
        assert not eq["created_at"].startswith(OLD_DATE)
    finally:
        await _cleanup_by_name(name)


async def test_split_keeps_acquired_at_on_every_unit(client: AsyncClient, admin_token: str):
    """แยกแถวรวมเป็นรายชิ้น = ของชิ้นเดิม ทุกหน่วยต้องได้วันที่ได้มาเดิม ไม่ใช่วันที่กดแยก"""
    h = auth(admin_token)
    name = f"วัสดุทดสอบแยกอายุ {uuid.uuid4().hex[:6]}"
    eq = await _make(client, h, name=name, item_type="material", quantity_total=3)
    try:
        r = await client.post(f"/equipment/{eq['id']}/split", headers=h)
        assert r.status_code == 200, r.text
        units = r.json()
        assert len(units) == 3
        assert all(u["acquired_at"] == OLD_DATE for u in units), [u["acquired_at"] for u in units]
        assert all(u["unit_value"] == 2000 for u in units)
    finally:
        await _cleanup_by_name(name)


async def test_restock_new_units_start_their_own_age_today(client: AsyncClient, admin_token: str):
    """เติมของเข้าคลัง = ซื้อของใหม่ หน่วยใหม่ต้องเริ่มนับอายุวันนี้ ไม่ใช่แก่เท่าของเดิมทันที"""
    h = auth(admin_token)
    name = f"ครุภัณฑ์ทดสอบเติมอายุ {uuid.uuid4().hex[:6]}"
    eq = await _make(client, h, name=name, item_type="durable",
                     code=f"{uuid.uuid4().int % 10**15:015d}", quantity_total=1)
    try:
        r = await client.post(f"/equipment/{eq['id']}/restock", json={"count": 2}, headers=h)
        assert r.status_code == 200, r.text
        new_units = r.json()
        assert len(new_units) == 2
        today = date.today().isoformat()
        assert all(u["acquired_at"] == today for u in new_units), [u["acquired_at"] for u in new_units]
        # ราคายังสืบทอดมาจากต้นแบบ (ไม่ให้ค่าหาย) แต่วันที่ต้องเป็นของใหม่
        assert all(u["unit_value"] == 2000 for u in new_units)
    finally:
        await _cleanup_by_name(name)


async def test_no_price_and_no_acquired_at_filters(
    client: AsyncClient, admin_token: str, superadmin_token: str,
):
    """ตัวกรอง "ยังไม่มีราคา"/"ยังไม่มีวันที่ได้มา" ใช้ไล่เติมข้อมูลของเก่าที่ทะเบียนไม่มี"""
    h = auth(admin_token)
    name = f"อุปกรณ์ทดสอบตัวกรองราคา {uuid.uuid4().hex[:6]}"
    eq = await _make(client, h, name=name)
    try:
        # ล้างค่าลงตรง ๆ ที่ DB — API บล็อกการล้างราคาไว้โดยตั้งใจ (ดู test_equipment_book_value)
        # จำลองแถวเก่าจากทะเบียนที่ไม่เคยมีทั้งราคาและวันที่
        async with AsyncSessionLocal() as db:
            row = (await db.execute(select(Equipment).where(Equipment.id == uuid.UUID(eq["id"])))).scalar_one()
            row.unit_value = None
            row.acquired_at = None
            await db.commit()

        for flt in ("no_price", "no_acquired_at"):
            for path in ("/equipment", "/equipment/grouped"):
                r = await client.get(path, params={"status": flt, "search": name, "page_size": 50}, headers=h)
                assert r.status_code == 200, r.text
                codes = [i["code"] for i in r.json()["items"]]
                assert eq["code"] in codes, f"{flt} ที่ {path} ต้องเจอแถวที่ยังว่าง"

        # เติมราคากลับแล้วต้องหลุดจากตัวกรอง no_price
        # ราคาเป็นฟิลด์การเงิน — แก้ได้เฉพาะ superadmin ตั้งแต่เฟส 8 (ดู equipment_service.FINANCE_FIELDS)
        assert (await client.patch(f"/equipment/{eq['id']}", json={"unit_value": 999},
                                   headers=auth(superadmin_token))).status_code == 200
        r = await client.get("/equipment", params={"status": "no_price", "search": name}, headers=h)
        assert eq["code"] not in [i["code"] for i in r.json()["items"]]
    finally:
        await _cleanup_by_name(name)
