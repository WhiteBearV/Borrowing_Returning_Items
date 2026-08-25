"""filter status=due_for_audit ในหน้าจัดการอุปกรณ์ — ยังไม่เคยตรวจนับ หรือเกิน audit_interval_days วันแล้ว
ไม่รวมของปลดระวาง, กลุ่มหลายหน่วยใช้ semantics "any member due" เหมือน filter "borrowed"
"""
import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import delete, update

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.equipment import Equipment
from tests.conftest import auth


async def _make_equipment(client: AsyncClient, admin_header: dict, **overrides) -> str:
    suffix = uuid.uuid4().hex[:6].upper()
    body = {
        "code": f"AUDF-{suffix}", "name": f"อุปกรณ์ทดสอบ due filter {suffix}",
        "category_ids": [], "item_type": "durable", "quantity_total": 1,
        "image_urls": ["/uploads/test.jpg"],
    }
    body.update(overrides)
    r = await client.post("/equipment", json=body, headers=admin_header)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _set_last_audited(eq_id: str, dt) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(update(Equipment).where(Equipment.id == uuid.UUID(eq_id)).values(last_audited_at=dt))
        await db.commit()


async def _cleanup(*eq_ids: str) -> None:
    async with AsyncSessionLocal() as db:
        for eq_id in eq_ids:
            await db.execute(delete(AuditLog).where(AuditLog.target_id == uuid.UUID(eq_id)))
        await db.execute(delete(Equipment).where(Equipment.id.in_([uuid.UUID(e) for e in eq_ids])))
        await db.commit()


async def test_due_for_audit_includes_never_audited_and_overdue(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    tag = uuid.uuid4().hex[:8]
    name = f"อุปกรณ์ทดสอบ due filter {tag}"
    never_audited = await _make_equipment(client, h, name=name)
    overdue = await _make_equipment(client, h, name=name)
    recently_audited = await _make_equipment(client, h, name=name)
    try:
        await _set_last_audited(overdue, datetime.now(timezone.utc) - timedelta(days=200))
        await _set_last_audited(recently_audited, datetime.now(timezone.utc) - timedelta(days=1))

        # ต้อง search แคบลงเฉพาะของทดสอบนี้ — dev DB มีอุปกรณ์เดิมจำนวนมากที่ last_audited_at เป็น NULL
        # อยู่แล้ว (ยังไม่เคยตรวจนับ) ก็เข้าเงื่อนไข due_for_audit เหมือนกัน จน page_size 100 ไม่พอครอบคลุม
        r = await client.get(
            "/equipment", params={"status": "due_for_audit", "search": tag, "page_size": 100}, headers=h
        )
        assert r.status_code == 200, r.text
        ids = {item["id"] for item in r.json()["items"]}
        assert never_audited in ids
        assert overdue in ids
        assert recently_audited not in ids
    finally:
        await _cleanup(never_audited, overdue, recently_audited)


async def test_due_for_audit_excludes_retired(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    eq_id = await _make_equipment(client, h)
    try:
        assert (await client.delete(f"/equipment/{eq_id}", headers=h)).status_code == 204  # retire

        r = await client.get("/equipment", params={"status": "due_for_audit", "page_size": 100}, headers=h)
        assert r.status_code == 200, r.text
        assert eq_id not in {item["id"] for item in r.json()["items"]}
    finally:
        await _cleanup(eq_id)


async def test_due_for_audit_grouped_uses_any_member_semantics(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    group_name = f"กลุ่มทดสอบ due filter {uuid.uuid4().hex[:6]}"
    fresh = await _make_equipment(client, h, name=group_name)
    stale = await _make_equipment(client, h, name=group_name)
    try:
        await _set_last_audited(fresh, datetime.now(timezone.utc) - timedelta(days=1))
        # stale ไม่เคยตรวจนับ (None) — กลุ่มนี้ต้องปรากฏใน due_for_audit เพราะมีอย่างน้อย 1 หน่วยครบกำหนด

        r = await client.get(
            "/equipment/grouped", params={"status": "due_for_audit", "search": group_name, "page_size": 50},
            headers=h,
        )
        assert r.status_code == 200, r.text
        names = [item["name"] for item in r.json()["items"]]
        assert group_name in names
    finally:
        await _cleanup(fresh, stale)
