"""แม่แบบนำเข้า (24 ก.ย. 69) — แม่แบบที่ให้ดาวน์โหลดต้องอ่านกลับด้วย parser จริงได้ครบ ไม่งั้นแม่แบบกับตัวอ่าน
เพี้ยนกันเงียบ ๆ (parser อ่านตามตำแหน่งคอลัมน์ ไม่ error ถ้าผิดที่) · ไม่แตะ DB
"""
from httpx import AsyncClient

from app.services import import_service, student_import_service
from tests.conftest import auth


def test_equipment_template_roundtrip(tmp_path):
    path = tmp_path / "eq.xlsx"
    path.write_bytes(import_service.build_equipment_template())
    rows, skipped, sn = import_service.parse_workbook(str(path))
    assert skipped == []
    durable = next(r for r in rows if r["item_type"] == "durable")
    assert durable["asset_number"] == "69-213-001-001-0001" and durable["code"] == ""
    assert durable["_sn"] == "SN-EXAMPLE-001" and durable["unit_value"] == 25000
    mats = [r for r in rows if r["item_type"] != "durable"]
    assert {r["item_type"] for r in mats} == {"material", "consumable"}
    assert all(r["code"].startswith(import_service.NEW_KEY_PREFIX) for r in mats)  # รหัสว่าง = ระบบออกให้
    assert next(r for r in mats if r["item_type"] == "material")["_sn"] == "SN-EXAMPLE-002"
    assert next(r for r in mats if r["item_type"] == "consumable")["unit_value"] == 5
    assert list(sn.values()) == ["SN-EXAMPLE-003"]


def test_student_template_roundtrip(tmp_path):
    path = tmp_path / "st.xlsx"
    path.write_bytes(student_import_service.build_student_template())
    parsed = student_import_service.parse_file(str(path), "st.xlsx")
    assert [r["student_id"] for r in parsed.rows] == ["6910301001", "6910301002"]
    assert parsed.major == "comp_eng" and parsed.generation and parsed.advisor


def test_material_sn_only_for_quantity_one(tmp_path):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "วัสดุ"
    ws.append(["รหัส", "รายการ", "ประเภท", "หน่วยนับ", "จำนวน", "สถานที่", "ราคา", "SN"])
    ws.append([None, "บอร์ดหลายชิ้น", "วัสดุใช้ซ้ำ", "ชิ้น", 5, "15310", 100, "SN-X"])
    path = tmp_path / "m.xlsx"
    wb.save(path)
    rows, skipped, _ = import_service.parse_workbook(str(path))
    assert rows[0]["_sn"] is None and "SN ใช้ได้เฉพาะแถวจำนวน 1" in skipped[0]["reason"]


async def test_template_endpoints_staff_only(client: AsyncClient, admin_token: str, student_token: str):
    for url in ("/equipment/import/template", "/eligible-students/import/template"):
        assert (await client.get(url, headers=auth(student_token))).status_code == 403
        r = await client.get(url, headers=auth(admin_token))
        assert r.status_code == 200 and r.content[:2] == b"PK"   # xlsx = zip


def test_partial_register_file_does_not_propose_retiring_everything():
    """ไฟล์เพิ่มของไม่กี่ชิ้น (เช่นแม่แบบ) ต้องไม่เสนอปลดระวางครุภัณฑ์ที่เหลือทั้งคลัง — เฉพาะทะเบียนฉบับเต็ม"""
    existing = {f"DT-D-{i:05d}": {"id": i, "asset_number": f"A{i}", "name": "x", "location": None,
                                  "status": "available", "item_type": "durable"} for i in range(1, 11)}
    new_row = {"code": "", "asset_number": "NEW-1", "name": "ของใหม่", "location": None, "status": "available",
               "quantity_available": 1, "category": "อื่น ๆ", "item_type": "durable", "quantity_total": 1,
               "unit": None, "unit_value": None, "acquired_at": None}
    rows = [dict(new_row)]
    import_service.resolve_keys(rows, {}, existing)
    assert {d["action"] for d in import_service.diff_rows(rows, existing)} == {"new"}
    # ทะเบียนฉบับเต็ม (จับคู่ได้ 9 จาก 10) → ชิ้นที่หายไปยังถูกเสนอปลดระวางเหมือนเดิม
    full = [dict(new_row, asset_number=f"A{i}", name="x") for i in range(1, 10)]
    import_service.resolve_keys(full, {}, existing)
    diff = import_service.diff_rows(full, existing)
    assert [d["code"] for d in diff if d["action"] == "retire"] == ["DT-D-00010"]
