"""ค้นหาในหน้า "ประวัติการยืมทั้งหมด" — GET /borrow-requests?search=... ค้นชื่อผู้ยืม/รหัสนักศึกษา/ชื่ออุปกรณ์

หมายเหตุ: conftest.py มี PYTEST_ALLOW_DB=1 รันใส่ DB dev จริง — ทุกเทสต้อง cleanup ใน finally เสมอ
"""
import uuid

from httpx import AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.borrow_item import BorrowItem
from app.models.borrow_request import BorrowRequest
from app.models.equipment import Equipment
from app.models.notification import Notification
from tests.conftest import auth


async def _make_equipment(client: AsyncClient, admin_header: dict, name: str) -> str:
    suffix = uuid.uuid4().hex[:6].upper()
    r = await client.post("/equipment", json={
        "code": f"SEARCH-{suffix}", "name": name,
        "category_ids": [], "item_type": "durable", "quantity_total": 1,
        "image_urls": ["/uploads/test.jpg"],
    }, headers=admin_header)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _cleanup(eq_id: str, req_id: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Notification).where(Notification.borrow_request_id == uuid.UUID(req_id)))
        await db.execute(delete(BorrowItem).where(BorrowItem.borrow_request_id == uuid.UUID(req_id)))
        await db.execute(delete(BorrowRequest).where(BorrowRequest.id == uuid.UUID(req_id)))
        await db.execute(delete(Equipment).where(Equipment.id == uuid.UUID(eq_id)))
        await db.commit()


async def test_search_by_equipment_name_finds_request(client: AsyncClient, admin_token: str, student_token: str):
    h_admin, h_student = auth(admin_token), auth(student_token)
    unique_name = f"อุปกรณ์ค้นหาเฉพาะ {uuid.uuid4().hex[:8]}"
    eq_id = await _make_equipment(client, h_admin, unique_name)
    r = await client.post("/borrow-requests", headers=h_student, json={
        "requested_due_date": "2028-06-01",
        "items": [{"equipment_id": eq_id, "quantity": 1}],
    })
    assert r.status_code == 201, r.text
    req_id = r.json()["id"]
    try:
        r = await client.get("/borrow-requests", params={"search": unique_name[:15]}, headers=h_admin)
        assert r.status_code == 200, r.text
        ids = {item["id"] for item in r.json()["items"]}
        assert req_id in ids

        r = await client.get("/borrow-requests", params={"search": "ไม่มีทางตรงกับอะไรแน่ๆ-xyz"}, headers=h_admin)
        assert req_id not in {item["id"] for item in r.json()["items"]}
    finally:
        await _cleanup(eq_id, req_id)


async def test_search_by_student_id_finds_request(client: AsyncClient, admin_token: str, student_token: str, test_student):
    h_admin, h_student = auth(admin_token), auth(student_token)
    eq_id = await _make_equipment(client, h_admin, f"อุปกรณ์ค้นหารหัสนักศึกษา {uuid.uuid4().hex[:6]}")
    r = await client.post("/borrow-requests", headers=h_student, json={
        "requested_due_date": "2028-06-01",
        "items": [{"equipment_id": eq_id, "quantity": 1}],
    })
    assert r.status_code == 201, r.text
    req_id = r.json()["id"]
    try:
        assert test_student.student_id, "fixture นักศึกษาต้องมี student_id เพื่อทดสอบค้นหาด้วยรหัส"
        r = await client.get("/borrow-requests", params={"search": test_student.student_id}, headers=h_admin)
        assert r.status_code == 200, r.text
        assert req_id in {item["id"] for item in r.json()["items"]}
    finally:
        await _cleanup(eq_id, req_id)
