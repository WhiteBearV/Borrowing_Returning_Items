"""QR code เข้ารหัสเป็น URL ไปหน้ารายละเอียดอุปกรณ์ (ไม่ใช่แค่รหัสเฉย ๆ) — สแกนแล้วเห็นสถานะ/ผู้ถือครองสดได้ทันที"""
import uuid
from unittest.mock import patch

from httpx import AsyncClient
from sqlalchemy import delete

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.equipment import Equipment
from tests.conftest import auth


async def _make_equipment(client: AsyncClient, admin_header: dict) -> str:
    suffix = uuid.uuid4().hex[:6].upper()
    r = await client.post("/equipment", json={
        "code": f"QR-{suffix}", "name": f"อุปกรณ์ทดสอบ QR {suffix}",
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


async def test_qrcode_endpoint_returns_valid_png(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    eq_id = await _make_equipment(client, h)
    try:
        r = await client.get(f"/equipment/{eq_id}/qrcode", headers=h)
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/png"
        assert r.content[:8] == b"\x89PNG\r\n\x1a\n"
    finally:
        await _cleanup(eq_id)


async def test_generate_qr_encodes_equipment_detail_url_not_bare_code(client: AsyncClient, admin_token: str):
    """สาระสำคัญ: ต้องเข้ารหัส URL ไปหน้า /equipment/{id} ไม่ใช่แค่ eq.code เฉย ๆ"""
    h = auth(admin_token)
    eq_id = await _make_equipment(client, h)
    try:
        with patch("app.services.equipment_service.generate_qr_png", return_value=b"fake") as mocked:
            r = await client.get(f"/equipment/{eq_id}/qrcode", headers=h)
            assert r.status_code == 200
            mocked.assert_called_once_with(f"{settings.FRONTEND_URL}/equipment/{eq_id}")
    finally:
        await _cleanup(eq_id)
