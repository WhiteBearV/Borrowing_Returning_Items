"""Tests ชุดอุปกรณ์ (advisor #9 — ยืมเป็นชุด)

ชุดเป็นแค่แม่แบบสำหรับหยิบของใส่ตะกร้า ไม่ผูกกับคำขอยืม จึงเน้นทดสอบ CRUD + สิทธิ์ + validation
"""
import uuid

from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.bundle import Bundle, BundleItem
from app.models.equipment import Equipment
from tests.conftest import auth


async def _cleanup(bundle_id: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(AuditLog).where(AuditLog.target_id == uuid.UUID(bundle_id)))
        await db.execute(delete(BundleItem).where(BundleItem.bundle_id == uuid.UUID(bundle_id)))
        await db.execute(delete(Bundle).where(Bundle.id == uuid.UUID(bundle_id)))
        await db.commit()


async def test_bundle_crud_and_item_details(
    client: AsyncClient, admin_token: str, test_equipment: Equipment
):
    """สร้าง/แก้/ลบชุดได้ และ response ต้องมีข้อมูลอุปกรณ์พอให้หน้าเว็บหยิบใส่ตะกร้าได้"""
    h = auth(admin_token)
    r = await client.post("/bundles", headers=h, json={
        "name": "ชุดทดสอบ", "description": "สำหรับเทส",
        "items": [{"equipment_id": str(test_equipment.id), "quantity": 2}],
    })
    assert r.status_code == 201, r.text
    body = r.json()
    bundle_id = body["id"]
    try:
        item = body["items"][0]
        assert item["equipment_name"] == test_equipment.name
        assert item["quantity"] == 2
        assert item["quantity_available"] is not None  # หน้าเว็บใช้กันของหมด

        # ส่ง items มา = แทนที่รายการทั้งชุด
        r = await client.patch(f"/bundles/{bundle_id}", headers=h, json={
            "name": "ชุดทดสอบ (แก้แล้ว)",
            "items": [{"equipment_id": str(test_equipment.id), "quantity": 5}],
        })
        assert r.status_code == 200, r.text
        assert r.json()["name"] == "ชุดทดสอบ (แก้แล้ว)"
        assert len(r.json()["items"]) == 1 and r.json()["items"][0]["quantity"] == 5

        assert (await client.delete(f"/bundles/{bundle_id}", headers=h)).status_code == 204
        async with AsyncSessionLocal() as db:
            left = (await db.execute(
                select(BundleItem).where(BundleItem.bundle_id == uuid.UUID(bundle_id))
            )).scalars().all()
        assert left == [], "ลบชุดแล้วรายการในชุดต้องถูกลบตาม (cascade)"
    finally:
        await _cleanup(bundle_id)


async def test_bundle_rejects_invalid_items(
    client: AsyncClient, admin_token: str, test_equipment: Equipment
):
    """ชุดว่าง / อุปกรณ์ซ้ำ / อุปกรณ์ไม่มีจริง ต้องถูกปฏิเสธ"""
    h = auth(admin_token)
    eq_id = str(test_equipment.id)

    assert (await client.post("/bundles", headers=h, json={"name": "ว่าง", "items": []})).status_code == 422
    r = await client.post("/bundles", headers=h, json={"name": "ซ้ำ", "items": [
        {"equipment_id": eq_id, "quantity": 1}, {"equipment_id": eq_id, "quantity": 2}]})
    assert r.status_code == 400, r.text
    r = await client.post("/bundles", headers=h, json={"name": "ไม่มีจริง", "items": [
        {"equipment_id": str(uuid.uuid4()), "quantity": 1}]})
    assert r.status_code == 404, r.text

    # ตัวกระตุ้นต้องไม่ซ้ำกับสมาชิกในชุด — ไม่งั้นกดยืมแล้วได้ตัวกระตุ้น 2 เท่า (ของจริงที่เคยพัง)
    r = await client.post("/bundles", headers=h, json={
        "name": "ตัวกระตุ้นซ้ำสมาชิก", "trigger_equipment_id": eq_id,
        "items": [{"equipment_id": eq_id, "quantity": 1}],
    })
    assert r.status_code == 400, r.text


async def test_bundle_permissions_and_active_filter(
    client: AsyncClient, admin_token: str, student_token: str, test_equipment: Equipment
):
    """นักศึกษาสร้าง/แก้ชุดไม่ได้ และเห็นเฉพาะชุดที่เปิดใช้งาน"""
    h = auth(admin_token)
    payload = {"name": "ชุดสิทธิ์", "items": [{"equipment_id": str(test_equipment.id), "quantity": 1}]}
    assert (await client.post("/bundles", headers=auth(student_token), json=payload)).status_code == 403

    bundle_id = (await client.post("/bundles", headers=h, json=payload)).json()["id"]
    try:
        assert any(b["id"] == bundle_id for b in (await client.get("/bundles", headers=auth(student_token))).json())

        await client.patch(f"/bundles/{bundle_id}", headers=h, json={"is_active": False})
        student_ids = [b["id"] for b in (await client.get("/bundles", headers=auth(student_token))).json()]
        admin_ids = [b["id"] for b in (await client.get("/bundles", headers=h)).json()]
        assert bundle_id not in student_ids, "ชุดที่ปิดใช้งานต้องไม่โผล่ให้นักศึกษา"
        assert bundle_id in admin_ids, "แอดมินต้องยังเห็นชุดที่ปิดใช้งานเพื่อกลับมาเปิดได้"

        assert (await client.delete(f"/bundles/{bundle_id}", headers=auth(student_token))).status_code == 403
    finally:
        await _cleanup(bundle_id)


async def test_bundle_item_unit_count_reflects_group_size(
    client: AsyncClient, admin_token: str, test_equipment: Equipment
):
    """item.unit_count ต้องบอกจำนวนหน่วยจริงในรุ่นเดียวกัน (name+item_type ตรงกัน) — ไม่ใช่ 1 เสมอ

    บั๊กจริงที่เจอ: ของที่ถูกดึงเข้าตะกร้าผ่านชุดอุปกรณ์ (bundle) ไม่มี unit_count ติดมาด้วยเลย
    ทำให้หน้าตะกร้า/ใบยืมโชว์รหัสหน่วยที่ยังไม่นิ่ง (จะเปลี่ยนได้ตอนอนุมัติ) เหมือนรหัสมันนิ่งแล้ว
    """
    h = auth(admin_token)
    tag = uuid.uuid4().hex[:6].upper()
    group_name = f"กลุ่มทดสอบ bundle unit_count {tag}"
    eq_ids: list[uuid.UUID] = []
    async with AsyncSessionLocal() as db:
        for i in range(1, 4):  # 3 หน่วยรุ่นเดียวกัน
            r_id = uuid.uuid4()
            db.add(Equipment(
                id=r_id, code=f"BUNDGRP-{tag}-{i:03d}", name=group_name,
                item_type="durable", quantity_total=1, quantity_available=1, status="available",
            ))
            eq_ids.append(r_id)
        await db.commit()

    r = await client.post("/bundles", headers=h, json={
        "name": f"ชุดทดสอบ unit_count {tag}",
        "items": [
            {"equipment_id": str(eq_ids[0]), "quantity": 1},
            {"equipment_id": str(test_equipment.id), "quantity": 1},  # เทียบกับของที่มีหน่วยเดียว (unit_count=1)
        ],
    })
    assert r.status_code == 201, r.text
    bundle_id = r.json()["id"]
    try:
        items_by_id = {i["equipment_id"]: i for i in r.json()["items"]}
        assert items_by_id[str(eq_ids[0])]["unit_count"] == 3, "รุ่นที่มี 3 หน่วย ต้องได้ unit_count = 3"
        assert items_by_id[str(test_equipment.id)]["unit_count"] == 1, "รุ่นที่มีหน่วยเดียว ต้องได้ unit_count = 1"

        # list_bundles (GET /bundles) ก็ต้องเติม unit_count ให้เหมือนกัน ไม่ใช่แค่ตอน create
        r = await client.get("/bundles", headers=h)
        listed = next(b for b in r.json() if b["id"] == bundle_id)
        listed_by_id = {i["equipment_id"]: i for i in listed["items"]}
        assert listed_by_id[str(eq_ids[0])]["unit_count"] == 3
    finally:
        await _cleanup(bundle_id)
        async with AsyncSessionLocal() as db:
            await db.execute(delete(Equipment).where(Equipment.id.in_(eq_ids)))
            await db.commit()
