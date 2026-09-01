"""Tests: บังคับรหัสครุภัณฑ์ (durable) ต้องเป็นตัวเลข 15 หลักพอดี ตอน "เปลี่ยนเข้า durable" เท่านั้น
(create_equipment ทุกกรณี, update_equipment/bulk_update_equipment เฉพาะตอนเปลี่ยนจาก material/consumable
เข้า durable) — ไม่ retroactive กับแถวที่เป็น durable อยู่แล้ว (ของเดิมจากทะเบียนจริงใช้รหัสภายในสั้นกว่านี้)

หมายเหตุ: conftest.py มี PYTEST_ALLOW_DB=1 รันใส่ DB dev จริง — ทุกเทสต้อง cleanup ใน finally เสมอ
"""
import uuid

from httpx import AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.equipment import Equipment
from tests.conftest import auth


def _digits15() -> str:
    return f"{uuid.uuid4().int % 10**15:015d}"


async def _make_equipment(client: AsyncClient, admin_header: dict, **overrides) -> str:
    suffix = uuid.uuid4().hex[:6].upper()
    body = {
        "code": _digits15(), "name": f"อุปกรณ์ทดสอบรหัสครุภัณฑ์ {suffix}",
        "category_ids": [], "item_type": "material", "quantity_total": 1,
        "image_urls": ["/uploads/test.jpg"],
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


async def test_create_durable_with_short_code_rejected(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    r = await client.post("/equipment", json={
        "code": "212001", "name": "ครุภัณฑ์รหัสสั้นทดสอบ",
        "category_ids": [], "item_type": "durable", "quantity_total": 1,
        "image_urls": ["/uploads/test.jpg"],
    }, headers=h)
    assert r.status_code == 400
    assert "15 หลัก" in r.json()["detail"]


async def test_create_durable_with_15_digit_code_succeeds(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    code = _digits15()
    r = await client.post("/equipment", json={
        "code": code, "name": "ครุภัณฑ์รหัสครบทดสอบ",
        "category_ids": [], "item_type": "durable", "quantity_total": 1,
        "image_urls": ["/uploads/test.jpg"],
    }, headers=h)
    assert r.status_code == 201, r.text
    try:
        assert r.json()["code"] == code
    finally:
        await _cleanup(r.json()["id"])


async def test_create_durable_code_with_dashes_counts_digits_only(client: AsyncClient, admin_token: str):
    """นับเฉพาะตัวเลข ตัด "-" ออกก่อนนับ — รูปแบบ 65-214-059-006-0019 (15 หลักจริงถ้านับแค่ตัวเลข) ต้องผ่าน"""
    h = auth(admin_token)
    digits = _digits15()
    code = f"{digits[:2]}-{digits[2:5]}-{digits[5:8]}-{digits[8:11]}-{digits[11:]}"
    r = await client.post("/equipment", json={
        "code": code, "name": "ครุภัณฑ์รหัสมีขีดทดสอบ",
        "category_ids": [], "item_type": "durable", "quantity_total": 1,
        "image_urls": ["/uploads/test.jpg"],
    }, headers=h)
    assert r.status_code == 201, r.text
    try:
        assert r.json()["code"] == code
    finally:
        await _cleanup(r.json()["id"])


async def test_create_non_durable_with_short_code_not_validated(client: AsyncClient, admin_token: str):
    """สร้าง material/consumable รหัสสั้นแบบเดิมยังต้องได้ปกติ — validator ผูกกับ durable เท่านั้น"""
    h = auth(admin_token)
    r = await client.post("/equipment", json={
        "code": f"MTL-{uuid.uuid4().hex[:6].upper()}", "name": "วัสดุรหัสสั้นทดสอบ",
        "category_ids": [], "item_type": "material", "quantity_total": 1,
        "image_urls": ["/uploads/test.jpg"],
    }, headers=h)
    assert r.status_code == 201, r.text
    try:
        pass
    finally:
        await _cleanup(r.json()["id"])


async def test_update_equipment_into_durable_with_short_code_rejected(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    eq_id = await _make_equipment(client, h, item_type="material", code=f"MTL-{uuid.uuid4().hex[:6].upper()}")
    try:
        r = await client.patch(f"/equipment/{eq_id}", json={"item_type": "durable"}, headers=h)
        assert r.status_code == 400
        assert "15 หลัก" in r.json()["detail"]
        # ต้องไม่ถูกแก้จริง — ยังเป็น material เหมือนเดิม
        eq = (await client.get(f"/equipment/{eq_id}", headers=h)).json()
        assert eq["item_type"] == "material"
    finally:
        await _cleanup(eq_id)


async def test_update_equipment_into_durable_with_15_digit_code_succeeds(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    code = _digits15()
    eq_id = await _make_equipment(client, h, item_type="material", code=code)
    try:
        r = await client.patch(f"/equipment/{eq_id}", json={"item_type": "durable"}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["item_type"] == "durable"
    finally:
        await _cleanup(eq_id)


async def test_update_equipment_into_durable_using_new_code_in_same_request(client: AsyncClient, admin_token: str):
    """ถ้า request เดียวกันเปลี่ยน code ด้วย ให้ใช้ code ใหม่ตรวจแทนของเดิม"""
    h = auth(admin_token)
    old_code = f"MTL-{uuid.uuid4().hex[:6].upper()}"  # ไม่ครบ 15 หลัก
    eq_id = await _make_equipment(client, h, item_type="material", code=old_code)
    new_code = _digits15()
    try:
        r = await client.patch(f"/equipment/{eq_id}", json={"item_type": "durable", "code": new_code}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["item_type"] == "durable" and r.json()["code"] == new_code
    finally:
        await _cleanup(eq_id)


async def test_update_equipment_already_durable_not_retroactively_validated(client: AsyncClient, admin_token: str):
    """แถวที่เป็น durable อยู่แล้ว (รหัสสั้นแบบทะเบียนเดิม) แก้ไขฟิลด์อื่นได้ปกติ ไม่ถูกบังคับ 15 หลักย้อนหลัง

    สร้างแถวนี้ด้วยการ insert ตรงผ่าน ORM (ไม่ผ่าน create_equipment) เพื่อจำลองของเดิมจากทะเบียนจริงที่มีอยู่
    แล้วก่อนมี validator นี้ — create_equipment เองก็บังคับ 15 หลักตอนสร้างใหม่เป็น durable แล้ว (ดูเทสอื่น)
    """
    h = auth(admin_token)
    eq_id = uuid.uuid4()
    legacy_code = f"212001-{uuid.uuid4().hex[:4]}"
    async with AsyncSessionLocal() as db:
        db.add(Equipment(
            id=eq_id, code=legacy_code, name="ครุภัณฑ์ทะเบียนเดิมทดสอบ",
            item_type="durable", quantity_total=1, quantity_available=1, status="available",
        ))
        await db.commit()
    try:
        r = await client.patch(f"/equipment/{eq_id}", json={"location": "ห้อง 15310"}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["location"] == "ห้อง 15310"
    finally:
        await _cleanup(str(eq_id))


async def test_bulk_update_into_durable_partial_success_skips_short_codes(client: AsyncClient, admin_token: str):
    """เลือกหลายแถวเปลี่ยนเข้า durable พร้อมกัน — แถวรหัสไม่ครบ 15 หลักถูกข้าม (ใส่ลง failed) แถวที่ผ่านอัปเดตตามปกติ"""
    h = auth(admin_token)
    good_code = _digits15()
    good_id = await _make_equipment(client, h, item_type="material", code=good_code)
    bad_id = await _make_equipment(client, h, item_type="material", code=f"MTL-{uuid.uuid4().hex[:6].upper()}")
    try:
        r = await client.patch("/equipment/bulk-update", json={
            "equipment_ids": [good_id, bad_id], "update": {"item_type": "durable"},
        }, headers=h)
        assert r.status_code == 200, r.text
        body = r.json()
        updated_ids = {u["id"] for u in body["updated"]}
        assert updated_ids == {good_id}
        assert all(u["item_type"] == "durable" for u in body["updated"])
        failed_ids = {f["equipment_id"] for f in body["failed"]}
        assert failed_ids == {bad_id}
        assert "15 หลัก" in body["failed"][0]["reason"]

        # แถวที่ไม่ผ่านต้องไม่ถูกแก้จริง
        bad_eq = (await client.get(f"/equipment/{bad_id}", headers=h)).json()
        assert bad_eq["item_type"] == "material"
    finally:
        await _cleanup(good_id, bad_id)


async def test_bulk_update_into_durable_all_fail_returns_empty_updated(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    bad_id = await _make_equipment(client, h, item_type="material", code=f"MTL-{uuid.uuid4().hex[:6].upper()}")
    try:
        r = await client.patch("/equipment/bulk-update", json={
            "equipment_ids": [bad_id], "update": {"item_type": "durable"},
        }, headers=h)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["updated"] == []
        assert len(body["failed"]) == 1 and body["failed"][0]["equipment_id"] == bad_id

        bad_eq = (await client.get(f"/equipment/{bad_id}", headers=h)).json()
        assert bad_eq["item_type"] == "material"
    finally:
        await _cleanup(bad_id)


async def test_bulk_update_other_fields_still_all_or_nothing(client: AsyncClient, admin_token: str):
    """ฟิลด์อื่นที่ไม่ใช่เปลี่ยนเข้า durable ยังคง all-or-nothing เหมือนเดิม ไม่มี failed"""
    h = auth(admin_token)
    ids = [await _make_equipment(client, h) for _ in range(2)]
    try:
        r = await client.patch("/equipment/bulk-update", json={
            "equipment_ids": ids, "update": {"location": "ตู้ทดสอบ"},
        }, headers=h)
        assert r.status_code == 200, r.text
        body = r.json()
        assert {u["id"] for u in body["updated"]} == set(ids)
        assert body["failed"] == []
    finally:
        await _cleanup(*ids)
