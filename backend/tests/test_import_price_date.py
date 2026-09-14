"""นำเข้าทะเบียน: ราคา + วันที่ได้มา ต้องไหลเข้าจริง และต้องไม่ทับค่าที่แอดมินกรอกเอง

คอลัมน์ "ราคา" (idx 3) และ "ว/ด/ป ที่รับ" (idx 4) มีอยู่ในไฟล์ทะเบียนจริงครบทุกแถวของชีตคณะ
แต่เดิม parse_workbook อ่านข้ามไปทั้งคู่ ไฟล์นี้กันไม่ให้หลุดอีก + ล็อกกฎ fill-only

หมายเหตุ: conftest.py มี PYTEST_ALLOW_DB=1 รันใส่ DB dev จริง — ทุกเทสต้อง cleanup ใน finally เสมอ
"""
from datetime import date, datetime

import openpyxl
import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.equipment import Equipment
from app.services.import_service import diff_rows, parse_workbook
from tests.conftest import auth

CODE = "TESTPRICE-001"
FILE_PRICE = 25000
FILE_DATE = datetime(2021, 3, 17)


@pytest_asyncio.fixture
async def cleanup_imported():
    yield
    async with AsyncSessionLocal() as db:
        ids = (await db.execute(select(Equipment.id).where(Equipment.code == CODE))).scalars().all()
        for eid in ids:
            await db.execute(delete(AuditLog).where(AuditLog.target_id == eid))
        await db.execute(delete(Equipment).where(Equipment.code == CODE))
        await db.commit()


def _register_file(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "คณะเทคโนฯดิจิทัล"
    for _ in range(4):
        ws.append([None])
    # คอลัมน์: 0 ลำดับ, 1 รหัส, 2 ชื่อ, 3 ราคา, 4 ว/ด/ป ที่รับ, 5 ปกติ, ..., 11 สถานที่
    ws.append([1, CODE, "ออสซิลโลสโคป Rigol DS1054Z", FILE_PRICE, FILE_DATE,
               "P", None, None, None, None, "คณะ", "15311"])
    path = tmp_path / "register.xlsx"
    wb.save(path)
    return path


def test_parse_workbook_reads_price_and_date(tmp_path):
    rows, _skipped, _sn = parse_workbook(str(_register_file(tmp_path)))
    assert len(rows) == 1
    assert rows[0]["unit_value"] == float(FILE_PRICE)
    assert rows[0]["acquired_at"] == FILE_DATE.date()


def test_diff_fills_only_empty_fields(tmp_path):
    """ช่องว่าง → เสนอเติม · ช่องที่มีค่าแล้ว → ต้องไม่เสนอทับ แม้ค่าในไฟล์จะต่างกัน"""
    rows, _s, _sn = parse_workbook(str(_register_file(tmp_path)))
    base = {"id": 1, "name": "ออสซิลโลสโคป Rigol DS1054Z", "location": "15311",
            "status": "available", "item_type": "durable"}

    empty = diff_rows(rows, {CODE: {**base, "unit_value": None, "acquired_at": None}})[0]
    assert empty["action"] == "update"
    assert empty["changes"]["unit_value"] == [None, float(FILE_PRICE)]
    assert empty["changes"]["acquired_at"] == [None, FILE_DATE.date().isoformat()]

    filled = diff_rows(rows, {CODE: {**base, "unit_value": 111.0, "acquired_at": date(2019, 1, 1)}})[0]
    assert "unit_value" not in filled["changes"]
    assert "acquired_at" not in filled["changes"]
    assert filled["action"] == "unchanged"


def test_diff_change_values_are_json_safe(tmp_path):
    """changes ถูกเขียนลง audit_logs.detail (JSONB) ตรง ๆ — date ดิบจะทำให้ commit พัง 500"""
    import json
    rows, _s, _sn = parse_workbook(str(_register_file(tmp_path)))
    base = {"id": 1, "name": "ออสซิลโลสโคป Rigol DS1054Z", "location": "15311",
            "status": "available", "item_type": "durable", "unit_value": None, "acquired_at": None}
    json.dumps(diff_rows(rows, {CODE: base})[0]["changes"])  # ต้องไม่ raise TypeError


@pytest.mark.asyncio(loop_scope="session")
async def test_commit_writes_price_and_date_then_is_idempotent(client, admin_token, tmp_path, cleanup_imported):
    """นำเข้าจริง → ราคา/วันที่เข้า DB · นำเข้าไฟล์เดิมซ้ำ → ไม่มีอะไรให้แก้อีก (idempotent)"""
    h = auth(admin_token)
    path = _register_file(tmp_path)

    async def _preview():
        with open(path, "rb") as f:
            r = await client.post(
                "/equipment/import/preview",
                files={"file": ("register.xlsx", f,
                                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                headers=h,
            )
        assert r.status_code == 200, r.text
        return r.json()

    draft = await _preview()
    row = next(r for r in draft["rows"] if r["code"] == CODE)
    assert row["action"] == "new"
    assert row["unit_value"] == float(FILE_PRICE)
    assert row["acquired_at"] == FILE_DATE.date().isoformat()

    r = await client.post(f"/equipment/import/{draft['import_id']}/commit",
                          json={"filename": "register.xlsx", "rows": [row]}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["new"] == 1

    async with AsyncSessionLocal() as db:
        eq = (await db.execute(select(Equipment).where(Equipment.code == CODE))).scalar_one()
        assert float(eq.unit_value) == float(FILE_PRICE)
        assert eq.acquired_at == FILE_DATE.date()

    # รอบสอง: ไฟล์เดิม ของอยู่ใน DB ครบแล้ว → ต้องเป็น unchanged ไม่ใช่เสนอเติมซ้ำไม่รู้จบ
    draft2 = await _preview()
    row2 = next(r for r in draft2["rows"] if r["code"] == CODE)
    assert row2["action"] == "unchanged", row2["changes"]
