"""Tests: ลบอุปกรณ์ถาวรหลายรายการพร้อมกัน (Phase B feature 2)

best-effort ไม่ใช่ all-or-nothing — ชิ้นที่ guard ของ delete_equipment ปฏิเสธได้อย่างชอบธรรมทีละชิ้น
(ยังไม่ปลดระวาง/ผูกกับชุดอุปกรณ์) ไม่ควรบล็อกชิ้นอื่นที่เหลือ
"""
import uuid

from httpx import AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.bundle import Bundle, BundleItem
from app.models.equipment import Equipment
from tests.conftest import auth


async def _make_equipment(client: AsyncClient, admin_header: dict, retired: bool = False) -> str:
    suffix = uuid.uuid4().hex[:6].upper()
    r = await client.post("/equipment", json={
        "code": f"{uuid.uuid4().int % 10**15:015d}", "name": f"อุปกรณ์ทดสอบลบหลายรายการ {suffix}",
        "category_ids": [], "item_type": "durable", "quantity_total": 1,
        "image_urls": ["/uploads/test.jpg"],
    }, headers=admin_header)
    assert r.status_code == 201, r.text
    eq_id = r.json()["id"]
    if retired:
        assert (await client.delete(f"/equipment/{eq_id}", headers=admin_header)).status_code == 204
    return eq_id


async def _cleanup(*eq_ids: str) -> None:
    async with AsyncSessionLocal() as db:
        for eq_id in eq_ids:
            await db.execute(delete(AuditLog).where(AuditLog.target_id == uuid.UUID(eq_id)))
            await db.execute(delete(Equipment).where(Equipment.id == uuid.UUID(eq_id)))
        await db.commit()


async def test_bulk_delete_all_succeed(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    ids = [await _make_equipment(client, h, retired=True) for _ in range(2)]
    try:
        r = await client.post("/equipment/bulk-delete", json={"equipment_ids": ids}, headers=h)
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body["deleted"]) == set(ids)
        assert body["failed"] == []
    finally:
        await _cleanup(*ids)


async def test_bulk_delete_partial_failure_not_retired(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    ok_id = await _make_equipment(client, h, retired=True)
    bad_id = await _make_equipment(client, h, retired=False)  # ยังไม่ปลดระวาง
    try:
        r = await client.post("/equipment/bulk-delete", json={"equipment_ids": [ok_id, bad_id]}, headers=h)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["deleted"] == [ok_id]
        assert len(body["failed"]) == 1
        assert body["failed"][0]["equipment_id"] == bad_id
        assert "ปลดระวาง" in body["failed"][0]["reason"]
    finally:
        await _cleanup(ok_id, bad_id)


async def test_bulk_delete_partial_failure_bundle_member(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    ok_id = await _make_equipment(client, h, retired=True)
    bundle_member_id = await _make_equipment(client, h, retired=False)
    bundle_id = None
    try:
        r = await client.post("/bundles", headers=h, json={
            "name": "ชุดทดสอบกันลบหลายรายการ",
            "items": [{"equipment_id": bundle_member_id, "quantity": 1}],
        })
        assert r.status_code == 201, r.text
        bundle_id = r.json()["id"]
        assert (await client.delete(f"/equipment/{bundle_member_id}", headers=h)).status_code == 204  # retire

        r = await client.post(
            "/equipment/bulk-delete", json={"equipment_ids": [ok_id, bundle_member_id]}, headers=h
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["deleted"] == [ok_id]
        assert len(body["failed"]) == 1
        assert body["failed"][0]["equipment_id"] == bundle_member_id
        assert "ชุดอุปกรณ์" in body["failed"][0]["reason"]
    finally:
        if bundle_id:
            async with AsyncSessionLocal() as db:
                await db.execute(delete(AuditLog).where(AuditLog.target_id == uuid.UUID(bundle_id)))
                await db.execute(delete(BundleItem).where(BundleItem.bundle_id == uuid.UUID(bundle_id)))
                await db.execute(delete(Bundle).where(Bundle.id == uuid.UUID(bundle_id)))
                await db.commit()
        await _cleanup(ok_id, bundle_member_id)


async def test_bulk_delete_empty_list_rejected(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    r = await client.post("/equipment/bulk-delete", json={"equipment_ids": []}, headers=h)
    assert r.status_code == 422


async def test_bulk_delete_forbidden_for_student(client: AsyncClient, admin_token: str, student_token: str):
    h_admin = auth(admin_token)
    h_student = auth(student_token)
    eq_id = await _make_equipment(client, h_admin, retired=True)
    try:
        r = await client.post("/equipment/bulk-delete", json={"equipment_ids": [eq_id]}, headers=h_student)
        assert r.status_code == 403
    finally:
        await _cleanup(eq_id)
