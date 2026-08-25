"""ตรวจนับอุปกรณ์ทางกายภาพ — POST /equipment/{id}/audit

อัปเดต last_audited_at + log audit_logs (action=physical_audit) แบบ append-only เดิม admin เท่านั้น
"""
import uuid
from datetime import datetime, timezone

from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.equipment import Equipment
from tests.conftest import auth


async def _make_equipment(client: AsyncClient, admin_header: dict, **overrides) -> str:
    suffix = uuid.uuid4().hex[:6].upper()
    body = {
        "code": f"PAUDIT-{suffix}", "name": f"อุปกรณ์ทดสอบตรวจนับ {suffix}",
        "category_ids": [], "item_type": "durable", "quantity_total": 1,
        "image_urls": ["/uploads/test.jpg"],
    }
    body.update(overrides)
    r = await client.post("/equipment", json=body, headers=admin_header)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _cleanup(eq_id: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(AuditLog).where(AuditLog.target_id == uuid.UUID(eq_id)))
        await db.execute(delete(Equipment).where(Equipment.id == uuid.UUID(eq_id)))
        await db.commit()


async def test_physical_audit_updates_last_audited_at_and_logs(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    eq_id = await _make_equipment(client, h)
    try:
        eq_before = (await client.get(f"/equipment/{eq_id}", headers=h)).json()
        assert eq_before["last_audited_at"] is None

        before = datetime.now(timezone.utc)
        r = await client.post(f"/equipment/{eq_id}/audit", json={"note": "เจอของจริง ปกติดี"}, headers=h)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["last_audited_at"] is not None
        audited_at = datetime.fromisoformat(body["last_audited_at"].replace("Z", "+00:00"))
        assert audited_at >= before

        async with AsyncSessionLocal() as db:
            log = (await db.execute(
                select(AuditLog).where(AuditLog.target_id == uuid.UUID(eq_id), AuditLog.action == "physical_audit")
            )).scalars().first()
            assert log is not None
            assert log.detail["note"] == "เจอของจริง ปกติดี"
            assert log.detail["previous_audit_at"] is None
    finally:
        await _cleanup(eq_id)


async def test_physical_audit_note_and_photo_optional(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    eq_id = await _make_equipment(client, h)
    try:
        r = await client.post(f"/equipment/{eq_id}/audit", json={}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["last_audited_at"] is not None
    finally:
        await _cleanup(eq_id)


async def test_physical_audit_records_previous_audit_time_on_second_call(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    eq_id = await _make_equipment(client, h)
    try:
        first = await client.post(f"/equipment/{eq_id}/audit", json={}, headers=h)
        first_audited_at = first.json()["last_audited_at"]

        second = await client.post(f"/equipment/{eq_id}/audit", json={"note": "ตรวจซ้ำ"}, headers=h)
        assert second.status_code == 200, second.text

        async with AsyncSessionLocal() as db:
            logs = (await db.execute(
                select(AuditLog).where(AuditLog.target_id == uuid.UUID(eq_id), AuditLog.action == "physical_audit")
                .order_by(AuditLog.created_at)
            )).scalars().all()
            assert len(logs) == 2
            assert logs[1].detail["previous_audit_at"] is not None
    finally:
        await _cleanup(eq_id)


async def test_physical_audit_forbidden_for_student(client: AsyncClient, admin_token: str, student_token: str):
    h_admin = auth(admin_token)
    eq_id = await _make_equipment(client, h_admin)
    try:
        r = await client.post(f"/equipment/{eq_id}/audit", json={}, headers=auth(student_token))
        assert r.status_code == 403
    finally:
        await _cleanup(eq_id)
