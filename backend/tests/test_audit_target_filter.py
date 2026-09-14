"""กรอง audit log ตาม target_id — ทางเข้าของ "ประวัติอุปกรณ์ชิ้นนี้"

feedback อาจารย์: อยากเห็นชัด ๆ ว่าอุปกรณ์ชิ้นหนึ่งถูกย้าย/แก้อะไรบ้าง เมื่อไร โดยใคร
ข้อมูลอยู่ใน audit_logs ครบอยู่แล้ว ขาดแค่ทางกรอง

หมายเหตุ: conftest.py มี PYTEST_ALLOW_DB=1 รันใส่ DB dev จริง — ทุกเทสต้อง cleanup ใน finally เสมอ
"""
import uuid

from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.equipment import Equipment
from tests.conftest import auth


async def _make(client: AsyncClient, h: dict, name: str) -> dict:
    r = await client.post("/equipment", json={
        "code": f"{uuid.uuid4().int % 10**15:015d}", "name": name,
        "category_ids": [], "item_type": "durable", "quantity_total": 1,
        "image_urls": ["/uploads/test.jpg"], "unit_value": 1000, "acquired_at": "2024-01-15",
        "location": "15310",
    }, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


async def _cleanup(names: list[str]) -> None:
    async with AsyncSessionLocal() as db:
        eq_ids = (await db.execute(select(Equipment.id).where(Equipment.name.in_(names)))).scalars().all()
        if eq_ids:
            await db.execute(delete(AuditLog).where(AuditLog.target_id.in_(eq_ids)))
            await db.execute(delete(Equipment).where(Equipment.id.in_(eq_ids)))
        await db.commit()


async def test_target_id_filter_isolates_one_equipment(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    n1 = f"อุปกรณ์ประวัติ A {uuid.uuid4().hex[:6]}"
    n2 = f"อุปกรณ์ประวัติ B {uuid.uuid4().hex[:6]}"
    try:
        a = await _make(client, h, n1)
        b = await _make(client, h, n2)
        assert (await client.patch(f"/equipment/{a['id']}", json={"location": "15399"}, headers=h)).status_code == 200
        assert (await client.patch(f"/equipment/{b['id']}", json={"location": "15400"}, headers=h)).status_code == 200

        r = await client.get("/audit-logs", params={"target_id": a["id"], "page_size": 50}, headers=h)
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        assert items, "ต้องมีประวัติอย่างน้อยการสร้าง + การแก้ไข"
        assert all(i["target_id"] == a["id"] for i in items)

        # ประวัติการย้ายสถานที่ต้องอ่านได้ว่าจากไหนไปไหน
        upd = next(i for i in items if i["action"] == "update_equipment")
        assert upd["detail"]["changes"]["location"] == ["15310", "15399"]
        assert upd["actor_name"]
    finally:
        await _cleanup([n1, n2])


async def test_bulk_update_history_visible_from_every_affected_unit(client: AsyncClient, admin_token: str):
    """bulk update เขียน log แถวเดียวต่อ batch — หน่วยที่ 2 เป็นต้นไปต้องยังเห็นประวัตินี้ด้วย"""
    h = auth(admin_token)
    n1 = f"อุปกรณ์ bulk ประวัติ A {uuid.uuid4().hex[:6]}"
    n2 = f"อุปกรณ์ bulk ประวัติ B {uuid.uuid4().hex[:6]}"
    try:
        a = await _make(client, h, n1)
        b = await _make(client, h, n2)
        r = await client.patch("/equipment/bulk-update", json={
            "equipment_ids": [a["id"], b["id"]], "update": {"location": "15499"},
        }, headers=h)
        assert r.status_code == 200, r.text

        for eq in (a, b):
            res = await client.get("/audit-logs",
                                   params={"target_id": eq["id"], "action": "bulk_update_equipment"}, headers=h)
            assert res.status_code == 200, res.text
            assert res.json()["total"] >= 1, f"หน่วย {eq['code']} ต้องเห็นประวัติ bulk update ของตัวเอง"
    finally:
        await _cleanup([n1, n2])


async def test_unknown_target_id_returns_empty(client: AsyncClient, admin_token: str):
    r = await client.get("/audit-logs", params={"target_id": str(uuid.uuid4())}, headers=auth(admin_token))
    assert r.status_code == 200
    assert r.json()["total"] == 0
    assert r.json()["items"] == []


async def test_target_table_filter(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    r = await client.get("/audit-logs", params={"target_table": "equipment", "page_size": 20}, headers=h)
    assert r.status_code == 200
    assert all(i["target_table"] == "equipment" for i in r.json()["items"])
