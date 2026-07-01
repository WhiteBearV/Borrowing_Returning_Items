import io
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle, HRFlowable
)

_FONT_DIR = Path(__file__).parent / "fonts"
_REGISTERED = False


def _register_fonts() -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    pdfmetrics.registerFont(TTFont("Thai", str(_FONT_DIR / "Garuda.ttf")))
    pdfmetrics.registerFont(TTFont("Thai-Bold", str(_FONT_DIR / "Garuda-Bold.ttf")))
    _REGISTERED = True


def _style(name: str, **kw) -> ParagraphStyle:
    base = ParagraphStyle(name, fontName="Thai", fontSize=11, leading=16)
    for k, v in kw.items():
        setattr(base, k, v)
    return base


def _fmt_date(dt) -> str:
    if dt is None:
        return "-"
    try:
        return dt.strftime("%d/%m/%Y")
    except Exception:
        return str(dt)


def _fmt_datetime(dt) -> str:
    if dt is None:
        return "-"
    try:
        return dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return str(dt)


def generate_borrow_pdf(req: object) -> bytes:
    """สร้าง PDF ใบยืมอุปกรณ์"""
    _register_fonts()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=20 * mm, bottomMargin=20 * mm,
    )

    title_style = _style("Title", fontName="Thai-Bold", fontSize=16, leading=22, alignment=1)
    sub_style = _style("Sub", fontSize=10, textColor=colors.gray, alignment=1)
    label_style = _style("Label", fontName="Thai-Bold", fontSize=11)
    normal_style = _style("Normal")
    small_style = _style("Small", fontSize=9, textColor=colors.gray)

    W = A4[0] - 40 * mm  # usable width

    elems = []

    # ── Header ──────────────────────────────────────────────────────────────
    elems.append(Paragraph("สถาบันเทคโนโลยีดิจิทัลสวนจิตรลดา (CDTI)", sub_style))
    elems.append(Spacer(1, 4))
    elems.append(Paragraph("ใบยืมอุปกรณ์ / Equipment Borrow Request", title_style))
    elems.append(Spacer(1, 6))
    elems.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#2563EB")))
    elems.append(Spacer(1, 10))

    # ── Request info ─────────────────────────────────────────────────────────
    info_data = [
        ["รหัสคำขอ", getattr(req, "request_code", "-")],
        ["วันที่ยื่นคำขอ", _fmt_datetime(getattr(req, "requested_at", None))],
        ["วันกำหนดคืน", _fmt_date(getattr(req, "due_date", None))],
        ["สถานะ", _status_th(getattr(req, "status", ""))],
        ["วัตถุประสงค์", getattr(req, "purpose", None) or "-"],
    ]

    student_name = getattr(req, "student_name", None)
    student_number = getattr(req, "student_number", None)
    student_email = getattr(req, "student_email", None)
    if student_name:
        info_data.insert(0, ["ชื่อผู้ยืม", student_name])
    if student_number:
        info_data.insert(1, ["รหัสนักศึกษา", student_number])
    if student_email:
        info_data.insert(2, ["อีเมล", student_email])

    info_table = Table(
        [[Paragraph(r[0], label_style), Paragraph(str(r[1]), normal_style)] for r in info_data],
        colWidths=[45 * mm, W - 45 * mm],
    )
    info_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
    ]))
    elems.append(info_table)
    elems.append(Spacer(1, 12))

    # ── Items table ───────────────────────────────────────────────────────────
    elems.append(Paragraph("รายการอุปกรณ์", _style("Sec", fontName="Thai-Bold", fontSize=12)))
    elems.append(Spacer(1, 6))

    items = getattr(req, "items", [])
    header = [
        Paragraph("#", _style("H", fontName="Thai-Bold", fontSize=10, alignment=1)),
        Paragraph("ชื่ออุปกรณ์", _style("H", fontName="Thai-Bold", fontSize=10)),
        Paragraph("ประเภท", _style("H", fontName="Thai-Bold", fontSize=10, alignment=1)),
        Paragraph("จำนวน", _style("H", fontName="Thai-Bold", fontSize=10, alignment=1)),
        Paragraph("สภาพเมื่อคืน", _style("H", fontName="Thai-Bold", fontSize=10, alignment=1)),
    ]
    rows = [header]
    for i, item in enumerate(items, 1):
        name = getattr(item, "equipment_name", None) or str(getattr(item, "equipment_id", "-"))
        type_th = "ครุภัณฑ์" if getattr(item, "item_type_snapshot", "") == "durable" else "วัสดุสิ้นเปลือง"
        condition = _condition_th(getattr(item, "condition_on_return", None))
        rows.append([
            Paragraph(str(i), _style(f"c{i}", fontSize=10, alignment=1)),
            Paragraph(name, _style(f"n{i}", fontSize=10)),
            Paragraph(type_th, _style(f"t{i}", fontSize=10, alignment=1)),
            Paragraph(str(getattr(item, "quantity", 1)), _style(f"q{i}", fontSize=10, alignment=1)),
            Paragraph(condition, _style(f"cd{i}", fontSize=10, alignment=1)),
        ])

    col_w = [10 * mm, W - 10 * mm - 30 * mm - 18 * mm - 30 * mm, 30 * mm, 18 * mm, 30 * mm]
    items_table = Table(rows, colWidths=col_w, repeatRows=1)
    items_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2563EB")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F4F6")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    elems.append(items_table)
    elems.append(Spacer(1, 24))

    # ── Signature row ─────────────────────────────────────────────────────────
    sig_data = [[
        _sig_cell("ลายเซ็นผู้ยืม", student_name or ""),
        _sig_cell("ลายเซ็นผู้อนุมัติ / ผู้รับคืน", ""),
    ]]
    sig_table = Table(sig_data, colWidths=[W / 2, W / 2])
    sig_table.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    elems.append(sig_table)

    doc.build(elems)
    return buf.getvalue()


def _status_th(status: str) -> str:
    return {
        "pending": "รออนุมัติ", "approved": "อนุมัติแล้ว",
        "rejected": "ปฏิเสธ", "cancelled": "ยกเลิก", "completed": "คืนครบแล้ว",
    }.get(status, status)


def _condition_th(condition: str | None) -> str:
    if condition is None:
        return "-"
    return {"ok": "ปกติ", "damaged": "เสียหาย", "lost": "สูญหาย"}.get(condition, condition)


def _sig_cell(label: str, name: str):
    style_label = _style("SL", fontSize=10, alignment=1)
    style_name = _style("SN", fontSize=9, textColor=colors.gray, alignment=1)
    return Table(
        [
            [Paragraph("_" * 30, _style("Line", alignment=1))],
            [Paragraph(label, style_label)],
            [Paragraph(f"({name})" if name else "", style_name)],
        ],
        colWidths=["100%"],
    )
