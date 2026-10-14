"""เลขครุภัณฑ์แยกจากรหัสอุปกรณ์ + รหัสที่ระบบออกให้ (24 ก.ย. 69 — migration 0048)

แทนเทสเดิม 2 ไฟล์ (consumable autocode "ชื่อ-001" / บังคับ code ครุภัณฑ์ 15 หลัก) ที่กฎเปลี่ยนแล้ว:
- เว้นรหัสได้ทุกประเภท → DT-D / DT-M / DT-C + เลขรัน 5 หลักต่อจากเดิม
- เลขครุภัณฑ์ (asset_number): 15 หลัก · ห้ามซ้ำ · แก้ภายหลังได้เฉพาะ superadmin · ค้นหาเจอ
- เพิ่มจำนวนครุภัณฑ์ (restock) ได้รหัส DT-D ใหม่ และไม่เดาเลขครุภัณฑ์ให้

หมายเหตุ: conftest.py มี PYTEST_ALLOW_DB=1 รันใส่ DB dev จริง — ลบทุกอย่างที่สร้างใน finally
"""
import uuid

from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.equipment import Equipment
from tests.conftest import auth


def _asset() -> str:
    """เลขครุภัณฑ์สุ่มรูปแบบทะเบียนจริง (มีขีด 2-3-3-3-4)"""
    d = f"{uuid.uuid4().int % 10**15:015d}"
    return f"{d[:2]}-{d[2:5]}-{d[5:8]}-{d[8:11]}-{d[11:]}"


def _body(**kw) -> dict:
    body = {"name": f"ทดสอบเลขครุภัณฑ์ {uuid.uuid4().hex[:6]}", "category_ids": [], "item_type": "durable",
            "quantity_total": 1, "image_urls": ["/uploads/test.jpg"], "unit_value": 1000,
            "acquired_at": "2024-01-15"}
    body.update(kw)
    return body


async def _cleanup(ids: list[str]) -> None:
    async with AsyncSessionLocal() as db:
        uids = [uuid.UUID(i) for i in ids]
        await db.execute(delete(AuditLog).where(AuditLog.target_id.in_(uids)))
        await db.execute(delete(Equipment).where(Equipment.id.in_(uids)))
        await db.commit()


async def test_blank_code_gets_system_code_per_type(client: AsyncClient, admin_token: str):
    h, ids = auth(admin_token), []
    try:
        for item_type, prefix in (("durable", "DT-D-"), ("material", "DT-M-"), ("consumable", "DT-C-")):
            codes = []
            for _ in range(2):
                r = await client.post("/equipment", json=_body(item_type=item_type), headers=h)
                assert r.status_code == 201, r.text
                ids.append(r.json()["id"])
                codes.append(r.json()["code"])
            assert all(c.startswith(prefix) and len(c) == len(prefix) + 5 for c in codes), codes
            assert int(codes[1][len(prefix):]) == int(codes[0][len(prefix):]) + 1
    finally:
        await _cleanup(ids)


async def test_asset_number_validation_duplicate_and_search(client: AsyncClient, admin_token: str):
    h, ids, asset = auth(admin_token), [], _asset()
    try:
        r = await client.post("/equipment", json=_body(asset_number="63-213-001"), headers=h)
        assert r.status_code == 400 and "15 หลัก" in r.json()["detail"]
        r = await client.post("/equipment", json=_body(asset_number=asset), headers=h)
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])
        assert r.json()["asset_number"] == asset and r.json()["code"].startswith("DT-D-")
        r = await client.post("/equipment", json=_body(asset_number=asset), headers=h)
        assert r.status_code == 409
        # ค้นด้วยเลขครุภัณฑ์เจอ (สติกเกอร์ราชการเป็นเลขนี้)
        r = await client.get("/equipment", params={"search": asset}, headers=h)
        assert [e["id"] for e in r.json()["items"]] == ids
    finally:
        await _cleanup(ids)


async def test_only_superadmin_edits_asset_number(
    client: AsyncClient, admin_token: str, superadmin_token: str,
):
    h, ids = auth(admin_token), []
    try:
        r = await client.post("/equipment", json=_body(), headers=h)   # สร้างใหม่ไม่กั้น (เหมือนราคา)
        ids.append(r.json()["id"])
        new_asset = _asset()
        assert (await client.patch(f"/equipment/{ids[0]}", json={"asset_number": new_asset},
                                   headers=h)).status_code == 403
        r = await client.patch(f"/equipment/{ids[0]}", json={"asset_number": new_asset},
                               headers=auth(superadmin_token))
        assert r.status_code == 200, r.text
        assert r.json()["asset_number"] == new_asset
        # ส่งค่าเดิมซ้ำมากับฟอร์ม = ไม่นับว่าแก้ ผู้ดูแลคลังบันทึกฟอร์มได้ตามปกติ
        assert (await client.patch(f"/equipment/{ids[0]}", json={"asset_number": new_asset, "location": "15310"},
                                   headers=h)).status_code == 200
    finally:
        await _cleanup(ids)


async def test_restock_durable_gets_new_system_code_without_asset(client: AsyncClient, admin_token: str):
    h, ids = auth(admin_token), []
    try:
        r = await client.post("/equipment", json=_body(asset_number=_asset()), headers=h)
        ids.append(r.json()["id"])
        r = await client.post(f"/equipment/{ids[0]}/restock", json={"count": 2}, headers=h)
        assert r.status_code == 200, r.text
        new = [e for e in r.json() if e["id"] != ids[0]]
        ids += [e["id"] for e in new]
        assert len(new) == 2
        assert all(e["code"].startswith("DT-D-") and e["asset_number"] is None for e in new)
    finally:
        await _cleanup(ids)


async def test_bulk_change_into_durable_no_longer_needs_15_digit_code(client: AsyncClient, admin_token: str):
    """เดิมแถวรหัสไม่ครบ 15 หลักถูกข้ามตอนเปลี่ยนเป็นครุภัณฑ์ — กฎย้ายไปที่เลขครุภัณฑ์แล้ว"""
    h, ids = auth(admin_token), []
    try:
        r = await client.post("/equipment", json=_body(item_type="material", code=f"MAT-{uuid.uuid4().hex[:6]}"),
                              headers=h)
        ids.append(r.json()["id"])
        r = await client.patch("/equipment/bulk-update", json={"equipment_ids": ids, "update": {"item_type": "durable"}},
                               headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["failed"] == [] and r.json()["updated"][0]["item_type"] == "durable"
    finally:
        async with AsyncSessionLocal() as db:
            assert (await db.execute(select(Equipment).where(Equipment.id == uuid.UUID(ids[0])))).scalar_one()
        await _cleanup(ids)


async def test_asset_number_without_dashes_is_formatted_and_searchable(client: AsyncClient, admin_token: str):
    """พิมพ์ติดกัน 15 หลัก → ระบบใส่ขีด 2-3-3-3-4 ให้ · ค้นแบบไม่มีขีดก็เจอ · ส่งเลขเดิมแบบไม่มีขีดไม่นับว่าแก้"""
    h, ids, dashed = auth(admin_token), [], _asset()
    raw = dashed.replace("-", "")
    try:
        r = await client.post("/equipment", json=_body(asset_number=raw), headers=h)
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])
        assert r.json()["asset_number"] == dashed
        assert (await client.post("/equipment", json=_body(asset_number=dashed), headers=h)).status_code == 409
        r = await client.get("/equipment", params={"search": raw}, headers=h)
        assert [e["id"] for e in r.json()["items"]] == ids
        # ผู้ดูแลคลัง (แก้เลขครุภัณฑ์ไม่ได้) ส่งเลขเดิมแบบไม่มีขีดมากับฟอร์ม → ต้องไม่โดน 403
        assert (await client.patch(f"/equipment/{ids[0]}", json={"asset_number": raw}, headers=h)).status_code == 200
    finally:
        await _cleanup(ids)
