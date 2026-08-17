"""ค้นหาด้วยรหัส + ห้ามยืมของที่ status ไม่ available (ทุกชนิด ไม่ใช่แค่ครุภัณฑ์) + หมวดวัสดุจากรหัส"""
import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.equipment import Equipment
from app.services.import_service import _categorize
from tests.conftest import auth


@pytest_asyncio.fixture(loop_scope="session")
async def blocked_material():
    """วัสดุที่ยังมีของในสต็อก แต่แอดมินตั้งเป็น 'ไม่อนุญาตให้ยืม'"""
    eq_id = uuid.uuid4()
    code = f"22{uuid.uuid4().hex[:4]}"
    async with AsyncSessionLocal() as db:
        db.add(Equipment(
            id=eq_id, code=code, name=f"บอร์ดห้ามยืม {code}",
            item_type="material", quantity_total=3, quantity_available=3,
            status="unavailable",
        ))
        await db.commit()
    yield eq_id, code
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Equipment).where(Equipment.id == eq_id))
        await db.commit()


@pytest.mark.asyncio(loop_scope="session")
async def test_search_by_code(client: AsyncClient, student_token: str, blocked_material):
    _, code = blocked_material
    r = await client.get("/equipment", params={"search": code}, headers=auth(student_token))
    assert r.status_code == 200
    assert [i["code"] for i in r.json()["items"]] == [code]


@pytest.mark.asyncio(loop_scope="session")
async def test_cannot_borrow_unavailable_material(client: AsyncClient, student_token: str, blocked_material):
    eq_id, _ = blocked_material
    r = await client.post("/borrow-requests", headers=auth(student_token), json={
        "purpose": "ทดสอบห้ามยืม", "requested_due_date": "2099-01-01", "items": [{"equipment_id": str(eq_id), "quantity": 1}],
    })
    assert r.status_code == 400
    assert "not available" in r.json()["detail"]


@pytest_asyncio.fixture(loop_scope="session")
async def fixed_asset():
    """โต๊ะ — อยู่ในทะเบียน สถานะปกติ มีของ แต่เป็นของประจำห้อง ห้ามยืมออก"""
    eq_id = uuid.uuid4()
    async with AsyncSessionLocal() as db:
        db.add(Equipment(
            id=eq_id, code=f"67-214-003-001-{uuid.uuid4().hex[:4]}", name="โต๊ะเรียน (ทดสอบ)",
            item_type="durable", quantity_total=1, quantity_available=1,
            status="available", is_borrowable=False,
        ))
        await db.commit()
    yield eq_id
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Equipment).where(Equipment.id == eq_id))
        await db.commit()


@pytest.mark.asyncio(loop_scope="session")
async def test_cannot_borrow_fixed_asset(client: AsyncClient, student_token: str, fixed_asset):
    r = await client.post("/borrow-requests", headers=auth(student_token), json={
        "purpose": "ทดสอบยืมโต๊ะ", "requested_due_date": "2099-01-01", "items": [{"equipment_id": str(fixed_asset), "quantity": 1}],
    })
    assert r.status_code == 400
    assert "not lendable" in r.json()["detail"]


def test_categorize_material_by_code_prefix():
    assert _categorize("Arduino Nano", "220015", "material") == "บอร์ด/ไมโครคอนโทรลเลอร์"
    assert _categorize("ตะกั่ว", "340002", "material") == "อุปกรณ์อิเล็กทรอนิกส์/เครื่องมือวัด"
    # ครุภัณฑ์ไม่ใช้รหัสจัดหมวด (2 หลักแรกคือปีงบ) — ต้องเดาจากชื่อเหมือนเดิม
    assert _categorize("โต๊ะเรียน", "67-214-003-001-0017", "durable") == "โต๊ะ/ตู้/เฟอร์นิเจอร์"
