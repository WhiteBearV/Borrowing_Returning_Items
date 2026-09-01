"""Tests: filter status "available"/"unavailable" ต้องรวม is_borrowable เข้ากับคอลัมน์ status ด้วย

ของประจำห้อง (is_borrowable=false) status คอลัมน์ยังเป็น "available" อยู่เสมอ (import ไฟล์ทะเบียนใหม่ไม่แตะ
ฟิลด์นี้) — เดิม filter "พร้อมให้ยืม"/"ทุกสถานะ" ดึงของกลุ่มนี้มาปนกับของที่ยืมได้จริง ส่วน filter "ไม่อนุญาต
ให้ยืม" กลับไม่ดึงมาเลยเพราะกรองแค่ status=="unavailable" คนละคอลัมน์กับ is_borrowable

หมายเหตุ: conftest.py มี PYTEST_ALLOW_DB=1 รันใส่ DB dev จริง (คลังจริงมีของหลายร้อยชิ้น) — ทุกเทสค้นด้วย
`search` แคบลงเฉพาะแท็กของตัวเองเสมอ ไม่ใช้ page_size ใหญ่ ๆ มาครอบทั้งคลัง (จะพลาด pagination ได้) และต้อง
cleanup ใน finally เสมอ
"""
import uuid

from httpx import AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.equipment import Equipment
from tests.conftest import auth


async def _make_equipment(client: AsyncClient, admin_header: dict, tag: str, **overrides) -> str:
    suffix = uuid.uuid4().hex[:6].upper()
    body = {
        "code": f"{uuid.uuid4().int % 10**15:015d}", "name": f"อุปกรณ์ทดสอบ is_borrowable filter {tag} {suffix}",
        "category_ids": [], "item_type": "durable", "quantity_total": 1,
        "image_urls": ["/uploads/test.jpg"],
    }
    body.update(overrides)
    r = await client.post("/equipment", json=body, headers=admin_header)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _cleanup(*eq_ids: str) -> None:
    async with AsyncSessionLocal() as db:
        for eq_id in eq_ids:
            await db.execute(delete(AuditLog).where(AuditLog.target_id == uuid.UUID(eq_id)))
            await db.execute(delete(Equipment).where(Equipment.id == uuid.UUID(eq_id)))
        await db.commit()


async def test_room_fixture_excluded_from_available_filter(client: AsyncClient, admin_token: str):
    """is_borrowable=false แต่ status="available" (ของประจำห้อง) ต้องไม่โผล่ตอนกรอง "พร้อมให้ยืม" """
    h = auth(admin_token)
    tag = uuid.uuid4().hex[:8]
    room_id = await _make_equipment(client, h, tag, is_borrowable=False)
    normal_id = await _make_equipment(client, h, tag, is_borrowable=True)
    try:
        r = await client.get("/equipment", params={"status": "available", "search": tag, "page_size": 20}, headers=h)
        ids = {i["id"] for i in r.json()["items"]}
        assert normal_id in ids
        assert room_id not in ids, "ของประจำห้อง (is_borrowable=false) ต้องไม่ปนอยู่ในกลุ่มพร้อมให้ยืม"
    finally:
        await _cleanup(room_id, normal_id)


async def test_room_fixture_included_in_unavailable_filter(client: AsyncClient, admin_token: str):
    """is_borrowable=false แต่ status="available" ต้องถูกดึงมาด้วยตอนกรอง "ไม่อนุญาตให้ยืม" """
    h = auth(admin_token)
    tag = uuid.uuid4().hex[:8]
    room_id = await _make_equipment(client, h, tag, is_borrowable=False)
    normal_id = await _make_equipment(client, h, tag, is_borrowable=True)
    try:
        r = await client.get("/equipment", params={"status": "unavailable", "search": tag, "page_size": 20}, headers=h)
        ids = {i["id"] for i in r.json()["items"]}
        assert room_id in ids, "ของประจำห้องต้องถูกจัดเข้ากลุ่มไม่อนุญาตให้ยืม แม้ status คอลัมน์จะเป็น available"
        assert normal_id not in ids
    finally:
        await _cleanup(room_id, normal_id)


async def test_status_unavailable_column_still_matches_unavailable_filter(client: AsyncClient, admin_token: str):
    """แถวที่ status="unavailable" จริง (ไม่ใช่ของประจำห้อง is_borrowable ยังเป็น true) ก็ต้องถูกกรองมาด้วยเหมือนเดิม"""
    h = auth(admin_token)
    tag = uuid.uuid4().hex[:8]
    eq_id = await _make_equipment(client, h, tag)
    try:
        assert (await client.patch(f"/equipment/{eq_id}", json={"status": "unavailable"}, headers=h)).status_code == 200
        r = await client.get("/equipment", params={"status": "unavailable", "search": tag, "page_size": 20}, headers=h)
        ids = {i["id"] for i in r.json()["items"]}
        assert eq_id in ids
    finally:
        await _cleanup(eq_id)


async def test_damaged_filter_untouched_by_is_borrowable(client: AsyncClient, admin_token: str):
    """filter_status="damaged" ยังกรองตรงคอลัมน์ status เหมือนเดิมเป๊ะ ไม่ถูกแก้ไขไปยุ่งกับ is_borrowable เลย
    (ต่างจาก "available"/"unavailable" ที่ถูกแก้ในรอบนี้) — ทดสอบด้วยแถวปกติ is_borrowable=true ธรรมดา"""
    h = auth(admin_token)
    tag = uuid.uuid4().hex[:8]
    eq_id = await _make_equipment(client, h, tag, is_borrowable=True)
    try:
        assert (await client.patch(f"/equipment/{eq_id}", json={"status": "damaged"}, headers=h)).status_code == 200
        r = await client.get("/equipment", params={"status": "damaged", "search": tag, "page_size": 20}, headers=h)
        ids = {i["id"] for i in r.json()["items"]}
        assert eq_id in ids
    finally:
        await _cleanup(eq_id)
