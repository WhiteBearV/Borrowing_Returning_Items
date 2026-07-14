"""นำเข้าจาก Excel ผ่าน API จริง: อัปโหลด → ร่าง → แอดมินแก้/ตัดออก → บันทึกเฉพาะที่เลือก

ตรวจว่าบรรทัดที่แอดมินตัดออกจากร่างต้องไม่เข้าระบบ, ค่าที่แก้ในร่างต้องถูกใช้จริง,
และร่างที่ถูกยัดของแปลกปลอม (code ไม่มีในไฟล์) ต้องถูกปฏิเสธ
"""
import openpyxl
import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.equipment import Equipment
from tests.conftest import auth

CODE_A = "TESTIMP-001"
CODE_B = "TESTIMP-002"


@pytest_asyncio.fixture
async def cleanup_imported():
    yield
    async with AsyncSessionLocal() as db:
        ids = (await db.execute(
            select(Equipment.id).where(Equipment.code.in_([CODE_A, CODE_B]))
        )).scalars().all()
        for eid in ids:
            await db.execute(delete(AuditLog).where(AuditLog.target_id == eid))
        await db.execute(delete(Equipment).where(Equipment.code.in_([CODE_A, CODE_B])))
        await db.commit()


def _register_file(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "คณะเทคโนฯดิจิทัล"
    for _ in range(4):
        ws.append([None])
    ws.append([1, CODE_A, "ออสซิลโลสโคป Rigol DS1054Z", 25000, None, "P", None, None, None, None, "คณะ", "15311"])
    ws.append([2, CODE_B, "มัลติมิเตอร์ Fluke 117", 8000, None, "P", None, None, None, None, "คณะ", "15311"])
    path = tmp_path / "register.xlsx"
    wb.save(path)
    return path


@pytest.mark.asyncio(loop_scope="session")
async def test_import_preview_then_commit_selected_rows(client, admin_token, tmp_path, cleanup_imported):
    path = _register_file(tmp_path)
    with open(path, "rb") as f:
        res = await client.post(
            "/equipment/import/preview",
            files={"file": ("register.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=auth(admin_token),
        )
    assert res.status_code == 200
    draft = res.json()
    new_rows = {r["code"]: r for r in draft["rows"] if r["action"] == "new"}
    assert CODE_A in new_rows and CODE_B in new_rows

    # แอดมินแก้ชื่อ/สถานะในร่าง แล้วตัด CODE_B ออก (ไม่เอาเข้าคลัง)
    res = await client.post(
        f"/equipment/import/{draft['import_id']}/commit",
        json={"filename": "register.xlsx", "rows": [{
            "code": CODE_A, "action": "new", "name": "ออสซิลโลสโคป Rigol (แก้ชื่อในร่าง)",
            "location": "15399", "status": "damaged", "category": "อุปกรณ์อิเล็กทรอนิกส์/เครื่องมือวัด",
        }]},
        headers=auth(admin_token),
    )
    assert res.status_code == 200
    assert res.json()["new"] == 1

    async with AsyncSessionLocal() as db:
        eq = (await db.execute(select(Equipment).where(Equipment.code == CODE_A))).scalar_one()
        assert eq.name == "ออสซิลโลสโคป Rigol (แก้ชื่อในร่าง)"  # ใช้ค่าที่แก้ในร่าง ไม่ใช่ค่าจากไฟล์
        assert eq.location == "15399"
        assert eq.status == "damaged" and eq.quantity_available == 0  # ชำรุด → ยืมไม่ได้
        # บรรทัดที่ถูกตัดออกจากร่างต้องไม่เข้าระบบ
        assert (await db.execute(select(Equipment).where(Equipment.code == CODE_B))).scalar_one_or_none() is None
        # ต้องมี audit log ให้ออกใบรับเข้าคลังได้
        log = (await db.execute(
            select(AuditLog).where(AuditLog.target_id == eq.id, AuditLog.action == "create_equipment")
        )).scalar_one()
        assert log.detail["code"] == CODE_A and log.detail["source"] == "register.xlsx"


@pytest.mark.asyncio(loop_scope="session")
async def test_commit_rejects_row_not_in_uploaded_file(client, admin_token, tmp_path, cleanup_imported):
    path = _register_file(tmp_path)
    with open(path, "rb") as f:
        res = await client.post(
            "/equipment/import/preview",
            files={"file": ("register.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=auth(admin_token),
        )
    import_id = res.json()["import_id"]

    res = await client.post(
        f"/equipment/import/{import_id}/commit",
        json={"rows": [{"code": "ของแปลกปลอม-999", "action": "new", "name": "ของที่ไม่ได้อยู่ในไฟล์",
                        "status": "available"}]},
        headers=auth(admin_token),
    )
    assert res.status_code == 400
