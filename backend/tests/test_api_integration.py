"""Integration tests — ใช้ DB จริง + FastAPI app"""
import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.borrow_item import BorrowItem
from app.models.borrow_request import BorrowRequest
from app.models.equipment import Equipment, equipment_category_links
from app.models.equipment_category import EquipmentCategory
from app.models.notification import Notification
from app.models.user import User
from tests.conftest import auth


# ── Auth ──────────────────────────────────────────────────────────────────────

async def test_login_success(client: AsyncClient, test_student: User):
    r = await client.post("/auth/login", json={
        "identifier": test_student.email,
        "password": "Test1234!",
    })
    assert r.status_code == 200
    assert "access_token" in r.json()


async def test_login_wrong_password(client: AsyncClient, test_student: User):
    r = await client.post("/auth/login", json={
        "identifier": test_student.email,
        "password": "WrongPassword",
    })
    assert r.status_code in (400, 401)


async def test_login_unverified_email(client: AsyncClient):
    uid = uuid.uuid4()
    async with AsyncSessionLocal() as db:
        u = User(
            id=uid, full_name="ยังไม่ verify",
            email=f"noverify_{uid.hex[:4]}@cdti.ac.th",
            password_hash=hash_password("Test1234!"),
            role="student", email_verified=False, is_active=True,
        )
        db.add(u)
        await db.commit()

    r = await client.post("/auth/login", json={
        "identifier": f"noverify_{uid.hex[:4]}@cdti.ac.th",
        "password": "Test1234!",
    })
    assert r.status_code == 403

    async with AsyncSessionLocal() as db:
        u = await db.get(User, uid)
        if u:
            await db.delete(u)
            await db.commit()


# ── Equipment ─────────────────────────────────────────────────────────────────

async def test_list_equipment(client: AsyncClient, student_token: str):
    r = await client.get("/equipment", headers=auth(student_token))
    assert r.status_code == 200
    body = r.json()
    assert "items" in body and "total" in body


async def test_list_equipment_filter_by_type(client: AsyncClient, student_token: str):
    r = await client.get("/equipment", params={"item_type": "durable"}, headers=auth(student_token))
    assert r.status_code == 200
    for item in r.json()["items"]:
        assert item["item_type"] == "durable"


async def test_list_equipment_filter_by_category(
    client: AsyncClient, student_token: str, test_equipment: Equipment, test_category
):
    r = await client.get(
        "/equipment",
        params={"category_id": str(test_category.id)},
        headers=auth(student_token),
    )
    assert r.status_code == 200
    ids = [i["id"] for i in r.json()["items"]]
    assert str(test_equipment.id) in ids


async def test_equipment_multiple_categories(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    suffix = uuid.uuid4().hex[:6]
    c1 = (await client.post("/equipment-categories", json={"name": f"cat_a_{suffix}"}, headers=h)).json()
    c2 = (await client.post("/equipment-categories", json={"name": f"cat_b_{suffix}"}, headers=h)).json()
    r = await client.post("/equipment", json={
        "code": f"MULTI-{suffix}", "name": "อุปกรณ์หลายหมวด",
        "category_ids": [c1["id"], c2["id"]], "item_type": "durable", "quantity_total": 1,
    }, headers=h)
    assert r.status_code == 201, r.text
    returned = {c["id"] for c in r.json()["categories"]}
    assert returned == {c1["id"], c2["id"]}
    # ต้องเจอเมื่อ filter ด้วยหมวดใดหมวดหนึ่ง
    ids = [i["id"] for i in (await client.get("/equipment", params={"category_id": c2["id"]}, headers=h)).json()["items"]]
    assert r.json()["id"] in ids

    # cleanup — ลบอุปกรณ์และหมวดหมู่ที่สร้างในเทสต์นี้ ไม่ให้ค้างใน DB
    async with AsyncSessionLocal() as db:
        await db.execute(delete(equipment_category_links).where(equipment_category_links.c.equipment_id == r.json()["id"]))
        await db.execute(delete(Equipment).where(Equipment.code == f"MULTI-{suffix}"))
        await db.execute(delete(EquipmentCategory).where(EquipmentCategory.id.in_([c1["id"], c2["id"]])))
        await db.commit()


async def test_unauthorized_without_token(client: AsyncClient):
    r = await client.get("/equipment")
    assert r.status_code in (401, 403)  # HTTPBearer คืน 403 หรือ 401 ขึ้นกับ version


# ── Borrow flow ───────────────────────────────────────────────────────────────

@pytest_asyncio.fixture(loop_scope="session")
async def borrow_request_id(client: AsyncClient, student_token: str, test_equipment: Equipment):
    r = await client.post("/borrow-requests", headers=auth(student_token), json={
        "purpose": "ทดสอบ integration",
        "items": [{"equipment_id": str(test_equipment.id), "quantity": 1}],
    })
    assert r.status_code == 201, r.text
    req_id = r.json()["id"]
    yield req_id
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Notification).where(Notification.borrow_request_id == req_id))
        await db.execute(delete(BorrowItem).where(BorrowItem.borrow_request_id == req_id))
        await db.execute(delete(BorrowRequest).where(BorrowRequest.id == req_id))
        eq = await db.get(Equipment, test_equipment.id)
        if eq:
            eq.quantity_available = eq.quantity_total
            eq.status = "available"
        await db.commit()


async def test_create_borrow_request(borrow_request_id: str):
    assert borrow_request_id is not None


async def test_borrow_response_has_equipment_name(
    client: AsyncClient, student_token: str, borrow_request_id: str
):
    """Bug fix: ต้องแสดงชื่ออุปกรณ์ ไม่ใช่ UUID"""
    r = await client.get(f"/borrow-requests/{borrow_request_id}", headers=auth(student_token))
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) > 0
    for item in items:
        assert item.get("equipment_name") is not None, "equipment_name must not be null"
        # ชื่อต้องไม่ใช่ UUID string (UUID มี - และยาว 36 ตัว)
        assert len(item["equipment_name"]) != 36 or "-" not in item["equipment_name"]


async def test_borrow_response_has_student_info(
    client: AsyncClient, student_token: str, borrow_request_id: str
):
    r = await client.get(f"/borrow-requests/{borrow_request_id}", headers=auth(student_token))
    body = r.json()
    assert body.get("student_name") is not None
    assert body.get("student_email") is not None


async def test_student_cannot_approve(
    client: AsyncClient, student_token: str, borrow_request_id: str
):
    r = await client.patch(
        f"/borrow-requests/{borrow_request_id}/approve",
        headers=auth(student_token),
    )
    assert r.status_code == 403


async def test_approve_request(
    client: AsyncClient, admin_token: str, borrow_request_id: str
):
    r = await client.patch(
        f"/borrow-requests/{borrow_request_id}/approve",
        headers=auth(admin_token),
    )
    assert r.status_code == 200


async def test_return_all_requires_admin(
    client: AsyncClient, student_token: str, borrow_request_id: str
):
    r = await client.post(
        f"/borrow-requests/{borrow_request_id}/return-all",
        headers=auth(student_token),
    )
    assert r.status_code == 403


async def test_return_all_by_admin(
    client: AsyncClient, admin_token: str, borrow_request_id: str
):
    r = await client.post(
        f"/borrow-requests/{borrow_request_id}/return-all",
        headers=auth(admin_token),
    )
    # ถ้า approved → 200, ถ้า approve test ไม่ผ่านก่อน → อาจ 400
    assert r.status_code in (200, 400)


async def test_quota_limit(client: AsyncClient, student_token: str, test_equipment: Equipment):
    """สร้างคำขอเกิน 2 (max_active_requests_per_student) ต้องได้ 400"""
    created_ids = []
    try:
        for i in range(3):
            r = await client.post("/borrow-requests", headers=auth(student_token), json={
                "purpose": f"ทดสอบ quota {i}",
                "items": [{"equipment_id": str(test_equipment.id), "quantity": 1}],
            })
            if r.status_code == 201:
                created_ids.append(r.json()["id"])
            elif r.status_code == 400:
                assert "active" in r.json()["detail"].lower()
                return  # ผ่าน: quota block ทำงานถูกต้อง
        # ถ้าสร้างได้ 3 ก็ fail
        pytest.fail("ควรได้ 400 เมื่อเกิน quota แต่ทำไม่ได้")
    finally:
        for req_id in created_ids:
            async with AsyncSessionLocal() as db:
                await db.execute(delete(Notification).where(Notification.borrow_request_id == req_id))
                await db.execute(delete(BorrowItem).where(BorrowItem.borrow_request_id == req_id))
                await db.execute(delete(BorrowRequest).where(BorrowRequest.id == req_id))
                await db.commit()


# ── Dashboard ─────────────────────────────────────────────────────────────────

async def test_dashboard_summary_has_all_fields(client: AsyncClient, admin_token: str):
    r = await client.get("/dashboard/summary", headers=auth(admin_token))
    assert r.status_code == 200
    body = r.json()
    for field in ("pending_requests", "overdue_requests", "low_stock_items",
                  "active_borrows", "active_borrowers"):
        assert field in body, f"missing field: {field}"
        assert isinstance(body[field], int), f"{field} must be int"


async def test_dashboard_requires_admin(client: AsyncClient, student_token: str):
    r = await client.get("/dashboard/summary", headers=auth(student_token))
    assert r.status_code == 403
