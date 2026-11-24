"""ชื่อ/หมายเหตุที่ขึ้นต้นด้วย = ต้องลงเป็นข้อความในไฟล์ Excel ไม่ใช่สูตร (formula injection) — ไม่แตะ DB"""
import io
from datetime import date

from openpyxl import load_workbook

from app.utils.pdf import SheetRow
from app.utils.stocktake_xlsx import xlsx_rows


def test_formula_like_text_stays_text() -> None:
    evil = '=HYPERLINK("http://x","คลิก")'
    rows = [SheetRow("15310", "DT-D-1", None, evil, None, 100.0, date(2024, 1, 1), "damaged", evil)]
    ws = load_workbook(io.BytesIO(xlsx_rows({"org": "", "title": "", "room": "", "date": "", "inspector": ""}, rows))).active
    cells = [c for row in ws.iter_rows() for c in row if c.value == evil]
    assert cells and all(c.data_type == "s" for c in cells)
    # ผลรวมมูลค่ายังเป็นสูตรตามเดิม
    assert any(c.data_type == "f" and str(c.value).startswith("=SUM") for row in ws.iter_rows() for c in row)
