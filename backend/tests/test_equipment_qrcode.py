"""QR code เข้ารหัสเป็น URL ไปหน้ารายละเอียดอุปกรณ์ (ไม่ใช่แค่รหัสเฉย ๆ) — สแกนแล้วเห็นสถานะ/ผู้ถือครองสดได้ทันที"""
import uuid

import pytest
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
        "code": f"{uuid.uuid4().int % 10**15:015d}", "name": f"อุปกรณ์ทดสอบ QR {suffix}",
        "category_ids": [], "item_type": "durable", "quantity_total": 1,
        "image_urls": ["/uploads/test.jpg"], "unit_value": 1000, "acquired_at": "2024-01-15",
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


async def test_qrcode_response_is_not_cached(client: AsyncClient, admin_token: str):
    """เครื่อง dev IP เปลี่ยนบ่อย — browser ห้าม cache รูป QR ไว้ไม่งั้นเห็น URL เก่าซ้ำ"""
    h = auth(admin_token)
    eq_id = await _make_equipment(client, h)
    try:
        r = await client.get(f"/equipment/{eq_id}/qrcode", headers=h)
        assert r.headers["cache-control"] == "no-store"
    finally:
        await _cleanup(eq_id)


async def test_qrcode_uses_forwarded_lan_host(client: AsyncClient, admin_token: str):
    """X-Forwarded-Host ที่เป็น IP ในวง LAN ต้องถูกใช้สร้าง URL แทน settings.FRONTEND_URL คงที่
    (เครื่อง dev IP เปลี่ยนบ่อย มือถือต้องสแกน QR แล้วเข้าถึง IP ปัจจุบันได้จริง)"""
    h = {**auth(admin_token), "X-Forwarded-Host": "192.168.1.50:5173", "X-Forwarded-Proto": "http"}
    eq_id = await _make_equipment(client, auth(admin_token))
    try:
        with patch("app.services.equipment_service.generate_qr_png", return_value=b"fake") as mocked:
            r = await client.get(f"/equipment/{eq_id}/qrcode", headers=h)
            assert r.status_code == 200
            mocked.assert_called_once_with(f"http://192.168.1.50:5173/equipment/{eq_id}")
    finally:
        await _cleanup(eq_id)


@pytest.mark.parametrize("evil_host", [
    "evil-phishing.com",       # โดเมนสาธารณะ — เคสหลักที่ต้องกัน (QR ชี้ไปเว็บฟิชชิ่ง)
    "evil.com/phish",          # แอบยัด path
    "8.8.8.8:5173",            # IP สาธารณะ
    "192.168.1.50:notaport",   # port เพี้ยน
])
async def test_qrcode_rejects_non_lan_forwarded_host(client: AsyncClient, admin_token: str, evil_host: str):
    """X-Forwarded-Host เป็นค่าที่ client ปลอมส่งมาได้เอง — อะไรที่ไม่ใช่ address ในวง LAN ต้องถูกทิ้ง
    แล้ว fallback ไปใช้ settings.FRONTEND_URL ปกติ กัน host header injection ไปฝัง URL ฟิชชิ่งใน QR"""
    h = {**auth(admin_token), "X-Forwarded-Host": evil_host}
    eq_id = await _make_equipment(client, auth(admin_token))
    try:
        with patch("app.services.equipment_service.generate_qr_png", return_value=b"fake") as mocked:
            r = await client.get(f"/equipment/{eq_id}/qrcode", headers=h)
            assert r.status_code == 200
            mocked.assert_called_once_with(f"{settings.FRONTEND_URL}/equipment/{eq_id}")
    finally:
        await _cleanup(eq_id)
