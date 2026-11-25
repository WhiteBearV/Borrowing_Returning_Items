"""ชื่อครุภัณฑ์ตามบัญชี (asset_name) แยกจากชื่อในระบบ (name) — 25 พ.ย. 69, migration 0059

- ของใหม่จากไฟล์ทะเบียนได้ชื่อจากไฟล์ทั้งสองช่อง
- ผู้ดูแลคลัง (ไม่ใช่ superadmin) แก้ชื่อตามบัญชีได้ · ค้นด้วยชื่อตามบัญชีก็เจอ
- นำเข้าไฟล์ทะเบียนซ้ำแก้แค่ asset_name ไม่ทับชื่อสั้นที่ตั้งไว้

PYTEST_ALLOW_DB=1 รันใส่ DB dev จริง — ลบทุกอย่างที่สร้างใน finally
"""
import openpyxl
import pytest
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.equipment import Equipment
from tests.conftest import auth

ASSET_NO = "TESTASSETNAME-0001"
LONG = "เครื่องคอมพิวเตอร์ทดสอบสำหรับประมวลผลแบบที่ 2 จอขนาดไม่น้อยกว่า 19 นิ้ว zq7"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _file(tmp_path, name: str):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "คณะเทคโนฯดิจิทัล"
    for _ in range(4):
        ws.append([None])
    ws.append([1, ASSET_NO, name, 25000, None, "P", None, None, None, None, "คณะ", "15311"])
    path = tmp_path / "register.xlsx"
    wb.save(path)
    return path


async def _preview(client, h, path) -> dict:
    with open(path, "rb") as f:
        r = await client.post("/equipment/import/preview", files={"file": ("register.xlsx", f, XLSX)}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


async def _commit(client, h, draft, row) -> None:
    r = await client.post(f"/equipment/import/{draft['import_id']}/commit", headers=h, json={
        "filename": "register.xlsx",
        "rows": [{"code": row["code"], "action": row["action"], "name": row["name"],
                  "location": row["location"], "status": row["status"], "category": row["category"]}],
    })
    assert r.status_code == 200, r.text


@pytest.mark.asyncio(loop_scope="session")
async def test_asset_name_separate_from_name(client, admin_token, tmp_path):
    h = auth(admin_token)
    try:
        # 1) ของใหม่จากไฟล์ = ชื่อจากไฟล์ทั้งสองช่อง
        draft = await _preview(client, h, _file(tmp_path, LONG))
        row = next(r for r in draft["rows"] if r["asset_number"] == ASSET_NO)
        await _commit(client, h, draft, row)
        async with AsyncSessionLocal() as db:
            eq = (await db.execute(select(Equipment).where(Equipment.asset_number == ASSET_NO))).scalar_one()
        assert eq.name == LONG and eq.asset_name == LONG

        # 2) ผู้ดูแลคลังตั้งชื่อสั้น + แก้ชื่อตามบัญชีได้ (ไม่ติดด่าน FINANCE_FIELDS)
        r = await client.patch(f"/equipment/{eq.id}", headers=h, json={"name": "คอมทดสอบ zq7 2 จอ"})
        assert r.status_code == 200, r.text
        r = await client.patch(f"/equipment/{eq.id}", headers=h, json={"asset_name": LONG + " (แก้)"})
        assert r.status_code == 200, r.text
        assert r.json()["asset_name"] == LONG + " (แก้)" and r.json()["name"] == "คอมทดสอบ zq7 2 จอ"

        # 3) ค้นด้วยท่อนของชื่อตามบัญชีก็เจอ
        r = await client.get("/equipment", headers=h, params={"search": "ประมวลผลแบบที่ 2 จอขนาดไม่น้อยกว่า 19 นิ้ว zq7"})
        assert str(eq.id) in [i["id"] for i in r.json()["items"]]

        # 4) นำเข้าไฟล์เดิมซ้ำ (ชื่อในไฟล์ = LONG) → เปลี่ยนแค่ชื่อตามบัญชี ชื่อสั้นในระบบไม่หาย
        draft = await _preview(client, h, _file(tmp_path, LONG))
        row = next(r for r in draft["rows"] if r.get("asset_number") == ASSET_NO)
        # ราคาว่างเพราะร่างข้างบนไม่ได้ส่ง unit_value มา — ไฟล์เติมให้ (fill-only) ไม่เกี่ยวกับเทสนี้
        assert row["action"] == "update" and "asset_name" in row["changes"] and "name" not in row["changes"]
        await _commit(client, h, draft, row)
        async with AsyncSessionLocal() as db:
            eq = (await db.execute(select(Equipment).where(Equipment.asset_number == ASSET_NO))).scalar_one()
        assert eq.name == "คอมทดสอบ zq7 2 จอ" and eq.asset_name == LONG

        # 5) ไฟล์ตรงกับระบบแล้ว = ไม่มีอะไรเปลี่ยน
        draft = await _preview(client, h, _file(tmp_path, LONG))
        assert "asset_name" not in next(r for r in draft["rows"] if r.get("asset_number") == ASSET_NO).get("changes", {})
    finally:
        async with AsyncSessionLocal() as db:
            ids = (await db.execute(select(Equipment.id).where(Equipment.asset_number == ASSET_NO))).scalars().all()
            await db.execute(delete(AuditLog).where(AuditLog.target_id.in_(ids)))
            await db.execute(delete(Equipment).where(Equipment.id.in_(ids)))
            await db.commit()
