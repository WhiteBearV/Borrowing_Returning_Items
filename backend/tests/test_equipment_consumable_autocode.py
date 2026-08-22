"""Tests: วัสดุสิ้นเปลืองสร้างได้โดยไม่ต้องกรอกรหัส — ระบบออกรหัสอัตโนมัติจากชื่อ (Phase B feature 5)

เว้นรหัสว่างได้เฉพาะ item_type=consumable เท่านั้น (เซ็นเซอร์/ตัวต้านทานหลายแบบไม่ต้องนั่งคิดรหัสให้ทุกแบบ)
รูปแบบรหัสที่ออกให้: "{ชื่อ}-{เลขลำดับ 3 หลัก}" อ่านแล้วรู้ทันทีว่าเป็นอุปกรณ์อะไร ดีกว่ารหัสสุ่มล้วน ๆ

หมายเหตุ: conftest.py มี PYTEST_ALLOW_DB=1 รันใส่ DB dev จริง (ไม่ใช่ DB แยกต่างหาก) — ทุกเทสในไฟล์นี้ต้อง
ลบข้อมูลที่สร้างเองใน finally เสมอ ไม่งั้นจะกลายเป็นขยะค้างถาวรในคลังจริง (เจอปัญหานี้มาแล้วรอบหนึ่ง)
"""
import uuid

from httpx import AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.equipment import Equipment
from tests.conftest import auth


async def _cleanup(*eq_ids: str) -> None:
    async with AsyncSessionLocal() as db:
        for eq_id in eq_ids:
            await db.execute(delete(AuditLog).where(AuditLog.target_id == uuid.UUID(eq_id)))
            await db.execute(delete(Equipment).where(Equipment.id == uuid.UUID(eq_id)))
        await db.commit()


async def test_create_consumable_without_code_autogenerates(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    name = f"ตัวต้านทาน 220 โอห์ม {uuid.uuid4().hex[:6]}"
    r = await client.post("/equipment", json={
        "name": name, "category_ids": [], "item_type": "consumable",
        "quantity_total": 100, "image_urls": ["/uploads/test.jpg"],
    }, headers=h)
    assert r.status_code == 201, r.text
    try:
        assert r.json()["code"] == f"{name}-001"
    finally:
        await _cleanup(r.json()["id"])


async def test_create_consumable_without_code_same_name_increments(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    name = f"LED สีแดง {uuid.uuid4().hex[:6]}"
    body = {
        "name": name, "category_ids": [], "item_type": "consumable",
        "quantity_total": 50, "image_urls": ["/uploads/test.jpg"],
    }
    r1 = await client.post("/equipment", json=body, headers=h)
    assert r1.status_code == 201, r1.text
    r2 = await client.post("/equipment", json=body, headers=h)
    assert r2.status_code == 201, r2.text
    try:
        assert r1.json()["code"] == f"{name}-001"
        assert r2.json()["code"] == f"{name}-002"
    finally:
        await _cleanup(r1.json()["id"], r2.json()["id"])


async def test_create_durable_without_code_rejected(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    r = await client.post("/equipment", json={
        "name": f"ครุภัณฑ์ไม่มีรหัส {uuid.uuid4().hex[:6]}", "category_ids": [],
        "item_type": "durable", "quantity_total": 1, "image_urls": ["/uploads/test.jpg"],
    }, headers=h)
    assert r.status_code == 400


async def test_autocode_can_be_edited_to_real_code_afterwards(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    name = f"AND gate {uuid.uuid4().hex[:6]}"
    r = await client.post("/equipment", json={
        "name": name, "category_ids": [], "item_type": "consumable",
        "quantity_total": 20, "image_urls": ["/uploads/test.jpg"],
    }, headers=h)
    eq_id = r.json()["id"]
    try:
        real_code = f"AUTOCODE-TEST-{uuid.uuid4().hex[:6].upper()}"
        r2 = await client.patch(f"/equipment/{eq_id}", json={"code": real_code}, headers=h)
        assert r2.status_code == 200, r2.text
        assert r2.json()["code"] == real_code
    finally:
        await _cleanup(eq_id)
