"""Tests: ปลดระวางอุปกรณ์หลายรายการพร้อมกัน — POST /equipment/bulk-retire

best-effort เหมือน bulk-delete — เรียก retire_equipment เดิมซ้ำทีละชิ้น ชิ้นที่ปลดระวางไม่ได้ (เช่น id ไม่มีจริง)
ไม่ควรบล็อกชิ้นอื่นที่เหลือ เหตุผลเดียวกันใช้กับทุกชิ้นที่เลือก
"""
import uuid

from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.equipment import Equipment
from tests.conftest import auth


async def _make_equipment(client: AsyncClient, admin_header: dict) -> str:
    suffix = uuid.uuid4().hex[:6].upper()
    r = await client.post("/equipment", json={
        "code": f"BULKRET-{suffix}", "name": f"อุปกรณ์ทดสอบปลดระวางหลายรายการ {suffix}",
        "category_ids": [], "item_type": "durable", "quantity_total": 1,
        "image_urls": ["/uploads/test.jpg"],
    }, headers=admin_header)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _cleanup(*eq_ids: str) -> None:
    async with AsyncSessionLocal() as db:
        for eq_id in eq_ids:
            await db.execute(delete(AuditLog).where(AuditLog.target_id == uuid.UUID(eq_id)))
            await db.execute(delete(Equipment).where(Equipment.id == uuid.UUID(eq_id)))
        await db.commit()


async def test_bulk_retire_all_succeed_with_shared_reason(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    ids = [await _make_equipment(client, h) for _ in range(2)]
    try:
        r = await client.post(
            "/equipment/bulk-retire", json={"equipment_ids": ids, "reason": "หมดสภาพทั้งชุด"}, headers=h
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body["retired"]) == set(ids)
        assert body["failed"] == []

        for eq_id in ids:
            eq = (await client.get(f"/equipment/{eq_id}", headers=h)).json()
            assert eq["status"] == "retired"

        async with AsyncSessionLocal() as db:
            log = (await db.execute(
                select(AuditLog).where(AuditLog.target_id == uuid.UUID(ids[0]), AuditLog.action == "retire_equipment")
            )).scalars().first()
            assert log.detail["reason"] == "หมดสภาพทั้งชุด"
    finally:
        await _cleanup(*ids)


async def test_bulk_retire_partial_failure_bad_id(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    ok_id = await _make_equipment(client, h)
    bad_id = str(uuid.uuid4())  # id ไม่มีจริง
    try:
        r = await client.post(
            "/equipment/bulk-retire", json={"equipment_ids": [ok_id, bad_id]}, headers=h
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["retired"] == [ok_id]
        assert len(body["failed"]) == 1
        assert body["failed"][0]["equipment_id"] == bad_id
    finally:
        await _cleanup(ok_id)


async def test_bulk_retire_empty_list_rejected(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    r = await client.post("/equipment/bulk-retire", json={"equipment_ids": []}, headers=h)
    assert r.status_code == 422


async def test_bulk_retire_forbidden_for_student(client: AsyncClient, admin_token: str, student_token: str):
    h_admin = auth(admin_token)
    eq_id = await _make_equipment(client, h_admin)
    try:
        r = await client.post(
            "/equipment/bulk-retire", json={"equipment_ids": [eq_id]}, headers=auth(student_token)
        )
        assert r.status_code == 403
    finally:
        await _cleanup(eq_id)
