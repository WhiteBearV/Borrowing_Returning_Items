"""เทสกันถดถอยของบั๊กจาก QA รอบ 2 (1 ต.ค. 69 — รายละเอียดใน Plans/qa-2026-10-01/bugs.md)

หมายเหตุ: PYTEST_ALLOW_DB=1 รันใส่ DB dev จริง — ลบทุกอย่างที่สร้าง + audit ใน finally
"""
import asyncio
import uuid
from datetime import date, timedelta

from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.borrow_item import BorrowItem
from app.models.borrow_request import BorrowRequest
from app.models.equipment import Equipment
from app.models.notification import Notification
from tests.conftest import auth


async def test_concurrent_approve_deducts_stock_once(
    client: AsyncClient, admin_token: str, student_token: str, test_equipment: Equipment,
):
    """R2-10: อนุมัติคำขอเดียวกันพร้อมกัน 3 ครั้ง ต้องผ่านครั้งเดียว สต็อกถูกตัดครั้งเดียว"""
    async with AsyncSessionLocal() as db:
        before = (await db.get(Equipment, test_equipment.id)).quantity_available
    r = await client.post("/borrow-requests", headers=auth(student_token), json={
        "purpose": "race", "requested_due_date": str(date.today() + timedelta(days=3)),
        "items": [{"equipment_id": str(test_equipment.id), "quantity": 1}]})
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    try:
        res = await asyncio.gather(*[client.patch(f"/borrow-requests/{rid}/approve", headers=auth(admin_token))
                                     for _ in range(3)])
        assert sorted(x.status_code for x in res) == [200, 400, 400], [x.text for x in res]
        async with AsyncSessionLocal() as db:
            assert (await db.get(Equipment, test_equipment.id)).quantity_available == before - 1
    finally:
        async with AsyncSessionLocal() as db:
            item_ids = (await db.execute(select(BorrowItem.id).where(BorrowItem.borrow_request_id == uuid.UUID(rid)))).scalars().all()
            await db.execute(delete(AuditLog).where(AuditLog.target_id.in_([uuid.UUID(rid), *item_ids])))
            await db.execute(delete(Notification).where(Notification.borrow_request_id == uuid.UUID(rid)))
            await db.execute(delete(BorrowItem).where(BorrowItem.borrow_request_id == uuid.UUID(rid)))
            await db.execute(delete(BorrowRequest).where(BorrowRequest.id == uuid.UUID(rid)))
            (await db.get(Equipment, test_equipment.id)).quantity_available = before
            await db.commit()


async def test_bad_input_is_4xx_not_500(client: AsyncClient, admin_token: str, test_equipment: Equipment):
    """R2-03 ข้อความยาวเกินคอลัมน์ · R2-06 สาขามั่ว · R2-07 รหัสผ่านยาว/เกิน 72 ไบต์"""
    r = await client.patch(f"/equipment/{test_equipment.id}", headers=auth(admin_token), json={"location": "ก" * 600})
    assert r.status_code == 400, r.text

    reg = {"email": f"r2_{uuid.uuid4().hex[:8]}@cdti.ac.th", "password": "Test1234!", "full_name": "ทดสอบ รอบสอง",
           "student_id": "6599912345", "phone": "0811111111", "major": "hacker", "pdpa_consent": True}
    assert (await client.post("/auth/register", json=reg)).status_code == 422
    assert (await client.post("/auth/register", json={**reg, "major": "comp_eng", "password": "ก" * 30})).status_code == 422
    # R3-06: ชื่อว่าง/ช่องว่างล้วนไม่ได้ทุกทางเข้า · ไม่มีนามสกุลใช้ "-" ได้
    for bad in ("", "   "):
        assert (await client.post("/auth/register", json={**reg, "major": "comp_eng", "full_name": bad})).status_code == 422
        assert (await client.patch("/users/me", headers=auth(admin_token), json={"full_name": bad})).status_code == 422
    r = await client.post("/auth/login", json={"identifier": "nobody@cdti.ac.th", "password": "x" * 5000})
    assert r.status_code == 422, r.text


async def test_round3_races_and_uploads(client: AsyncClient, admin_token: str):
    """R3-02 เพิ่มอุปกรณ์พร้อมกันไม่ชนรหัส · R3-08 ไฟล์ภาพเสียถูกปฏิเสธ"""
    body = {"name": f"R3 race {uuid.uuid4().hex[:6]}", "item_type": "material", "quantity_total": 1, "category_ids": [],
            "image_urls": ["/uploads/test.jpg"], "unit_value": 1, "acquired_at": "2024-01-01"}
    res = await asyncio.gather(*[client.post("/equipment", headers=auth(admin_token), json=body) for _ in range(4)])
    ids = [uuid.UUID(r.json()["id"]) for r in res if r.status_code == 201]
    try:
        assert [r.status_code for r in res] == [201] * 4, [r.text[:120] for r in res]
        assert len({r.json()["code"] for r in res}) == 4
        r = await client.post("/users/me/avatar", headers=auth(admin_token),
                              files={"file": ("a.jpg", b"\xff\xd8\xff\xe0junk", "image/jpeg")})
        assert r.status_code == 400, r.text
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(AuditLog).where(AuditLog.target_id.in_(ids)))
            await db.execute(delete(Equipment).where(Equipment.id.in_(ids)))
            await db.commit()


async def test_round4_paging_is_stable_and_bundle_name_unique(
    client: AsyncClient, admin_token: str, test_equipment: Equipment,
):
    """R4-01 ไล่ทุกหน้าของรายการรายหน่วยต้องไม่ซ้ำ/ไม่หาย · R4-04 ชุดอุปกรณ์ชื่อซ้ำ = 409"""
    h = auth(admin_token)
    total = (await client.get("/equipment", headers=h, params={"page": 1, "page_size": 100})).json()["total"]
    ids = [i["id"] for p in range(1, total // 100 + 2)
           for i in (await client.get("/equipment", headers=h, params={"page": p, "page_size": 100})).json()["items"]]
    assert len(ids) == len(set(ids)) == total

    name = f"R4 bundle {uuid.uuid4().hex[:6]}"
    body = {"name": name, "items": [{"equipment_id": str(test_equipment.id), "quantity": 1}]}
    r = await client.post("/bundles", headers=h, json=body)
    assert r.status_code == 201, r.text
    try:
        assert (await client.post("/bundles", headers=h, json={**body, "name": f"  {name.upper()} "})).status_code == 409
    finally:
        bid = uuid.UUID(r.json()["id"])
        await client.delete(f"/bundles/{bid}", headers=h)
        async with AsyncSessionLocal() as db:
            await db.execute(delete(AuditLog).where(AuditLog.target_id == bid))
            await db.commit()


async def test_round5_blank_names_rejected(client: AsyncClient, admin_token: str, test_equipment: Equipment):
    """R5-03: ชื่อหมวดหมู่/อุปกรณ์/ชุด และเหตุผล ว่างหรือช่องว่างล้วนไม่ได้ · หน่วยนับว่าง = ไม่ระบุ (ไม่เก็บสตริงว่าง)"""
    h = auth(admin_token)
    eq = {"item_type": "material", "quantity_total": 1, "category_ids": [], "image_urls": ["/uploads/test.jpg"],
          "unit_value": 1, "acquired_at": "2024-01-01"}
    for blank in ("", "   "):
        assert (await client.post("/equipment-categories", headers=h, json={"name": blank})).status_code == 422
        assert (await client.post("/equipment", headers=h, json={**eq, "name": blank})).status_code == 422
        assert (await client.patch(f"/equipment/{test_equipment.id}", headers=h, json={"name": blank})).status_code == 422
        r = await client.post("/bundles", headers=h, json={
            "name": blank, "items": [{"equipment_id": str(test_equipment.id), "quantity": 1}]})
        assert r.status_code == 422
    assert (await client.post("/change-requests", headers=h,
                              json={"target_table": "equipment", "reason": "   "})).status_code == 422
    assert (await client.post(f"/equipment/{test_equipment.id}/adjust-stock", headers=h,
                              json={"new_available": 1, "reason": "   "})).status_code == 422
    old_unit = test_equipment.unit
    r = await client.patch(f"/equipment/{test_equipment.id}", headers=h, json={"unit": "   "})
    assert r.status_code == 200 and r.json()["unit"] == old_unit, r.text
