"""แยกวัสดุ (material) ก้อนเดียวเป็นรายชิ้น — split_equipment_into_units() + POST /equipment/{id}/split

ครอบคลุม: เงื่อนไขปฏิเสธ (ไม่ใช่ material / quantity_total<=1 / มีของยืมอยู่), scheme สร้างรหัสใหม่
(ต่อเลขท้ายรัน / รหัสชนกัน / ไม่มีเลขท้าย), การคัดลอกข้อมูล (categories/รูป/location), audit log เดียว,
สิทธิ์ admin เท่านั้น, และยืนยันว่าหลังแยกแล้วยืมของจากกลุ่มนี้แยกเป็น BorrowItem คนละแถวคนละรหัสจริง
(ใช้กลไก find_group_members เดิมที่มีเทสอยู่แล้วใน test_equipment_group_race.py)
"""
import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import delete, select, update

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.borrow_item import BorrowItem
from app.models.borrow_request import BorrowRequest
from app.models.equipment import Equipment
from app.models.equipment_category import EquipmentCategory
from app.models.notification import Notification
from app.models.user import User
from app.services.equipment_service import _generate_split_codes, split_equipment_into_units
from tests.conftest import auth

SPLIT_NAME_PREFIX = "อุปกรณ์ทดสอบแยกรายชิ้น"


def _split_code(tag: str) -> str:
    """รหัสตัวเลขล้วนลงท้ายด้วยเลข — ใช้ทดสอบ scheme ต่อเลขท้ายรัน ('9' นำหน้ากันชนของจริงในทะเบียน"""
    return f"9{uuid.uuid4().int % 100000:05d}{tag}"


async def _cleanup_group(name: str) -> None:
    async with AsyncSessionLocal() as db:
        eq_ids = (await db.execute(select(Equipment.id).where(Equipment.name == name))).scalars().all()
        if not eq_ids:
            return
        req_ids = (await db.execute(
            select(BorrowItem.borrow_request_id).where(BorrowItem.equipment_id.in_(eq_ids))
        )).scalars().all()
        if req_ids:
            await db.execute(delete(Notification).where(Notification.borrow_request_id.in_(req_ids)))
            await db.execute(delete(BorrowItem).where(BorrowItem.borrow_request_id.in_(req_ids)))
            await db.execute(delete(BorrowRequest).where(BorrowRequest.id.in_(req_ids)))
        await db.execute(delete(AuditLog).where(AuditLog.target_id.in_(eq_ids)))
        await db.execute(delete(Equipment).where(Equipment.id.in_(eq_ids)))
        await db.commit()


@pytest_asyncio.fixture(loop_scope="session")
async def bulk_material(test_category: EquipmentCategory):
    """วัสดุก้อนเดียว quantity_total=5 ทุกหน่วยว่าง — มีรูป/หมวดหมู่/location ครบ ไว้เช็คว่าคัดลอกถูก"""
    tag = uuid.uuid4().hex[:6].upper()
    name = f"{SPLIT_NAME_PREFIX} {tag}"
    eq_id = uuid.uuid4()
    async with AsyncSessionLocal() as db:
        cat = await db.get(EquipmentCategory, test_category.id)
        eq = Equipment(
            id=eq_id, code=_split_code("0"), name=name, item_type="material",
            description="บอร์ดทดสอบแยกชิ้น",
            image_url="/uploads/a.jpg", image_urls=["/uploads/a.jpg", "/uploads/b.jpg"],
            location="15310", unit="ชิ้น", unit_value=200, quantity_total=5, quantity_available=5,
            low_stock_threshold=2, status="available", is_borrowable=True, categories=[cat],
        )
        db.add(eq)
        await db.commit()
    yield eq_id
    await _cleanup_group(name)


@pytest_asyncio.fixture(loop_scope="session")
async def bulk_consumable():
    """วัสดุสิ้นเปลือง quantity_total=5 — ต้องคงเป็นก้อนเดียวตามกฎธุรกิจ (CLAUDE.md ข้อ 5) ห้ามแยก"""
    tag = uuid.uuid4().hex[:6].upper()
    name = f"{SPLIT_NAME_PREFIX} สิ้นเปลือง {tag}"
    eq_id = uuid.uuid4()
    async with AsyncSessionLocal() as db:
        db.add(Equipment(
            id=eq_id, code=_split_code("2"), name=name, item_type="consumable",
            image_urls=[], quantity_total=5, quantity_available=5, status="available",
        ))
        await db.commit()
    yield eq_id
    await _cleanup_group(name)


@pytest_asyncio.fixture(loop_scope="session")
async def single_material():
    """วัสดุ quantity_total=1 — ไม่มีอะไรให้แยก"""
    tag = uuid.uuid4().hex[:6].upper()
    name = f"{SPLIT_NAME_PREFIX} เดี่ยว {tag}"
    eq_id = uuid.uuid4()
    async with AsyncSessionLocal() as db:
        db.add(Equipment(
            id=eq_id, code=_split_code("1"), name=name, item_type="material",
            image_urls=[], quantity_total=1, quantity_available=1, status="available",
        ))
        await db.commit()
    yield eq_id
    await _cleanup_group(name)


# ── _generate_split_codes (pure function) ──────────────────────────────────────

def test_generate_split_codes_increments_trailing_digits():
    codes = _generate_split_codes("234001", 4, existing_codes=set())
    assert codes == ["234002", "234003", "234004", "234005"]


def test_generate_split_codes_skips_collisions():
    codes = _generate_split_codes("900001", 2, existing_codes={"900002"})
    assert codes == ["900003", "900004"]


def test_generate_split_codes_no_trailing_digit_uses_dash_suffix():
    codes = _generate_split_codes("MAT-ARD", 2, existing_codes=set())
    assert codes == ["MAT-ARD-2", "MAT-ARD-3"]


# ── split_equipment_into_units — เงื่อนไขปฏิเสธ ─────────────────────────────────

@pytest.mark.asyncio(loop_scope="session")
async def test_split_rejects_non_material(test_admin, test_equipment):
    """test_equipment เป็น durable — ปฏิเสธก่อนเช็คอย่างอื่นทั้งหมด"""
    async with AsyncSessionLocal() as db:
        admin = await db.get(User, test_admin.id)
        with pytest.raises(HTTPException) as exc:
            await split_equipment_into_units(db, admin, test_equipment.id)
        assert exc.value.status_code == 400


@pytest.mark.asyncio(loop_scope="session")
async def test_split_rejects_consumable(test_admin, bulk_consumable):
    """consumable ต้องคงเป็นก้อนเดียว — whitelist เฉพาะ material เท่านั้น (durable ถูกทดสอบแยกไว้ข้างบนแล้ว)"""
    async with AsyncSessionLocal() as db:
        admin = await db.get(User, test_admin.id)
        with pytest.raises(HTTPException) as exc:
            await split_equipment_into_units(db, admin, bulk_consumable)
        assert exc.value.status_code == 400


@pytest.mark.asyncio(loop_scope="session")
async def test_split_rejects_quantity_total_le_1(test_admin, single_material):
    async with AsyncSessionLocal() as db:
        admin = await db.get(User, test_admin.id)
        with pytest.raises(HTTPException) as exc:
            await split_equipment_into_units(db, admin, single_material)
        assert exc.value.status_code == 400


@pytest.mark.asyncio(loop_scope="session")
async def test_split_rejects_when_units_borrowed_out(test_admin, bulk_material):
    async with AsyncSessionLocal() as db:
        await db.execute(update(Equipment).where(Equipment.id == bulk_material).values(quantity_available=3))
        await db.commit()

    async with AsyncSessionLocal() as db:
        admin = await db.get(User, test_admin.id)
        with pytest.raises(HTTPException) as exc:
            await split_equipment_into_units(db, admin, bulk_material)
        assert exc.value.status_code == 400
        assert "2" in exc.value.detail  # บอกจำนวนที่ยืมอยู่ (5-3=2) ในข้อความ


# ── happy path ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio(loop_scope="session")
async def test_split_happy_path_creates_5_distinct_rows(test_admin, test_category, bulk_material):
    async with AsyncSessionLocal() as db:
        admin = await db.get(User, test_admin.id)
        rows = await split_equipment_into_units(db, admin, bulk_material)

    assert len(rows) == 5
    codes = [r.code for r in rows]
    assert len(set(codes)) == 5, "รหัสต้องไม่ซ้ำกันเลย"
    for r in rows:
        assert r.quantity_total == 1
        assert r.quantity_available == 1
        assert r.item_type == "material"
        assert r.location == "15310"
        assert r.unit == "ชิ้น"
        assert float(r.unit_value) == 200.0
        assert r.image_urls == ["/uploads/a.jpg", "/uploads/b.jpg"]
        assert {c.id for c in r.categories} == {test_category.id}

    # audit log ต้องมีแค่ 1 รายการเดียว (ไม่ใช่ N รายการเหมือนสร้างของใหม่ N ชิ้น)
    async with AsyncSessionLocal() as db:
        logs = (await db.execute(
            select(AuditLog).where(AuditLog.target_id == bulk_material, AuditLog.action == "split_equipment")
        )).scalars().all()
        assert len(logs) == 1
        assert set(logs[0].detail["split_into"]) == set(codes)


@pytest.mark.asyncio(loop_scope="session")
async def test_split_rejects_second_call_after_already_split(test_admin, bulk_material):
    """แยกแล้วแถวเดิมเหลือ quantity_total=1 — เรียกซ้ำต้องโดนปฏิเสธ (ไม่มีอะไรให้แยกอีก)"""
    async with AsyncSessionLocal() as db:
        admin = await db.get(User, test_admin.id)
        await split_equipment_into_units(db, admin, bulk_material)

    async with AsyncSessionLocal() as db:
        admin = await db.get(User, test_admin.id)
        with pytest.raises(HTTPException) as exc:
            await split_equipment_into_units(db, admin, bulk_material)
        assert exc.value.status_code == 400


# ── endpoint ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio(loop_scope="session")
async def test_split_endpoint_requires_admin(client, student_token, bulk_material):
    r = await client.post(f"/equipment/{bulk_material}/split", headers=auth(student_token))
    assert r.status_code == 403


@pytest.mark.asyncio(loop_scope="session")
async def test_split_endpoint_returns_units(client, admin_token, bulk_material):
    r = await client.post(f"/equipment/{bulk_material}/split", headers=auth(admin_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 5
    assert len({item["code"] for item in body}) == 5


# ── borrow after split → BorrowItem คนละแถวคนละรหัสจริง ─────────────────────────

@pytest.mark.asyncio(loop_scope="session")
async def test_borrow_after_split_creates_distinct_borrow_items(
    client, admin_token, student_token, test_student, bulk_material,
):
    r = await client.post(f"/equipment/{bulk_material}/split", headers=auth(admin_token))
    assert r.status_code == 200, r.text
    units = r.json()
    unit_ids = {u["id"] for u in units}

    res = await client.post("/borrow-requests", headers=auth(student_token), json={
        "purpose": "ทดสอบยืมหลังแยกวัสดุ", "requested_due_date": "2099-01-01",
        "items": [{"equipment_id": units[0]["id"], "quantity": 3}],
    })
    assert res.status_code == 201, res.text
    req_id = res.json()["id"]

    async with AsyncSessionLocal() as db:
        items = (await db.execute(
            select(BorrowItem).where(BorrowItem.borrow_request_id == uuid.UUID(req_id))
        )).scalars().all()
        assert len(items) == 3, "ยืม 3 ชิ้นจากรุ่นที่เพิ่งแยก ต้องได้ BorrowItem 3 แถว ไม่ใช่ 1 แถว quantity=3"
        eq_ids = {str(i.equipment_id) for i in items}
        assert len(eq_ids) == 3, "แต่ละ BorrowItem ต้องคนละอุปกรณ์ (คนละรหัส) ไม่ใช่ผูกหน่วยเดียวกันซ้ำ"
        assert eq_ids <= unit_ids
        assert all(i.quantity == 1 for i in items)

        await db.execute(delete(Notification).where(Notification.borrow_request_id == uuid.UUID(req_id)))
        await db.execute(delete(BorrowItem).where(BorrowItem.borrow_request_id == uuid.UUID(req_id)))
        await db.execute(delete(BorrowRequest).where(BorrowRequest.id == uuid.UUID(req_id)))
        await db.commit()
