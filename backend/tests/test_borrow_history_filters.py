"""เฟส 0 (feedback อาจารย์ 5 ก.ย. 69) — filter หมวดหมู่/ประเภทในประวัติการยืม + บังคับกรอกวัตถุประสงค์

หมายเหตุ: conftest.py มี PYTEST_ALLOW_DB=1 รันใส่ DB dev จริง — ทุกเทสต้อง cleanup ใน finally เสมอ
"""
import uuid

from httpx import AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.borrow_item import BorrowItem
from app.models.borrow_request import BorrowRequest
from app.models.equipment import Equipment
from app.models.equipment_category import EquipmentCategory
from app.models.notification import Notification
from tests.conftest import auth


async def _make_category(client: AsyncClient, h_admin: dict) -> str:
    r = await client.post("/equipment-categories",
                          json={"name": f"หมวดทดสอบ filter {uuid.uuid4().hex[:8]}"}, headers=h_admin)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _make_equipment(client: AsyncClient, h_admin: dict, category_id: str, item_type: str) -> str:
    body = {
        "code": f"{uuid.uuid4().int % 10**15:015d}", "name": f"อุปกรณ์ทดสอบ filter {uuid.uuid4().hex[:6]}",
        "category_ids": [category_id], "item_type": item_type, "quantity_total": 1,
        "image_urls": ["/uploads/test.jpg"], "unit_value": 1000, "acquired_at": "2024-01-15",
    }
    if item_type == "consumable":
        body["unit"] = "ชิ้น"
    r = await client.post("/equipment", json=body, headers=h_admin)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _cleanup(eq_ids: list[str], req_ids: list[str], cat_ids: list[str]) -> None:
    async with AsyncSessionLocal() as db:
        for rid in req_ids:
            await db.execute(delete(Notification).where(Notification.borrow_request_id == uuid.UUID(rid)))
            await db.execute(delete(BorrowItem).where(BorrowItem.borrow_request_id == uuid.UUID(rid)))
            await db.execute(delete(BorrowRequest).where(BorrowRequest.id == uuid.UUID(rid)))
        for eid in eq_ids:
            await db.execute(delete(Equipment).where(Equipment.id == uuid.UUID(eid)))
        for cid in cat_ids:
            await db.execute(delete(EquipmentCategory).where(EquipmentCategory.id == uuid.UUID(cid)))
        await db.commit()


async def test_filter_by_item_type_and_category(client: AsyncClient, admin_token: str, student_token: str):
    """คำขอที่มีแต่ครุภัณฑ์ต้องโผล่เมื่อกรอง durable และหายไปเมื่อกรอง consumable
    ส่วนหมวดหมู่ต้องกรองได้ตรงหมวดของอุปกรณ์ในคำขอเท่านั้น"""
    h_admin, h_student = auth(admin_token), auth(student_token)
    cat_a = await _make_category(client, h_admin)
    cat_b = await _make_category(client, h_admin)
    eq_id = await _make_equipment(client, h_admin, cat_a, "durable")
    r = await client.post("/borrow-requests", headers=h_student, json={
        "purpose": "ทดสอบ filter ประวัติการยืม",
        "requested_due_date": "2028-06-01",
        "items": [{"equipment_id": eq_id, "quantity": 1}],
    })
    assert r.status_code == 201, r.text
    req_id = r.json()["id"]
    try:
        async def ids(**params) -> set[str]:
            resp = await client.get("/borrow-requests", params=params, headers=h_admin)
            assert resp.status_code == 200, resp.text
            return {i["id"] for i in resp.json()["items"]}

        assert req_id in await ids(item_type="durable", page_size=100)
        assert req_id not in await ids(item_type="consumable", page_size=100)
        assert req_id in await ids(category_id=cat_a, page_size=100)
        assert req_id not in await ids(category_id=cat_b, page_size=100)
        # กรองสองชั้นพร้อมกันต้องเป็น AND ไม่ใช่ OR
        assert req_id not in await ids(category_id=cat_b, item_type="durable", page_size=100)
    finally:
        await _cleanup([eq_id], [req_id], [cat_a, cat_b])


async def test_purpose_is_required(client: AsyncClient, admin_token: str, student_token: str, test_equipment):
    """วัตถุประสงค์บังคับกรอกตั้งแต่ 5 ก.ย. 69 — ไม่ส่งมาเลยหรือส่งมาแต่ช่องว่างต้องถูกปฏิเสธทั้งคู่"""
    h_student = auth(student_token)
    base = {"requested_due_date": "2028-06-01",
            "items": [{"equipment_id": str(test_equipment.id), "quantity": 1}]}

    r = await client.post("/borrow-requests", headers=h_student, json=base)
    assert r.status_code == 422, r.text

    r = await client.post("/borrow-requests", headers=h_student, json={**base, "purpose": "   "})
    assert r.status_code == 422, r.text

    # ตัดช่องว่างหัวท้ายก่อนบันทึกจริง
    r = await client.post("/borrow-requests", headers=h_student, json={**base, "purpose": "  ทดสอบ trim  "})
    assert r.status_code == 201, r.text
    req_id = r.json()["id"]
    try:
        assert r.json()["purpose"] == "ทดสอบ trim"
    finally:
        await _cleanup([], [req_id], [])
