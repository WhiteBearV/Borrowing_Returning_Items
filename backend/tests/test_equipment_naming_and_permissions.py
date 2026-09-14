"""มาตรฐานการตั้งชื่อ + แยกสิทธิ์ฟอร์มอุปกรณ์ตามความเสี่ยง (เฟส 8 — feedback อาจารย์ ข้อ 15, 18, 17)

3 เรื่องที่ต้องไม่พัง:
- ค้นหา "DHT11" (ชื่อรุ่น) ต้องเจอของที่ชื่อเป็นภาษาไทย — ต้นตอของ "DHT11 คืออะไร" ที่อาจารย์ยกมา
- ผู้ดูแลคลังแก้ตัวเลขทะเบียน/การเงินของอุปกรณ์ที่มีอยู่แล้วไม่ได้ (กระทบใบยืมเก่า/ค่าเสียหายย้อนหลัง)
- เปลี่ยนสถานะอุปกรณ์ต้องมีเหตุผลกำกับเสมอ และเหตุผลต้องไปโผล่ใน audit
"""
import uuid
from datetime import date

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.equipment import Equipment
from app.models.equipment_category import EquipmentCategory
from app.models.equipment_part import EquipmentPart
from tests.conftest import auth


@pytest_asyncio.fixture(loop_scope="session")
async def named_equipment(test_category: EquipmentCategory):
    """ของที่ตั้งชื่อตามมาตรฐาน: ชื่อไทยอ่านรู้เรื่อง + เก็บชื่อรุ่นแยกช่อง"""
    eq_id = uuid.uuid4()
    async with AsyncSessionLocal() as db:
        cat = await db.get(EquipmentCategory, test_category.id)
        db.add(Equipment(
            id=eq_id, code=f"TEST-NAME-{eq_id.hex[:6].upper()}",
            name="เซ็นเซอร์อุณหภูมิและความชื้น (ทดสอบ)", categories=[cat],
            manufacturer="Aosong", model_number="DHT11-TESTONLY",
            item_type="material", quantity_total=2, quantity_available=2, status="available",
            unit_value=150, acquired_at=date.today(),
        ))
        await db.commit()
    yield eq_id
    async with AsyncSessionLocal() as db:
        await db.execute(delete(AuditLog).where(AuditLog.target_id == eq_id))
        await db.execute(delete(EquipmentPart).where(EquipmentPart.equipment_id == eq_id))
        await db.execute(delete(Equipment).where(Equipment.id == eq_id))
        await db.commit()


@pytest.mark.asyncio(loop_scope="session")
async def test_search_finds_equipment_by_model_number(
    client: AsyncClient, admin_token: str, named_equipment,
):
    """ค้นด้วยชื่อรุ่นต้องเจอ ทั้งที่ชื่ออุปกรณ์เป็นภาษาไทยล้วน (และค้นด้วยคำไทยก็ยังเจอเหมือนเดิม)"""
    by_model = await client.get("/equipment", params={"search": "DHT11-TESTONLY"}, headers=auth(admin_token))
    assert by_model.status_code == 200, by_model.text
    assert any(r["id"] == str(named_equipment) for r in by_model.json()["items"])

    by_thai = await client.get("/equipment", params={"search": "เซ็นเซอร์อุณหภูมิและความชื้น (ทดสอบ)"},
                               headers=auth(admin_token))
    assert any(r["id"] == str(named_equipment) for r in by_thai.json()["items"])

    row = next(r for r in by_model.json()["items"] if r["id"] == str(named_equipment))
    assert row["manufacturer"] == "Aosong" and row["model_number"] == "DHT11-TESTONLY"


@pytest.mark.asyncio(loop_scope="session")
async def test_finance_fields_are_superadmin_only(
    client: AsyncClient, admin_token: str, superadmin_token: str, named_equipment,
):
    """ผู้ดูแลคลังแก้ราคา/วันที่ได้มา/อายุ/มูลค่าตามบัญชีของของเดิมไม่ได้ — superadmin เท่านั้น"""
    url = f"/equipment/{named_equipment}"
    for field, value in [("unit_value", 999), ("acquired_at", "2020-01-01"),
                         ("useful_life_years", 9), ("book_value_override", 50)]:
        r = await client.patch(url, json={field: value}, headers=auth(admin_token))
        assert r.status_code == 403, f"{field} ต้องถูกกั้น: {r.text}"

    # ส่งค่าเดิมซ้ำมาไม่นับว่าแก้ — ฟอร์มส่งทั้งก้อนทุกครั้ง ถ้ากั้นแบบนั้นผู้ดูแลคลังแก้ชื่อไม่ได้เลย
    same = await client.patch(url, json={"unit_value": 150, "location": "ตู้ทดสอบ"}, headers=auth(admin_token))
    assert same.status_code == 200, same.text
    assert same.json()["location"] == "ตู้ทดสอบ"

    # superadmin แก้ได้จริง
    ok = await client.patch(url, json={"unit_value": 999}, headers=auth(superadmin_token))
    assert ok.status_code == 200, ok.text
    assert ok.json()["unit_value"] == 999


@pytest.mark.asyncio(loop_scope="session")
async def test_status_change_requires_reason_and_lands_in_audit(
    client: AsyncClient, admin_token: str, named_equipment,
):
    url = f"/equipment/{named_equipment}"
    no_reason = await client.patch(url, json={"status": "under_repair"}, headers=auth(admin_token))
    assert no_reason.status_code == 400

    ok = await client.patch(url, json={"status": "under_repair", "status_reason": "ส่งซ่อมศูนย์บริการ"},
                            headers=auth(admin_token))
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "under_repair"

    async with AsyncSessionLocal() as db:
        logs = (await db.execute(
            select(AuditLog).where(AuditLog.target_id == named_equipment,
                                   AuditLog.action == "update_equipment")
        )).scalars().all()
    assert any(log.detail.get("reason") == "ส่งซ่อมศูนย์บริการ" for log in logs), \
        "เหตุผลที่เปลี่ยนสถานะต้องอยู่ใน audit ไม่ใช่หายไปเฉย ๆ"

    # แก้ฟิลด์อื่นโดยไม่แตะสถานะ ไม่ต้องมีเหตุผล
    assert (await client.patch(url, json={"description": "หมายเหตุทดสอบ"},
                               headers=auth(admin_token))).status_code == 200


@pytest.mark.asyncio(loop_scope="session")
async def test_part_replacement_chain(client: AsyncClient, admin_token: str, named_equipment):
    """ชิ้นส่วนใหม่บอกได้ว่ามาแทนชิ้นไหน — ได้ไทม์ไลน์การอัพเกรดต่อเนื่อง"""
    base = f"/equipment/{named_equipment}/parts"
    first = await client.post(base, headers=auth(admin_token), json={
        "name": "SSD 256GB (ทดสอบ)", "acquired_at": str(date.today()), "unit_value": 1200,
    })
    assert first.status_code == 201, first.text
    old_id = first.json()["id"]

    second = await client.post(base, headers=auth(admin_token), json={
        "name": "SSD 512GB (ทดสอบ)", "acquired_at": str(date.today()), "unit_value": 2000,
        "replaces_part_id": old_id,
    })
    assert second.status_code == 201, second.text
    assert second.json()["replaces_part_id"] == old_id
    assert second.json()["replaces_part_name"] == "SSD 256GB (ทดสอบ)"

    listed = (await client.get(base, headers=auth(admin_token))).json()
    new_row = next(p for p in listed if p["id"] == second.json()["id"])
    assert new_row["replaces_part_name"] == "SSD 256GB (ทดสอบ)"

    # ชิ้นส่วนของเครื่องอื่นเอามาอ้างว่า "แทน" ไม่ได้ (กันไทม์ไลน์ข้ามเครื่อง)
    cross = await client.post(f"/equipment/{uuid.uuid4()}/parts", headers=auth(admin_token), json={
        "name": "ของเครื่องอื่น", "acquired_at": str(date.today()), "replaces_part_id": old_id,
    })
    assert cross.status_code == 404


@pytest.mark.asyncio(loop_scope="session")
async def test_bulk_update_enforces_same_rules(
    client: AsyncClient, admin_token: str, superadmin_token: str, named_equipment,
):
    """แก้หลายรายการพร้อมกันต้องไม่กลายเป็นทางลัดข้ามด่านสิทธิ์/เหตุผลของการแก้ทีละชิ้น"""
    ids = [str(named_equipment)]
    money = await client.patch("/equipment/bulk-update", headers=auth(admin_token),
                               json={"equipment_ids": ids, "update": {"unit_value": 777}})
    assert money.status_code == 403, money.text

    no_reason = await client.patch("/equipment/bulk-update", headers=auth(admin_token),
                                   json={"equipment_ids": ids, "update": {"status": "damaged"}})
    assert no_reason.status_code == 400, no_reason.text

    ok = await client.patch("/equipment/bulk-update", headers=auth(admin_token), json={
        "equipment_ids": ids, "update": {"status": "damaged"}, "status_reason": "ตกพื้นทั้งล็อต (ทดสอบ)",
    })
    assert ok.status_code == 200, ok.text
    # ผู้ดูแลคลังยังแก้ฟิลด์ทั่วไปหลายรายการได้ตามปกติ
    assert (await client.patch("/equipment/bulk-update", headers=auth(admin_token), json={
        "equipment_ids": ids, "update": {"model_number": "DHT11-BULK-TEST"},
    })).status_code == 200
