import io
from datetime import datetime, timezone
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

from app.core.config import TZ

_FONT_DIR = Path(__file__).parent / "fonts"
_REGISTERED = False

# ต้องตรงกับ label ฝั่ง frontend (RegisterPage.jsx / ProfilePage.jsx / UsersPage.jsx)
_MAJOR_LABEL = {"comp_eng": "วิศวกรรมคอมพิวเตอร์", "digital_design": "ออกแบบดิจิทัล"}


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


def _local(dt):
    """เวลาใน DB เก็บเป็น UTC — เอกสารต้องโชว์เวลาไทย (+7) ไม่งั้น 14:11 จะขึ้นเป็น 7:11"""
    if not isinstance(dt, datetime):
        return dt  # date ธรรมดา (เช่น due_date) ไม่มีเวลา ไม่ต้องแปลง
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TZ)


def _fmt_date(dt) -> str:
    if dt is None:
        return "-"
    try:
        return _local(dt).strftime("%d/%m/%Y")
    except Exception:
        return str(dt)


def _fmt_datetime(dt) -> str:
    if dt is None:
        return "-"
    try:
        return _local(dt).strftime("%d/%m/%Y %H:%M")
    except Exception:
        return str(dt)


def _doc_title(title_th: str, code: str | None = None) -> str:
    """ชื่อเอกสารที่ฝังใน PDF metadata — ไม่มีอันนี้ Chrome จะโชว์แท็บว่า "(anonymous)"

    ตัดครึ่งภาษาอังกฤษออก เหลือชื่อไทยสั้น ๆ ต่อด้วยเลขคำขอ เช่น "ใบยืมอุปกรณ์ REQ-2026-65010-a1b2c3"
    """
    short = title_th.split(" / ")[0]
    return f"{short} {code}" if code else short


def generate_borrow_pdf(req: object) -> bytes:
    """สร้าง PDF ใบยืมอุปกรณ์ ตามแบบฟอร์มกระดาษของคณะ"""
    return _build_form(req, "borrow")


def generate_preview_pdf(req: object) -> bytes:
    """สร้าง PDF ร่างใบยืม (ก่อนกดส่งคำขอ / ยังไม่อนุมัติ) — ฟอร์มเดียวกัน ต่างแค่ประทับว่าเป็นร่าง"""
    return _build_form(req, "draft")


def generate_return_pdf(req: object) -> bytes:
    """สร้าง PDF ใบคืนอุปกรณ์ — เลย์เอาต์ล้อใบยืม ใช้เลขคำขอเดียวกัน ต่างที่สภาพเมื่อคืน"""
    return _build_form(req, "return")


_THAI_MONTHS = ["มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
                "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"]

# ย่อหน้ารับรอง — คัดจากแบบฟอร์มกระดาษของคณะคำต่อคำ ห้ามแก้ถ้อยคำเอง
_PLEDGE = (
    "ข้าพเจ้าขอรับรองว่า จะดูแลรักษาอุปกรณ์ที่ยืมเป็นอย่างดี โดยหากมีความเสียหายใด ๆ หรือมีการ"
    "สูญหายเกิดขึ้น ข้าพเจ้าจะขอรับผิดชอบทั้งหมดทุกกรณีโดยไม่มีเงื่อนไข โดยจักทำการซ่อมแซมให้ใช้การได้"
    "ดังเดิมหรือจัดหาทดแทนให้ครบตามจำนวนที่ยืมในกรณีมีการสูญหายเกิดขึ้น"
)
# ย่อหน้าปิดท้ายใบคืน — คู่กับ _PLEDGE ของใบยืม
_RETURN_NOTE = (
    "ข้าพเจ้าได้ส่งคืนวัสดุ อุปกรณ์ ตามรายการข้างต้นครบถ้วนแล้ว และเจ้าหน้าที่ได้ตรวจรับ"
    "พร้อมบันทึกสภาพของอุปกรณ์แต่ละรายการไว้เป็นหลักฐานตามที่ปรากฏในตาราง"
)
# จำนวนแถวขั้นต่ำในตาราง — ฟอร์มกระดาษเว้นบรรทัดว่างไว้ให้เขียนเพิ่มด้วยมือ
_MIN_ITEM_ROWS = 12

# ป้ายประเภท/หน่วยเริ่มต้นในใบยืม (item_type = durable / material / consumable)
_ITEM_TYPE_TH = {"durable": "ครุภัณฑ์", "material": "วัสดุใช้ซ้ำ", "consumable": "วัสดุสิ้นเปลือง"}
_DEFAULT_UNIT = {"durable": "ชิ้น", "material": "ชิ้น", "consumable": "หน่วย"}


def _fmt_money(v) -> str:
    """มูลค่าต่อชิ้นในใบยืม — ไม่มีราคา = '-' (อุปกรณ์หลายชิ้นยังไม่กรอกมูลค่า)"""
    return f"{float(v):,.2f}" if v is not None else "-"


def _thai_date_parts(dt) -> tuple[str, str, str]:
    """(วัน, เดือนไทย, พ.ศ.) — ฟอร์มราชการเขียนวันที่แยกช่อง ไม่ใช่ 01/07/2569"""
    dt = _local(dt) if dt else None
    if dt is None:
        return "____", "____________", "______"
    return str(dt.day), _THAI_MONTHS[dt.month - 1], str(dt.year + 543)


def _position_th(req: object) -> str:
    """ตำแหน่งผู้ยืมบนฟอร์ม — มีรหัสนักศึกษา = นักศึกษา ไม่มี = บุคลากร (ไม่ต้องเก็บฟิลด์เพิ่ม)"""
    return "นักศึกษา" if getattr(req, "student_number", None) else "อาจารย์/เจ้าหน้าที่"


def _build_form(req: object, kind: str) -> bytes:
    """ใบยืม / ร่างใบยืม / ใบคืนสิ่งของและอุปกรณ์ — เลย์เอาต์เดียวกันทั้งหมด (ดู docs/น.ส.อรพรรณ คล้ายนาค.pdf)

    ใบคืนล้อใบยืมทุกส่วนและใช้เลขคำขอเดียวกัน ต่างแค่หัวเรื่อง วันที่อ้างอิง
    คอลัมน์สุดท้าย (มูลค่า/ชิ้น → สภาพเมื่อคืน) ย่อหน้ารับรอง และป้ายลายเซ็น
    ฟอร์มกระดาษเว้นเส้นให้เซ็นด้วยมือหลังพิมพ์ ไม่ใช่กรอกจากระบบ
    """
    _register_fonts()
    is_return = kind == "return"
    draft = kind == "draft"
    buf = io.BytesIO()
    code = getattr(req, "request_code", None)
    title_th = "ใบคืนสิ่งของและอุปกรณ์" if is_return else "ใบยืมสิ่งของและอุปกรณ์"
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=18 * mm, bottomMargin=15 * mm,
        title=_doc_title(f"{title_th} (ร่าง)" if draft else title_th, code),
        author="ระบบยืม-คืนอุปกรณ์ คณะเทคโนโลยีดิจิทัล",
    )

    center = _style("C", fontName="Thai-Bold", fontSize=14, leading=20, alignment=1)
    center_sub = _style("CS", fontName="Thai-Bold", fontSize=12, leading=18, alignment=1)
    body = _style("B", fontSize=11, leading=18)
    right = _style("R", fontSize=11, leading=18, alignment=2)
    small_gray = _style("SG", fontSize=9, textColor=colors.gray, alignment=1)

    W = A4[0] - 40 * mm
    # ใบคืนอ้างวันที่รับคืนจริง (ยังไม่สรุปครบก็ใช้วันที่ยื่นคำขอไปก่อน)
    doc_dt = getattr(req, "returned_at", None) if is_return else None
    doc_dt = doc_dt or getattr(req, "requested_at", None)
    d, m, y = _thai_date_parts(doc_dt)

    elems: list = [
        Paragraph(title_th, center),
        Paragraph("คณะเทคโนโลยีดิจิทัล สถาบันเทคโนโลยีจิตรลดา", center_sub),
        Spacer(1, 6),
    ]
    if draft:
        elems.append(Paragraph("— ร่าง / ยังไม่ได้รับอนุมัติ —", small_gray))
    if code:
        elems.append(Paragraph(f"เลขที่คำขอ {code}", small_gray))
    elems.append(Spacer(1, 10))

    req_dt = _local(doc_dt)
    time_str = req_dt.strftime("%H:%M") if getattr(req_dt, "hour", None) is not None else "____"
    elems.append(Paragraph(f"วันที่ {d} เดือน {m} พ.ศ. {y} &nbsp;&nbsp; เวลา {time_str} น.", right))
    elems.append(Spacer(1, 4))
    name = getattr(req, "student_name", None) or "____________________"
    number = getattr(req, "student_number", None)
    who = f"{name} ({number})" if number else name
    elems.append(Paragraph(
        f"ข้าพเจ้า <u>{who}</u> &nbsp;&nbsp;&nbsp; ตำแหน่ง <u>{_position_th(req)}</u>", body))
    major = _MAJOR_LABEL.get(getattr(req, "student_major", None))
    major_part = f"สาขา <u>{major}</u> &nbsp;&nbsp;&nbsp; " if major else ""
    elems.append(Paragraph(f"{major_part}ฝ่ายงาน <u>คณะเทคโนโลยีดิจิทัล</u>", body))
    contact = getattr(req, "student_email", None)
    if contact:
        elems.append(Paragraph(f"ช่องทางติดต่อ <u>{contact}</u>", body))
    purpose = getattr(req, "purpose", None)
    if is_return:
        elems.append(Paragraph(
            f"ขอส่งคืนวัสดุ อุปกรณ์ ตามใบยืมเลขที่ <u>{code or '-'}</u> ดังรายการต่อไปนี้", body))
        elems.append(Paragraph(
            f"วันที่ยืม <u>{_fmt_datetime(getattr(req, 'requested_at', None))}</u>"
            f" &nbsp;&nbsp; กำหนดคืน <u>{_fmt_date(getattr(req, 'due_date', None))}</u>", body))
    else:
        elems.append(Paragraph(
            "มีความประสงค์จะขอยืมวัสดุ อุปกรณ์ ดังรายการต่อไปนี้"
            + (f" (เพื่อ {purpose})" if purpose else ""), body))
        elems.append(Paragraph(
            f"กำหนดคืน (โดยประมาณ) <u>{_fmt_date(getattr(req, 'due_date', None))}</u>", body))
    elems.append(Spacer(1, 10))

    # ── ตารางรายการ ──
    # ใบยืม: ที่ | รหัส | ชื่ออุปกรณ์ | ประเภท | จำนวน | มูลค่า/ชิ้น
    # ใบคืน: ที่ | รหัส | ชื่ออุปกรณ์ | ประเภท | จำนวน | สภาพเมื่อคืน | วันเวลาที่คืน
    def _h(t: str) -> Paragraph:
        return Paragraph(t, _style(f"h{t}", fontName="Thai-Bold", fontSize=10, alignment=1))

    items = list(getattr(req, "items", []))
    if is_return:
        # ใบคืนสะสมเฉพาะชิ้นที่คืนแล้ว เรียงตามเวลาที่คืน — คืนเพิ่มภายหลังจะโผล่เป็นแถวใหม่พร้อมเวลาของตัวเอง
        items = sorted(
            [it for it in items if getattr(it, "returned", False)],
            key=lambda it: getattr(it, "returned_at", None) or datetime.min.replace(tzinfo=timezone.utc),
        )
        header = [_h("ที่"), _h("รหัส"), _h("ชื่ออุปกรณ์"), _h("ประเภท"), _h("จำนวน"),
                  _h("สภาพเมื่อคืน"), _h("วันเวลาที่คืน")]
    else:
        header = [_h("ที่"), _h("รหัส"), _h("ชื่ออุปกรณ์"), _h("ประเภท"), _h("จำนวน"), _h("มูลค่า/ชิ้น")]
    ncol = len(header)
    rows = [header]
    for i, item in enumerate(items, 1):
        itype = getattr(item, "item_type_snapshot", None)
        unit = getattr(item, "equipment_unit", None) or _DEFAULT_UNIT.get(itype, "ชิ้น")
        qty = getattr(item, "quantity", 1)
        # ร่าง/พรีวิว (ยังไม่อนุมัติ): ห้ามโชว์รหัสหน่วยเจาะจง เพราะระบบเลือก "หน่วยว่างรหัสต่ำสุด" ใหม่ทุกครั้ง
        # ที่เรียก ยังไม่ sync กันระหว่างตะกร้า/คำขอ/อนุมัติ รหัสที่เห็นตอนร่างอาจไม่ตรงของจริงตอนอนุมัติ
        # เขียนบอกตรง ๆ ว่า "รออนุมัติ" แทน "-" เฉย ๆ กันผู้ยืมสับสนว่าทำไมไม่มีรหัส
        code_display = "รออนุมัติ" if draft else (getattr(item, "equipment_code", None) or "-")
        cells = [
            Paragraph(str(i), _style(f"i{i}", fontSize=10, alignment=1)),
            Paragraph(code_display, _style(f"c{i}", fontSize=9, alignment=1)),
            Paragraph(getattr(item, "equipment_name", None) or "-", _style(f"n{i}", fontSize=10)),
            Paragraph(_ITEM_TYPE_TH.get(itype, "-"), _style(f"t{i}", fontSize=9, alignment=1)),
            Paragraph(f"{qty} {unit}", _style(f"q{i}", fontSize=10, alignment=1)),
        ]
        if is_return:
            cells.append(Paragraph(_condition_th(getattr(item, "condition_on_return", None)),
                                   _style(f"v{i}", fontSize=9, alignment=1)))
            cells.append(Paragraph(_fmt_datetime(getattr(item, "returned_at", None)),
                                   _style(f"rt{i}", fontSize=8, alignment=1)))
        else:
            cells.append(Paragraph(_fmt_money(getattr(item, "equipment_value", None)),
                                   _style(f"v{i}", fontSize=9, alignment=2)))
        rows.append(cells)
    # แถวว่างเหมือนฟอร์มกระดาษ — ใช้ nbsp แทนสตริงว่างเพื่อดันความสูงแถวให้เท่ากับแถวมีข้อมูล
    blank = Paragraph("&nbsp;", _style("blank", fontSize=11, leading=17))
    rows += [[blank] * ncol] * max(0, _MIN_ITEM_ROWS - len(items))

    # แถวรวมมูลค่า (เฉพาะใบยืม) — ผู้ยืมต้องเห็นวงเงินรวมที่ต้องรับผิดชอบ
    total = sum((getattr(i, "equipment_value", None) or 0) * getattr(i, "quantity", 1) for i in items)
    if not is_return and total:
        rows.append([
            blank, blank, blank, blank,
            Paragraph("รวมมูลค่า", _style("tl", fontName="Thai-Bold", fontSize=10, alignment=2)),
            Paragraph(_fmt_money(total), _style("tv", fontName="Thai-Bold", fontSize=9, alignment=2)),
        ])

    # "วัสดุสิ้นเปลือง" ยาวสุดในคอลัมน์ประเภท ต้อง 26mm ไม่งั้นตัดบรรทัด
    if is_return:
        col = [10 * mm, 26 * mm, W - 10 * mm - 26 * mm - 22 * mm - 20 * mm - 22 * mm - 28 * mm,
               22 * mm, 20 * mm, 22 * mm, 28 * mm]
    else:
        col = [10 * mm, 30 * mm, W - 10 * mm - 30 * mm - 26 * mm - 22 * mm - 26 * mm, 26 * mm, 22 * mm, 26 * mm]
    # rowHeights=None (auto) — ชื่ออุปกรณ์ยาว ๆ ต้องขยายแถวเอง ไม่งั้นข้อความล้นทับเส้นตาราง
    table = Table(rows, colWidths=col, repeatRows=1)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.7, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (2, 1), (2, -1), 6),
    ]))
    elems.append(table)
    elems.append(Spacer(1, 12))

    elems.append(Paragraph(
        f"&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;{_RETURN_NOTE if is_return else _PLEDGE}",
        _style("P", fontSize=11, leading=18)))
    elems.append(Spacer(1, 18))

    # ── ลายเซ็น: ใบยืม = ผู้ยืม/ผู้อนุมัติ, ใบคืน = ผู้คืน/ผู้รับคืน (แยกใบกันตามข้อ 1.10) ──
    blank = "(............................................)"
    borrower = f"({name})" if getattr(req, "student_name", None) else blank
    approver = getattr(req, "approver_name", None)
    receiver = getattr(req, "receiver_name", None)
    signer = receiver if is_return else approver
    right_name = f"({signer})" if signer else blank
    line = "............................................"
    sig = _style("S", fontSize=11, leading=22)
    sig_c = _style("SC", fontSize=10, leading=16, alignment=1)
    date_line = "วันที่ .......... เดือน .................... พ.ศ. .........."
    left_label, right_label = ("ผู้คืน", "ผู้รับคืน") if is_return else ("ผู้ยืม", "ผู้อนุมัติ")

    sig_rows = [
        [Paragraph(f"{left_label} {line}", sig), Paragraph(f"{right_label} {line}", sig)],
        [Paragraph(borrower, sig_c), Paragraph(right_name, sig_c)],
        [Paragraph(date_line, sig), Paragraph(date_line, sig)],
    ]
    sig_table = Table(sig_rows, colWidths=[W / 2, W / 2])
    sig_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elems.append(sig_table)

    doc.build(elems)
    return buf.getvalue()


# ── เอกสารรับเข้า/ปลดระวาง (ร่างเข้า/ร่างออก) ───────────────────────────────
# ต่างจากใบยืม: อ้างอิงช่วงวันที่ + รายการหลายชิ้นจาก audit log ไม่ผูกกับคำขอเดียว
def generate_repair_pdf(rows: list[dict], requester: str, unit: str = "คณะเทคโนโลยีดิจิทัล") -> bytes:
    """บันทึกข้อความ "ขออนุมัติซ่อมแซมครุภัณฑ์" ตามแบบฟอร์มของสถาบัน (พศ.004:1)

    ระบบเติมให้เฉพาะส่วนที่มีข้อมูลจริง: ตารางครุภัณฑ์ที่ชำรุด (รายการ/รหัส/ลักษณะที่ชำรุด)
    ช่องความเห็นผู้ตรวจสอบ ประวัติการซ่อม และช่องอนุมัติ เว้นว่างให้กรอก/เซ็นด้วยมือตามของจริง
    แต่ละ row: {name, code, damage, note}
    """
    _register_fonts()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=15 * mm, bottomMargin=12 * mm,
        title=_doc_title("บันทึกข้อความ ขออนุมัติซ่อมแซมครุภัณฑ์"),
        author="ระบบยืม-คืนอุปกรณ์ คณะเทคโนโลยีดิจิทัล",
    )
    W = A4[0] - 36 * mm
    title = _style("RT", fontName="Thai-Bold", fontSize=16, leading=22, alignment=1)
    body = _style("RB", fontSize=10.5, leading=17)
    small = _style("RS", fontSize=9.5, leading=15)
    dots = "." * 60
    d, m, y = _thai_date_parts(_now())

    def _h(t: str) -> Paragraph:
        return Paragraph(t, _style(f"rh{t}", fontName="Thai-Bold", fontSize=10, alignment=1))

    elems: list = [
        Paragraph("บันทึกข้อความ", title),
        Spacer(1, 8),
        Paragraph(f"<b>ส่วนงาน</b> {unit} {dots}", body),
        Paragraph(f"<b>ที่</b> ....................................... <b>วันที่</b> {d} {m} {y}", body),
        Paragraph("<b>เรื่อง</b> ขออนุมัติซ่อมแซมครุภัณฑ์", body),
        Spacer(1, 6),
        Paragraph("<b>เรียน</b> ผู้มีอำนาจอนุมัติวงเงิน", body),
        Spacer(1, 4),
        Paragraph(f"&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;ด้วยหน่วยงาน {unit} "
                  "มีความประสงค์จะขออนุมัติซ่อมแซมครุภัณฑ์ รายละเอียดดังนี้", body),
        Spacer(1, 8),
    ]

    data = [[_h("ลำดับที่"), _h("รายการ"), _h("รหัสครุภัณฑ์"), _h("ลักษณะ/สภาพที่ชำรุด"), _h("หมายเหตุ")]]
    for i, r in enumerate(rows, 1):
        data.append([
            Paragraph(str(i), _style(f"ri{i}", fontSize=9.5, alignment=1)),
            Paragraph(r.get("name") or "-", _style(f"rn{i}", fontSize=9.5)),
            Paragraph(r.get("code") or "-", _style(f"rc{i}", fontSize=8.5, alignment=1)),
            Paragraph(r.get("damage") or "-", _style(f"rd{i}", fontSize=9.5)),
            Paragraph(r.get("note") or "", _style(f"rm{i}", fontSize=9)),
        ])
    data += [["", "", "", "", ""]] * max(0, 3 - len(rows))  # ฟอร์มจริงมีบรรทัดว่างให้เขียนเพิ่ม

    table = Table(data, colWidths=[15 * mm, W - 15 * mm - 35 * mm - 45 * mm - 25 * mm,
                                   35 * mm, 45 * mm, 25 * mm])
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.7, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elems.append(table)
    elems.append(Spacer(1, 10))

    # ความเห็นผู้ตรวจสอบ + แหล่งเงิน + คณะกรรมการ — เว้นให้กรอกมือ (ระบบไม่รู้ราคา/งบ)
    for line in [
        "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;โดยผู้ตรวจสอบได้ตรวจสอบแล้วมีความเห็นว่า",
        "[  ] ซ่อมได้เองไม่มีค่าใช้จ่าย &nbsp; [  ] ซ่อมได้เองมีค่าใช้จ่าย โดยเปลี่ยนวัสดุ/อุปกรณ์ที่ชำรุด "
        "วงเงินประมาณ ............... บาท (แนบใบเสนอราคา)",
        "[  ] ส่งซ่อมภายนอก วงเงินประมาณ ............... บาท (แนบใบเสนอราคา)",
        "[  ] ไม่ควรซ่อม เหตุผล ....................................................................................",
        "",
        "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;การซ่อมแซมครุภัณฑ์ครั้งนี้ใช้เงินงบประมาณจากแหล่งเงิน "
        ".............................. ประจำปีงบประมาณ พ.ศ. ..........",
        "งาน/โครงการ .............................. รหัสงบ .............................. "
        "และขอเสนอรายชื่อคณะกรรมการซื้อ/จ้าง สำหรับงานซ่อม ดังนี้",
        "คณะกรรมการซื้อ/จ้าง &nbsp; 1. ........................ &nbsp; 2. ........................ "
        "&nbsp; 3. ........................",
        "คณะกรรมการตรวจรับพัสดุ หรือ ผู้ตรวจรับพัสดุ &nbsp; 1. ........................ "
        "&nbsp; 2. ........................ &nbsp; 3. ........................",
    ]:
        elems.append(Paragraph(line, small) if line else Spacer(1, 4))
    elems.append(Spacer(1, 14))

    sig = Table([[
        Paragraph(f"ลงชื่อ ........................................ ผู้ขอซ่อม<br/>"
                  f"&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;( {requester} )<br/>"
                  "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;......../......../........", small),
        Paragraph("ลงชื่อ ........................................ ผู้ตรวจสอบ<br/>"
                  "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;(........................................)<br/>"
                  "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;......../......../........", small),
    ]], colWidths=[W / 2, W / 2])
    sig.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    elems.append(sig)
    elems.append(Spacer(1, 12))

    # ช่องอนุมัติ 3 ระดับ ตามฟอร์มกระดาษ — เว้นว่างทั้งหมด
    approve = Table([
        [_h("ผู้อำนวยการ/คณบดี"), _h("รองอธิการบดี"), _h("อธิการบดี")],
        [Paragraph("[  ] เห็นชอบ &nbsp; [  ] อนุมัติ<br/><br/>ลงชื่อ ....................<br/>"
                   "(....................)<br/>วันที่ ....................", small),
         Paragraph("[  ] เห็นชอบ &nbsp; [  ] อนุมัติ<br/><br/>ลงชื่อ ....................<br/>"
                   "(....................)<br/>วันที่ ....................", small),
         Paragraph("[  ] อนุมัติ &nbsp; [  ] อื่น ๆ ..........<br/><br/>ลงชื่อ ....................<br/>"
                   "(....................)<br/>วันที่ ....................", small)],
    ], colWidths=[W / 3] * 3)
    approve.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.7, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    elems.append(approve)

    doc.build(elems)
    return buf.getvalue()


_STOCK_META = {
    "receipt":  ("ใบรับเข้าคลัง (ร่างเข้า) / Stock Receipt", "#2563EB", "รายการที่นำเข้า"),
    "disposal": ("ใบปลดระวาง (ร่างออก) / Stock Disposal", "#B91C1C", "รายการที่ปลดระวาง"),
}


def _build_receipt_form(date_from: str, date_to: str, generated_by: str, rows: list[dict]) -> bytes:
    """ใบรับเข้าคลัง — เลย์เอาต์ตาม "รายการเบิกครุภัณฑ์" ของสถาบัน (ดู docs/ตัวอย่างใบรับครุภัณฑ์ ดิจิทัล.pdf)

    ระบบเติมรายการ + รหัสครุภัณฑ์รายชิ้นจาก audit log ส่วนราคา/เลขที่ใบเบิก/เลขใบตรวจรับ
    เว้นว่างให้กรอกมือ เพราะระบบคลังไม่ได้เก็บข้อมูลฝั่งจัดซื้อ (ราคา สัญญา ใบตรวจรับ)
    """
    _register_fonts()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=15 * mm, bottomMargin=15 * mm,
        title=_doc_title("รายการเบิกครุภัณฑ์ (ใบรับเข้าคลัง)", f"{date_from} - {date_to}"),
        author="ระบบยืม-คืนอุปกรณ์ คณะเทคโนโลยีดิจิทัล",
    )
    W = A4[0] - 36 * mm
    center = _style("KC", fontName="Thai-Bold", fontSize=13, leading=19, alignment=1)
    center_sub = _style("KS", fontSize=12, leading=18, alignment=1)
    body = _style("KB", fontSize=10.5, leading=17)
    right = _style("KR", fontSize=10, leading=16, alignment=2)
    small = _style("KM", fontSize=9.5, leading=15)
    d, m, y = _thai_date_parts(_now())

    elems: list = [
        Paragraph("สถาบันเทคโนโลยีจิตรลดา", center_sub),
        Paragraph("รายการเบิกครุภัณฑ์", center),
        Spacer(1, 8),
        Paragraph("เลขที่ใบเบิก ...........................", right),
        Paragraph("อ้างอิงใบตรวจรับ ...........................", right),
        Paragraph(f"วันที่ {d} {m} {y}", right),
        Spacer(1, 6),
        Paragraph(f"ชื่อ-สกุล <u>{generated_by}</u> &nbsp;&nbsp; ตำแหน่ง ......................... "
                  "&nbsp;&nbsp; หน่วยงาน <u>คณะเทคโนโลยีดิจิทัล</u>", body),
        Paragraph(f"รายการที่นำเข้าคลังระหว่างวันที่ {date_from} ถึง {date_to} "
                  f"รวม {len(rows)} รายการ", small),
        Spacer(1, 8),
    ]

    def _h(t: str) -> Paragraph:
        return Paragraph(t, _style(f"kh{t}", fontName="Thai-Bold", fontSize=9.5, alignment=1))

    # คอลัมน์ตามใบจริง — ราคาเว้นว่าง (ระบบคลังไม่รู้ราคา ต้องกรอกจากใบจัดซื้อ)
    data = [[_h("ลำดับ"), _h("รายการ"), _h("จำนวน"), _h("ราคาต่อหน่วย"), _h("จำนวนเงิน"), _h("รหัสครุภัณฑ์")]]
    for i, r in enumerate(rows, 1):
        unit_th = {"durable": "เครื่อง/ชิ้น", "material": "ชิ้น", "consumable": "หน่วย"}.get(
            r.get("item_type") or "", "")
        qty = r.get("quantity")
        data.append([
            Paragraph(str(i), _style(f"ka{i}", fontSize=9, alignment=1)),
            Paragraph(str(r.get("name") or "-"), _style(f"kb{i}", fontSize=9)),
            Paragraph(f"{qty} {unit_th}" if qty is not None else "-",
                      _style(f"kc{i}", fontSize=9, alignment=1)),
            "", "",
            Paragraph(str(r.get("code") or "-"), _style(f"kd{i}", fontSize=8.5, alignment=1)),
        ])
    data += [["", "", "", "", "", ""]] * max(0, 5 - len(rows))

    table = Table(data, colWidths=[13 * mm, W - 13 * mm - 22 * mm - 28 * mm - 24 * mm - 42 * mm,
                                   22 * mm, 28 * mm, 24 * mm, 42 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.6, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elems.append(table)
    elems.append(Spacer(1, 20))

    sig = Table([[
        Paragraph("ลงชื่อ ........................................ ผู้เบิก<br/>"
                  f"&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;( {generated_by} )<br/>"
                  "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;......../......../........", small),
        Paragraph("ลงชื่อ ........................................ ผู้จ่ายครุภัณฑ์<br/>"
                  "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;(........................................)<br/>"
                  "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;......../......../........", small),
    ]], colWidths=[W / 2, W / 2])
    sig.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    elems.append(sig)

    doc.build(elems)
    return buf.getvalue()


def generate_stock_document_pdf(
    kind: str,
    date_from: str,
    date_to: str,
    generated_by: str,
    rows: list[dict],
) -> bytes:
    """สร้าง PDF เอกสารรับเข้าคลัง (receipt) หรือปลดระวาง (disposal)

    รวมรายการหลายชิ้นในช่วงวันที่เดียว ให้เห็นว่านำอะไรเข้า/ออกบ้าง ใครทำ เมื่อไร
    (ตอบข้อเสนออาจารย์ #2/#3: เอกสารร่างเข้า/ร่างออก) — ดึงจาก audit log เป็นหลักฐาน
    แต่ละ row: {code, name, item_type, quantity, actor, date, reason}
    """
    if kind == "receipt":
        return _build_receipt_form(date_from, date_to, generated_by, rows)

    _register_fonts()
    title_th, accent, items_label = _STOCK_META.get(kind, _STOCK_META["receipt"])
    is_disposal = kind == "disposal"

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=20 * mm, bottomMargin=20 * mm,
        title=_doc_title(title_th, f"{date_from} - {date_to}"),
        author="ระบบยืม-คืนอุปกรณ์",
    )
    title_style = _style("Title", fontName="Thai-Bold", fontSize=16, leading=22, alignment=1)
    sub_style = _style("Sub", fontSize=10, textColor=colors.gray, alignment=1)
    label_style = _style("Label", fontName="Thai-Bold", fontSize=11)
    normal_style = _style("Normal")

    W = A4[0] - 40 * mm
    elems = []

    elems.append(Paragraph("สถาบันเทคโนโลยีดิจิทัลสวนจิตรลดา (CDTI)", sub_style))
    elems.append(Spacer(1, 4))
    elems.append(Paragraph(title_th, title_style))
    elems.append(Spacer(1, 6))
    elems.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor(accent)))
    elems.append(Spacer(1, 10))

    # ── ข้อมูลเอกสาร ──
    info_data = [
        ["ช่วงวันที่", f"{date_from} ถึง {date_to}"],
        ["ออกเอกสารโดย", generated_by],
        ["วันที่ออกเอกสาร", _fmt_datetime(_now())],
        ["จำนวนรายการ", str(len(rows))],
    ]
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

    elems.append(Paragraph(items_label, _style("Sec", fontName="Thai-Bold", fontSize=12)))
    elems.append(Spacer(1, 6))

    # ร่างออกโชว์คอลัมน์ "เหตุผล" แทน "วันที่" (สำคัญกว่าในบริบทปลดระวาง)
    last_col = "เหตุผล" if is_disposal else "วันที่"

    def _h(t, align=0):
        return Paragraph(t, _style("H", fontName="Thai-Bold", fontSize=10, alignment=align))

    header = [_h("#", 1), _h("รหัส"), _h("ชื่อรายการ"), _h("ประเภท", 1),
              _h("จำนวน", 1), _h("ผู้ทำ"), _h(last_col)]
    table_rows = [header]
    for i, r in enumerate(rows, 1):
        type_th = {"durable": "ครุภัณฑ์", "material": "วัสดุ", "consumable": "วัสดุสิ้นเปลือง"}.get(
            r.get("item_type") or "", "-")
        last_val = (r.get("reason") or "-") if is_disposal else _fmt_date(r.get("date"))
        table_rows.append([
            Paragraph(str(i), _style(f"a{i}", fontSize=9, alignment=1)),
            Paragraph(str(r.get("code") or "-"), _style(f"b{i}", fontSize=9)),
            Paragraph(str(r.get("name") or "-"), _style(f"c{i}", fontSize=9)),
            Paragraph(type_th, _style(f"d{i}", fontSize=9, alignment=1)),
            Paragraph(str(r.get("quantity") if r.get("quantity") is not None else "-"),
                      _style(f"e{i}", fontSize=9, alignment=1)),
            Paragraph(str(r.get("actor") or "-"), _style(f"f{i}", fontSize=9)),
            Paragraph(str(last_val), _style(f"g{i}", fontSize=9)),
        ])

    col_w = [8 * mm, 30 * mm, W - 8 * mm - 30 * mm - 22 * mm - 15 * mm - 28 * mm - 28 * mm,
             22 * mm, 15 * mm, 28 * mm, 28 * mm]
    tbl = Table(table_rows, colWidths=col_w, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(accent)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F4F6")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elems.append(tbl)
    elems.append(Spacer(1, 24))

    sig_left = "ลายเซ็นผู้จัดทำ"
    sig_right = "ลายเซ็นผู้อนุมัติ" if is_disposal else "ลายเซ็นผู้รับเข้า"
    sig_table = Table([[_sig_cell(sig_left, generated_by), _sig_cell(sig_right, "")]],
                      colWidths=[W / 2, W / 2])
    sig_table.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    elems.append(sig_table)

    doc.build(elems)
    return buf.getvalue()


def _now() -> datetime:
    """เวลาปัจจุบันตามเวลาไทย — เซิร์ฟเวอร์รันเป็น UTC จะได้ไม่ออกใบเป็นเวลา UTC"""
    return datetime.now(TZ)


def _status_th(status: str) -> str:
    return {
        "pending": "รออนุมัติ", "approved": "อนุมัติแล้ว",
        "rejected": "ปฏิเสธ", "cancelled": "ยกเลิก", "completed": "คืนครบแล้ว",
    }.get(status, status)


def _condition_th(condition: str | None) -> str:
    if condition is None:
        return "-"
    return {
        "ok": "ปกติ", "damaged": "เสียหาย", "lost": "สูญหาย",
        "returned_full": "คืนครบ", "used_up": "ใช้หมด", "discarded": "ทิ้ง (เสียหาย)",
    }.get(condition, condition)


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
