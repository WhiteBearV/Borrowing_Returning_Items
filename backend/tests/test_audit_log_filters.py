"""GET /audit-logs รองรับกรอง action (มีอยู่แล้ว) + date_from/date_to (ใหม่)"""
import uuid
from datetime import date, timedelta

from httpx import AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.equipment import Equipment
from tests.conftest import auth


async def _make_equipment(client: AsyncClient, admin_header: dict) -> str:
    suffix = uuid.uuid4().hex[:6].upper()
    r = await client.post("/equipment", json={
        "code": f"{uuid.uuid4().int % 10**15:015d}", "name": f"อุปกรณ์ทดสอบกรอง log {suffix}",
        "category_ids": [], "item_type": "durable", "quantity_total": 1,
        "image_urls": ["/uploads/test.jpg"],
    }, headers=admin_header)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _cleanup(eq_id: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(AuditLog).where(AuditLog.target_id == uuid.UUID(eq_id)))
        await db.execute(delete(Equipment).where(Equipment.id == uuid.UUID(eq_id)))
        await db.commit()


async def test_filter_by_action_only_returns_matching_rows(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    eq_id = await _make_equipment(client, h)
    try:
        r = await client.get("/audit-logs", params={"action": "create_equipment", "page_size": 100}, headers=h)
        assert r.status_code == 200
        assert all(item["action"] == "create_equipment" for item in r.json()["items"])
        assert any(item["target_id"] == eq_id for item in r.json()["items"])
    finally:
        await _cleanup(eq_id)


async def test_filter_by_date_range_includes_today(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    eq_id = await _make_equipment(client, h)
    try:
        today = date.today().isoformat()
        r = await client.get(
            "/audit-logs", params={"date_from": today, "date_to": today, "page_size": 100}, headers=h
        )
        assert r.status_code == 200
        assert any(item["target_id"] == eq_id for item in r.json()["items"])
    finally:
        await _cleanup(eq_id)


async def test_filter_by_date_range_excludes_yesterday_only(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    eq_id = await _make_equipment(client, h)
    try:
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        r = await client.get(
            "/audit-logs", params={"date_from": yesterday, "date_to": yesterday, "page_size": 100}, headers=h
        )
        assert r.status_code == 200
        assert not any(item["target_id"] == eq_id for item in r.json()["items"])
    finally:
        await _cleanup(eq_id)


async def test_reversed_date_range_rejected(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    r = await client.get("/audit-logs", params={"date_from": today, "date_to": yesterday}, headers=auth(admin_token))
    assert r.status_code == 400


async def test_audit_logs_forbidden_for_student(client: AsyncClient, student_token: str):
    r = await client.get("/audit-logs", headers=auth(student_token))
    assert r.status_code == 403
