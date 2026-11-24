"""ใบตรวจครุภัณฑ์ประจำห้อง แบบ Excel — คอลัมน์ A–R ตรงกับชีตแรกของ "รายงานทะเบียนคุมทรัพย์สิน" ของคณะ (23 พ.ย. 69)

ผู้ใช้ให้ใช้ไฟล์นั้นเป็นแบบ (docs/รายงานทะเบียนคุมทรัพย์สิน … 4 พฤศจิกายน 2568.xlsx) เพื่อคัดลอกแถวไปวางต่อในทะเบียนหลักได้ตรงช่อง
ติ๊ก = ตัวอักษร "✓" จริง — ต้นฉบับใช้ "P" + ฟอนต์ Wingdings 2 แต่เครื่องที่ไม่มีฟอนต์นั้นเห็นเป็นตัว P (ผู้ใช้เจอจริง)
พรีวิวบนหน้าเว็บ (`preview_rows`) ใช้แถวชุดเดียวกับไฟล์ (`_cells`) — สิ่งที่เห็นก่อนโหลด = สิ่งที่อยู่ในไฟล์เสมอ
"""
import io
from datetime import date, datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from app.utils.pdf import CONDITION_COLUMNS, SheetRow, _fmt_date_th_full, _fmt_money, round_rows

ORG = "คณะเทคโนโลยีดิจิทัล"
TICK = "✓"
HEADERS = ["ลำดับที่", "รหัสครุภัณฑ์", "รายการครุภัณฑ์ (รุ่น/ยี่ห้อ)", "ราคา", "ว/ด/ป\nที่รับ",
           *(label for _, label in CONDITION_COLUMNS),
           "หน่วยงาน\nรับผิดชอบ", "สถานที่ตั้ง/\nจัดเก็บ", "หน่วยงานรับผิดชอบ", "ชื่อห้อง", "อาคาร", "ชั้น", "ห้อง", "หมายเหตุ"]
WIDTHS = [7, 22, 48, 11, 11, 6, 6, 6, 8, 9, 14, 12, 14, 24, 7, 6, 9, 36]
TICK_COLS = range(6, 11)  # F–J (1-based)


def room_head(rnd: object) -> dict[str, str]:
    """หัวใบตรวจรายห้อง"""
    return {
        "org": "สถาบันเทคโนโลยีจิตรลดา",
        "title": "ใบตรวจครุภัณฑ์ประจำห้อง (รายงานทะเบียนคุมทรัพย์สิน)",
        "room": f"{ORG} · ห้อง {rnd.location}",
        "date": f"วันที่ตรวจ {_fmt_date_th_full(rnd.started_at)}",
        "inspector": f"ผู้ตรวจ {rnd.started_by_name or '-'}",
    }


def summary_head(as_of: object) -> dict[str, str]:
    """หัวใบรวมทุกห้อง — แบบเดียวกับไฟล์ทะเบียนของคณะ ("ข้อมูล ณ วันที่ …")"""
    return {"org": "สถาบันเทคโนโลยีจิตรลดา", "title": "รายงานทะเบียนคุมทรัพย์สิน (รวมทุกห้อง)",
            "room": ORG, "date": f"ข้อมูล ณ วันที่ {_fmt_date_th_full(as_of)}", "inspector": ""}


def _cells(rows: list[SheetRow]) -> list[list]:
    """แถว Excel (ค่าดิบ) — ใช้ร่วมกันทั้งไฟล์และพรีวิว"""
    return [
        [n, r.asset_number or r.code, r.name, r.unit_value, r.acquired_at,
         *(TICK if r.condition == key else None for key, _ in CONDITION_COLUMNS),
         ORG, r.room, ORG, r.location_detail, None, None, r.room, r.note or None]
        for n, r in enumerate(rows, 1)
    ]


def preview(rnd: object) -> dict:
    return preview_rows(room_head(rnd), round_rows(rnd))


def generate_stocktake_xlsx(rnd: object) -> bytes:
    return xlsx_rows(room_head(rnd), round_rows(rnd))


def preview_rows(head: dict[str, str], sheet_rows: list[SheetRow]) -> dict:
    """พรีวิวบนหน้าเว็บ — แปลงค่าดิบเป็นข้อความแบบที่ Excel แสดง (ราคา 1,500.00 · วันที่ dd/mm/yyyy)"""
    rows = _cells(sheet_rows)

    def show(v: object, col: int) -> str | None:
        if v is None:
            return None
        if col == 4:
            return _fmt_money(v)
        if isinstance(v, (date, datetime)):
            return v.strftime("%d/%m/%Y")
        return str(v)

    total = sum(float(r[3]) for r in rows if r[3] is not None)
    return {**head, "headers": HEADERS, "rows": [[show(v, c) for c, v in enumerate(r, 1)] for r in rows],
            "total": _fmt_money(total)}


def xlsx_rows(head: dict[str, str], sheet_rows: list[SheetRow]) -> bytes:
    rows = _cells(sheet_rows)
    wb = Workbook()
    ws = wb.active
    ws.title = "ใบตรวจครุภัณฑ์"
    font = Font(name="TH SarabunPSK", size=14)
    bold = Font(name="TH SarabunPSK", size=14, bold=True)
    tick = Font(name="Segoe UI Symbol", size=12, bold=True)  # ไม่มีฟอนต์นี้ โปรแกรมหาฟอนต์อื่นที่มี ✓ ให้เอง
    thin = Side(style="thin")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)

    ws["O1"], ws["O2"], ws["A3"], ws["N3"], ws["A2"] = head["org"], head["title"], head["room"], head["date"], head["inspector"] or None
    for ref in ("O1", "O2", "A3", "N3", "A2"):
        ws[ref].font = bold
    for rng in ("O1:R1", "O2:R2", "N3:R3", "A3:E3", "A2:E2"):
        ws.merge_cells(rng)

    for col, h in enumerate(HEADERS, 1):
        c = ws.cell(row=4, column=col, value=h)
        c.font, c.alignment, c.border = bold, center, box
        c.fill = PatternFill("solid", fgColor="F3F4F6")
    for col, w in enumerate(WIDTHS, 1):
        ws.column_dimensions[ws.cell(row=4, column=col).column_letter].width = w

    for n, row in enumerate(rows, 1):
        r = 4 + n
        for col, v in enumerate(row, 1):
            c = ws.cell(row=r, column=col, value=v)
            c.border = box
            c.font = tick if col in TICK_COLS else font
            c.alignment = center if col not in (3, 14, 18) else Alignment(vertical="center", wrap_text=True)
        ws.cell(row=r, column=4).number_format = "#,##0.00"
        ws.cell(row=r, column=5).number_format = "dd/mm/yyyy"

    total = 5 + len(rows)
    ws.cell(row=total, column=3, value="รวมทั้งสิ้น").font = bold
    ws.cell(row=total, column=4, value=f"=SUM(D5:D{total - 1})").number_format = "#,##0.00"

    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_title_rows = "1:4"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
