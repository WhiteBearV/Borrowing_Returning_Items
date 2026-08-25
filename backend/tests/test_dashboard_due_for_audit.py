"""GET /dashboard/summary มีฟิลด์ due_for_audit_items (ครบกำหนดตรวจนับทางกายภาพ)"""
import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import delete, update

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.equipment import Equipment
from tests.conftest import auth


async def test_dashboard_summary_includes_due_for_audit_count(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    r = await client.get("/dashboard/summary", headers=h)
    assert r.status_code == 200, r.text
    before = r.json()["due_for_audit_items"]

    suffix = uuid.uuid4().hex[:6].upper()
    r = await client.post("/equipment", json={
        "code": f"DASHAUD-{suffix}", "name": f"อุปกรณ์ทดสอบ dashboard {suffix}",
        "category_ids": [], "item_type": "durable", "quantity_total": 1,
        "image_urls": ["/uploads/test.jpg"],
    }, headers=h)
    eq_id = r.json()["id"]
    try:
        # ยังไม่เคยตรวจนับ (last_audited_at=NULL) → ต้องนับรวมใน due_for_audit_items ทันที
        r = await client.get("/dashboard/summary", headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["due_for_audit_items"] == before + 1

        # ตรวจนับแล้ว → หลุดออกจากรายการครบกำหนด
        await client.post(f"/equipment/{eq_id}/audit", json={}, headers=h)
        r = await client.get("/dashboard/summary", headers=h)
        assert r.json()["due_for_audit_items"] == before
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(AuditLog).where(AuditLog.target_id == uuid.UUID(eq_id)))
            await db.execute(delete(Equipment).where(Equipment.id == uuid.UUID(eq_id)))
            await db.commit()
