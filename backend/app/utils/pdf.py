import os
from dataclasses import dataclass
import io
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.graphics.shapes import Drawing, PolyLine
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle, HRFlowable
)

from app.core.config import TZ, settings
from app.utils.duedate import effective_due_date
from app.utils.pdf_seal import seal_pdf

_FONT_DIR = Path(__file__).parent / "fonts"
_REGISTERED = False

# ต้องตรงกับ label ฝั่ง frontend (RegisterPage.jsx / ProfilePage.jsx / UsersPage.jsx)
def _e(v):
    """escape ข้อความที่ผู้ใช้กรอกก่อนใส่ Paragraph — ReportLab ตีความ <...>/& เป็น markup ทำให้ข้อความหาย
    ("สาย <USB-C>" เหลือ "สาย"), แทรกรูปแบบได้ หรือออกเอกสารไม่ได้เลย (QA-06, 30 ก.ย. 69)
    ข้อความที่ระบบประกอบเอง (<u>, <br/>, &nbsp;) ไม่ต้องผ่านตัวนี้"""
    return escape(str(v)) if v is not None else None


# ป้ายชนิดลายเซ็น — ใช้ทั้งข้อความ error ของ borrow_service._esign และเลขอ้างอิงท้ายเอกสาร
SIGNATURE_LABEL_TH = {
    "handover_borrower": "ผู้ยืม",       # ช่องเซ็นในใบยืม = ผู้ยืม / ผู้อนุมัติ (23 พ.ย. 69 ลงชื่อตอนยื่น/อนุมัติ)
    "handover_staff": "ผู้อนุมัติ",
    "return_borrower": "ผู้คืน",
    "return_staff": "ผู้รับคืน",
}

_MAJOR_LABEL = {"comp_eng": "วิศวกรรมคอมพิวเตอร์", "digital_design": "ออกแบบดิจิทัล"}


def _register_fonts() -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    pdfmetrics.registerFont(TTFont("Thai", str(_FONT_DIR / "Garuda.ttf")))
    pdfmetrics.registerFont(TTFont("Thai-Bold", str(_FONT_DIR / "Garuda-Bold.ttf")))
    # ฟอนต์ลายมือ (OFL) — ชื่อผู้ลงนาม E-sign ตรงช่องเซ็น ให้ดูเป็นลายมือชื่อแทนข้อความระบบ (23 พ.ย. 69)
    pdfmetrics.registerFont(TTFont("Thai-Script", str(_FONT_DIR / "Charmonman-Regular.ttf")))
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


def _fmt_date_short(d) -> str:
    """วันที่แบบย่อในตาราง เช่น "1 ก.ย. 69" — คอลัมน์กำหนดคืนแคบเกินกว่าจะใส่ 01/09/2569"""
    if d is None:
        return "-"
    try:
        d = _local(d)
        return f"{d.day} {_THAI_MONTHS_ABBR[d.month - 1]} {(d.year + 543) % 100:02d}"
    except Exception:
        return str(d)


def _item_due(item: object, req: object, draft: bool):
    """วันครบกำหนดคืนของ 1 รายการที่จะพิมพ์ลงเอกสาร

    ใบยืมจริงใช้ effective_due_date (ต่อเวลาที่อนุมัติแล้วชนะเสมอ — ใบที่พิมพ์ซ้ำหลังต่อเวลา
    จึงขึ้นวันใหม่ถูกต้อง) ส่วนร่าง/พรีวิวยังไม่มีวันจริง ใช้วันที่ผู้ยืม "ขอไว้" ของชิ้นนั้น
    """
    if draft:
        return getattr(item, "requested_due_date", None) or getattr(req, "due_date", None)
    return effective_due_date(item, req)


def _fmt_date_th(d) -> str:
    """วันที่แบบไทยเต็มปี เช่น "30 ก.ย. 2569" — ใช้กับบรรทัดหัวที่พูดถึงกำหนดคืน

    ไม่ใช้ _fmt_date (01/09/2026) กับกำหนดคืน เพราะบรรทัดหัวกับตารางต้องเป็นปฏิทินเดียวกัน
    ไม่งั้นหัวบอก 2026 ตารางบอก 69 ในเอกสารใบเดียวกัน
    """
    if d is None:
        return "-"
    try:
        d = _local(d)
        return f"{d.day} {_THAI_MONTHS_ABBR[d.month - 1]} {d.year + 543}"
    except Exception:
        return str(d)


def _fmt_date_th_full(d) -> str:
    """วันที่ไทยชื่อเดือนเต็ม เช่น "18 พฤศจิกายน 2569" — หัวใบตรวจครุภัณฑ์ (ผู้ใช้ขอไม่เอาตัวย่อ 23 พ.ย. 69)"""
    if d is None:
        return "-"
    d = _local(d)
    return f"{d.day} {_THAI_MONTHS[d.month - 1]} {d.year + 543}"


def _fmt_datetime_th(dt) -> str:
    """วัน+เวลาแบบไทย เช่น "8 ก.ย. 2569 13:00" — ใช้กับนัดรับของ ให้เป็นปฏิทินเดียวกับกำหนดคืนในตาราง"""
    if dt is None:
        return "-"
    try:
        return f"{_fmt_date_th(dt)} {_local(dt):%H:%M}"
    except Exception:
        return str(dt)


def _fmt_datetime_short(dt) -> str:
    """วัน+เวลาแบบย่อสำหรับช่องแคบในใบคืน เช่น 2 ต.ค. 69 14:30"""
    if dt is None:
        return "-"
    try:
        return f"{_fmt_date_short(dt)} {_local(dt).strftime('%H:%M')}"
    except Exception:
        return str(dt)


def _return_cell(item: object, due) -> str:
    """ช่อง "วันเวลาที่คืน" ของใบคืน — กำหนด / คืนจริง / ช้ากี่วัน ในเซลล์เดียว

    "ช้า N วัน" ขึ้นเฉพาะเมื่อเกินกำหนดจริง เป็นหลักฐานประกอบเวลาเรียกค่าปรับ
    (เทียบเฉพาะส่วนวันที่ — คืนวันครบกำหนดตอนบ่ายไม่ถือว่าช้า)
    """
    returned_at = getattr(item, "returned_at", None)
    lines = []
    if due:
        lines.append(f"กำหนด {_fmt_date_short(due)}")
    lines.append(f"คืนจริง {_fmt_datetime_short(returned_at)}" if returned_at else "คืนจริง -")
    if due and returned_at:
        actual = _local(returned_at)
        actual = actual.date() if hasattr(actual, "date") else actual
        late = (actual - due).days
        if late > 0:
            lines.append(f"(ช้า {late} วัน)")
    return "<br/>".join(lines)


def _doc_title(title_th: str, code: str | None = None) -> str:
    """ชื่อเอกสารที่ฝังใน PDF metadata — ไม่มีอันนี้ Chrome จะโชว์แท็บว่า "(anonymous)"

    ตัดครึ่งภาษาอังกฤษออก เหลือชื่อไทยสั้น ๆ ต่อด้วยเลขคำขอ เช่น "ใบยืมอุปกรณ์ REQ-2026-65010-a1b2c3"
    """
    short = title_th.split(" / ")[0]
    return f"{short} {code}" if code else short


def generate_borrow_pdf(req: object, value_source: str = "acquisition") -> bytes:
    """สร้าง PDF ใบยืมอุปกรณ์ ตามแบบฟอร์มกระดาษของคณะ — ประทับตราดิจิทัลทั้งไฟล์ (ร่างไม่ประทับ)"""
    return seal_pdf(_build_form(req, "borrow", value_source), f"ใบยืมอุปกรณ์ {req.request_code}")


def generate_preview_pdf(req: object, value_source: str = "acquisition") -> bytes:
    """สร้าง PDF ร่างใบยืม (ก่อนกดส่งคำขอ / ยังไม่อนุมัติ) — ฟอร์มเดียวกัน ต่างแค่ประทับว่าเป็นร่าง"""
    return _build_form(req, "draft", value_source)


def generate_return_pdf(req: object, value_source: str = "acquisition") -> bytes:
    """สร้าง PDF ใบคืนอุปกรณ์ — เลย์เอาต์ล้อใบยืม ใช้เลขคำขอเดียวกัน ต่างที่สภาพเมื่อคืน"""
    return seal_pdf(_build_form(req, "return", value_source), f"ใบคืนอุปกรณ์ {req.request_code}")


_THAI_MONTHS = ["มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
                "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"]
# แบบย่อสำหรับช่องแคบในตาราง (คอลัมน์กำหนดคืน 22mm) — "1 ก.ย. 69" พอดี ส่วน 01/09/2569 ล้น
_THAI_MONTHS_ABBR = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
                     "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]

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

# ป้ายประเภท/หน่วยเริ่มต้นในใบยืม (item_type = durable / material / consumable)
_ITEM_TYPE_TH = {"durable": "ครุภัณฑ์", "material": "วัสดุใช้ซ้ำ", "consumable": "วัสดุสิ้นเปลือง"}
_DEFAULT_UNIT = {"durable": "ชิ้น", "material": "ชิ้น", "consumable": "หน่วย"}


def _fmt_money(v) -> str:
    """มูลค่าต่อชิ้นในใบยืม — ไม่มีราคา = '-' (อุปกรณ์หลายชิ้นยังไม่กรอกมูลค่า)"""
    return f"{float(v):,.2f}" if v is not None else "-"


def _item_value(item: object, value_source: str):
    """มูลค่าที่เอกสารจะแสดงสำหรับ 1 รายการ ตาม setting pdf_value_source

    ทั้งสองค่าเป็น snapshot ณ วันอนุมัติ (unit_value_snapshot / book_value_snapshot) ไม่คำนวณสด
    ใบยืมใบเดิมจึงพิมพ์ซ้ำได้ตัวเลขเดิมเสมอ แม้ค่าเสื่อมจะเดินไปแล้วหรือแอดมินแก้ราคาในคลังภายหลัง
    """
    if value_source == "book":
        return getattr(item, "book_value", None)
    return getattr(item, "equipment_value", None)


def _thai_date_parts(dt) -> tuple[str, str, str]:
    """(วัน, เดือนไทย, พ.ศ.) — ฟอร์มราชการเขียนวันที่แยกช่อง ไม่ใช่ 01/07/2569"""
    dt = _local(dt) if dt else None
    if dt is None:
        return "____", "____________", "______"
    return str(dt.day), _THAI_MONTHS[dt.month - 1], str(dt.year + 543)


def _position_th(req: object) -> str:
    """ตำแหน่งผู้ยืมบนฟอร์ม — ตัดสินจาก "มีรหัสนักศึกษาไหม" ไม่ใช่ "มีรหัสประจำตัวไหม"
    เพราะตอนนี้อาจารย์ก็มีรหัสประจำตัวของตัวเอง (username) แล้ว
    """
    is_student = getattr(req, "borrower_is_student", None)
    if is_student is None:  # object ที่ไม่มีฟิลด์นี้ (เช่นที่ประกอบเอง) — ถอยไปใช้เกณฑ์เดิม
        is_student = bool(getattr(req, "student_number", None))
    return "นักศึกษา" if is_student else "อาจารย์/เจ้าหน้าที่"


def _build_form(req: object, kind: str, value_source: str = "acquisition") -> bytes:
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
        elems.append(Paragraph(f"เลขที่คำขอ {_e(code)}", small_gray))
    elems.append(Spacer(1, 10))

    req_dt = _local(doc_dt)
    time_str = req_dt.strftime("%H:%M") if getattr(req_dt, "hour", None) is not None else "____"
    elems.append(Paragraph(f"วันที่ {d} เดือน {m} พ.ศ. {y} &nbsp;&nbsp; เวลา {time_str} น.", right))
    elems.append(Spacer(1, 4))
    name = _e(getattr(req, "student_name", None)) or "____________________"
    # อาจารย์/เจ้าหน้าที่ต้องมีรหัสประจำตัวขึ้นบนใบยืมเหมือนกัน ไม่ใช่เว้นว่างเพราะไม่มีรหัสนักศึกษา
    number = _e(getattr(req, "borrower_identifier", None) or getattr(req, "student_number", None))
    position = _position_th(req)
    # บอกชนิดรหัสกำกับ (feedback อาจารย์) — ดูแล้วรู้ทันทีว่าเลขนี้เป็นของนักศึกษาหรือบุคลากร
    id_kind = "รหัสนักศึกษา" if position == "นักศึกษา" else "รหัสบุคลากร"
    who = f"{name} ({id_kind} {number})" if number else name
    elems.append(Paragraph(
        f"ข้าพเจ้า <u>{who}</u> &nbsp;&nbsp;&nbsp; ตำแหน่ง <u>{position}</u>", body))
    major = _MAJOR_LABEL.get(getattr(req, "student_major", None))
    major_part = f"สาขา <u>{major}</u> &nbsp;&nbsp;&nbsp; " if major else ""
    elems.append(Paragraph(f"{major_part}ฝ่ายงาน <u>คณะเทคโนโลยีดิจิทัล</u>", body))
    contact = _e(getattr(req, "student_email", None))
    if contact:
        elems.append(Paragraph(f"ช่องทางติดต่อ <u>{contact}</u>", body))
    purpose = _e(getattr(req, "purpose", None))

    # รายการที่พิมพ์ลงเอกสาร — ใบยืมพิมพ์เฉพาะชิ้นที่ได้รับอนุมัติ (ชิ้นที่แอดมินไม่อนุมัติไม่เคยออกจากคลัง
    # ถ้าพิมพ์ลงใบที่ผู้ยืมเซ็นรับผิดชอบ = ให้เซ็นรับของที่ไม่เคยได้รับ) ใบคืนสะสมเฉพาะชิ้นที่คืนแล้ว
    items = list(getattr(req, "items", []))
    if is_return:
        items = sorted(
            [it for it in items if getattr(it, "returned", False)],
            key=lambda it: getattr(it, "returned_at", None) or datetime.min.replace(tzinfo=timezone.utc),
        )
    else:
        items = [it for it in items if getattr(it, "item_status", "approved") != "rejected"]
    dues = [_item_due(it, req, draft) for it in items]
    uniq_dues = sorted({d for d in dues if d})

    if is_return:
        elems.append(Paragraph(
            f"ขอส่งคืนวัสดุ อุปกรณ์ ตามใบยืมเลขที่ <u>{_e(code) or '-'}</u> ดังรายการต่อไปนี้", body))
        # วันคืนต่างกันรายชิ้นแล้ว การพิมพ์วันเดียวลอย ๆ ตรงหัวจะขัดกับตารางข้างล่างทันที
        due_head = (f"กำหนดคืน <u>{_fmt_date_th(uniq_dues[0])}</u>" if len(uniq_dues) == 1
                    else "กำหนดคืน <u>ตามรายการด้านล่าง</u>" if uniq_dues else "")
        elems.append(Paragraph(
            f"วันที่ยืม <u>{_fmt_datetime(getattr(req, 'requested_at', None))}</u>"
            + (f" &nbsp;&nbsp; {due_head}" if due_head else ""), body))
    else:
        elems.append(Paragraph(
            "มีความประสงค์จะขอยืมวัสดุ อุปกรณ์ ดังรายการต่อไปนี้"
            + (f" (เพื่อ {purpose})" if purpose else ""), body))
        # นัดรับของ (เฟส 4) — ใบยืมเป็นเอกสารที่ผู้ยืมถือไปจริง ต้องบอกว่าไปรับที่ไหนเมื่อไหร่
        pickup_at = getattr(req, "pickup_at", None)
        where = _e(getattr(req, "pickup_location", None))
        if pickup_at or where:
            # มีสถานที่แต่ไม่นัดเวลา (จ่ายหน้าเคาน์เตอร์) ก็ต้องพิมพ์สถานที่ ไม่ทิ้งทั้งบรรทัด
            when = f"นัดรับของ <u>{_fmt_datetime_th(pickup_at)} น.</u> &nbsp;&nbsp; " if pickup_at else ""
            elems.append(Paragraph(when + (f"สถานที่รับของ <u>{where}</u>" if where else ""), body))
            note = _e(getattr(req, "pickup_note", None))
            if note:
                elems.append(Paragraph(f"หมายเหตุการรับของ: {note}", body))
        if len(uniq_dues) > 1:
            elems.append(Paragraph(
                f"กำหนดคืนตามรายการด้านล่าง (เร็วสุด <u>{_fmt_date_th(uniq_dues[0])}</u>"
                f" &nbsp;·&nbsp; ช้าสุด <u>{_fmt_date_th(uniq_dues[-1])}</u>)", body))
        else:
            one_due = uniq_dues[0] if uniq_dues else getattr(req, "due_date", None)
            elems.append(Paragraph(
                f"กำหนดคืน (โดยประมาณ) <u>{_fmt_date_th(one_due)}</u>", body))
    elems.append(Spacer(1, 10))

    # ── ตารางรายการ ──
    # ใบยืม: ที่ | รหัส | ชื่ออุปกรณ์ | ประเภท | จำนวน | กำหนดคืน | มูลค่า/ชิ้น
    # ใบคืน: ที่ | รหัส | ชื่ออุปกรณ์ | ประเภท | จำนวน | สภาพเมื่อคืน | กำหนด/วันเวลาที่คืน
    def _h(t: str) -> Paragraph:
        return Paragraph(t, _style(f"h{t}", fontName="Thai-Bold", fontSize=10, alignment=1))

    if is_return:
        # หัวคอลัมน์ยาวกว่าความกว้างช่องต้องใส่ <br/> เอง (ReportLab ตัดคำไทยให้ไม่ได้)
        header = [_h("ที่"), _h("รหัส"), _h("ชื่ออุปกรณ์"), _h("ประเภท"), _h("จำนวน"),
                  _h("สภาพ<br/>เมื่อคืน"), _h("วันเวลาที่คืน")]
    else:
        # setting pdf_value_source เลือกว่าเอกสารพูดถึงมูลค่าแบบไหน — หัวคอลัมน์ต้องเปลี่ยนตามด้วย
        # ไม่งั้นคนอ่านใบยืมแยกไม่ออกว่าเลขที่เห็นคือราคาที่ซื้อมาหรือมูลค่าหลังหักค่าเสื่อม
        _use_book = value_source == "book"
        # คอลัมน์กว้าง 26mm และ ReportLab ตัดคำไทยที่ไม่มีช่องว่างเองไม่ได้ (ข้อความยาวจะถูกตัดหาย
        # ไม่ใช่ขึ้นบรรทัดใหม่) — ต้องใส่ <br/> เองเมื่อหัวคอลัมน์ยาวกว่า "มูลค่า/ชิ้น" เดิม
        _value_head = "มูลค่า<br/>ตามบัญชี" if _use_book else "มูลค่า/ชิ้น"
        header = [_h("ที่"), _h("รหัส"), _h("ชื่ออุปกรณ์"), _h("ประเภท"), _h("จำนวน"),
                  _h("กำหนดคืน"), _h(_value_head)]
    ncol = len(header)
    rows = [header]
    for i, (item, item_due) in enumerate(zip(items, dues), 1):
        itype = getattr(item, "item_type_snapshot", None)
        unit = _e(getattr(item, "equipment_unit", None)) or _DEFAULT_UNIT.get(itype, "ชิ้น")
        qty = getattr(item, "quantity", 1)
        # ร่าง/พรีวิว (ยังไม่อนุมัติ): ห้ามโชว์รหัสหน่วยเจาะจง เพราะระบบเลือก "หน่วยว่างที่ได้มาเก่าสุด" ใหม่ทุกครั้ง
        # ที่เรียก ยังไม่ sync กันระหว่างตะกร้า/คำขอ/อนุมัติ รหัสที่เห็นตอนร่างอาจไม่ตรงของจริงตอนอนุมัติ
        # เขียนบอกตรง ๆ ว่า "รออนุมัติ" แทน "-" เฉย ๆ กันผู้ยืมสับสนว่าทำไมไม่มีรหัส
        code_display = "รออนุมัติ" if draft else (_e(getattr(item, "equipment_code", None)) or "-")
        # เลขครุภัณฑ์ (ทะเบียนราชการ) บรรทัดล่างของรหัสระบบ — เอกสารราชการอ้างเลขนี้ แยกจากรหัสตั้งแต่ migration 0048
        asset_no = None if draft else _e(getattr(item, "equipment_asset_number", None))
        if asset_no:
            code_display += f"<br/><font size=7 color='#555555'>ครุภัณฑ์ {asset_no}</font>"
        # SN (ถ้ามี) ต่อท้ายชื่อในวงเล็บ — ร่างยังไม่รู้ว่าจะได้หน่วยไหนจริง จึงโชว์ "รออนุมัติ" เหมือนคอลัมน์รหัส
        name_display = _e(getattr(item, "equipment_name", None)) or "-"
        sn = _e(getattr(item, "equipment_serial_number", None))
        if sn:
            name_display += f"(SN:{'รออนุมัติ' if draft else sn})"
        # ชื่อตามบัญชีทะเบียน (0059) — พิมพ์เมื่อต่างจากชื่อในระบบ เอกสารจะอ้างกลับไปที่ทะเบียนราชการได้
        asset_name = None if draft else _e(getattr(item, "equipment_asset_name", None))
        if asset_name and asset_name != _e(getattr(item, "equipment_name", None)):
            name_display += f"<br/><font size=7 color='#555555'>ชื่อตามทะเบียน: {asset_name}</font>"
        # สเปกที่ติดตั้งอยู่ ณ วันยืม (เฟส 8, ข้อ 17) — กันเคส "ยืมไปมี RAM 16GB คืนมาเหลือ 8GB"
        # เอกสารที่ผู้ยืมเซ็นต้องระบุว่าตอนรับของเครื่องมีอะไรอยู่บ้าง ไม่ใช่แค่ชื่อเครื่อง
        specs = _e(getattr(item, "equipment_specs", None))
        if specs:
            name_display += f"<br/><font size=7 color='#555555'>สเปก: {specs}</font>"
        # wordWrap="CJK" = ตัดขึ้นบรรทัดใหม่ได้ทุกตัวอักษร จำเป็นสำหรับไทยและรหัสยาว ๆ:
        # ReportLab แบบปกติตัดที่ช่องว่างเท่านั้น ข้อความไทยยาว ๆ หรือรหัส "สนว.-65-201-038-001-0002"
        # ที่ไม่มีช่องว่างเลยจะถูก "ตัดหาย" ไม่ใช่ขึ้นบรรทัดใหม่ (ของจริงในคลังยาวถึง 98 ตัวอักษร)
        cells = [
            Paragraph(str(i), _style(f"i{i}", fontSize=10, alignment=1)),
            Paragraph(code_display, _style(f"c{i}", fontSize=9, alignment=1, wordWrap="CJK")),
            Paragraph(name_display, _style(f"n{i}", fontSize=10, wordWrap="CJK")),
            Paragraph(_ITEM_TYPE_TH.get(itype, "-"), _style(f"t{i}", fontSize=9, alignment=1)),
            Paragraph(f"{qty} {unit}", _style(f"q{i}", fontSize=10, alignment=1)),
        ]
        if is_return:
            cells.append(Paragraph(_condition_th(getattr(item, "condition_on_return", None)),
                                   _style(f"v{i}", fontSize=9, alignment=1)))
            # ไม่เพิ่มคอลัมน์ (ใบคืนมี 7 คอลัมน์อยู่แล้ว ชื่ออุปกรณ์จะเหลือ ~28mm จนอ่านไม่ออก)
            # แต่รวมกำหนด/คืนจริง/จำนวนวันที่ช้าไว้ในช่องเดียว — เป็นหลักฐานประกอบค่าปรับด้วย
            cells.append(Paragraph(_return_cell(item, item_due),
                                   _style(f"rt{i}", fontSize=7.5, leading=10, alignment=1,
                                          wordWrap="CJK")))
        else:
            cells.append(Paragraph(_fmt_date_short(item_due),
                                   _style(f"d{i}", fontSize=8, alignment=1)))
            cells.append(Paragraph(_fmt_money(_item_value(item, value_source)),
                                   _style(f"v{i}", fontSize=9, alignment=2)))
        rows.append(cells)
    # ไม่เติมแถวว่าง (8 ก.ย. 69) — ยืม 3 ชิ้นแล้วได้ตารางเปล่าอีก 9 บรรทัดคือเอกสารที่ดูไม่จบ
    # และเปิดช่องให้เขียนของเพิ่มเองหลังเซ็นด้วย · blank ยังใช้ในแถว "รวมมูลค่า" ด้านล่าง
    blank = Paragraph("&nbsp;", _style("blank", fontSize=11, leading=17))

    # แถวรวมมูลค่า (เฉพาะใบยืม) — ผู้ยืมต้องเห็นวงเงินรวมที่ต้องรับผิดชอบ
    total = sum((_item_value(i, value_source) or 0) * getattr(i, "quantity", 1) for i in items)
    if not is_return and total:
        rows.append([
            blank, blank, blank, blank, blank,
            Paragraph("รวมมูลค่า", _style("tl", fontName="Thai-Bold", fontSize=10, alignment=2)),
            Paragraph(_fmt_money(total), _style("tv", fontName="Thai-Bold", fontSize=9, alignment=2)),
        ])

    # "วัสดุสิ้นเปลือง" ยาวสุดในคอลัมน์ประเภท ต้อง 26mm ไม่งั้นตัดบรรทัด
    if is_return:
        col = [8 * mm, 25 * mm, W - 8 * mm - 25 * mm - 23 * mm - 21 * mm - 22 * mm - 28 * mm,
               23 * mm, 21 * mm, 22 * mm, 28 * mm]
    else:
        # 7 คอลัมน์: ที่ 8 · รหัส 28 · ชื่อ (ที่เหลือ ≈46) · ประเภท 22 · จำนวน 20 · กำหนดคืน 22 · มูลค่า 24
        col = [8 * mm, 28 * mm, W - 8 * mm - 28 * mm - 23 * mm - 21 * mm - 22 * mm - 24 * mm,
               23 * mm, 21 * mm, 22 * mm, 24 * mm]
    # rowHeights=None (auto) — ชื่ออุปกรณ์ยาว ๆ ต้องขยายแถวเอง ไม่งั้นข้อความล้นทับเส้นตาราง
    table = Table(rows, colWidths=col, repeatRows=1)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.7, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (2, 1), (2, -1), 6),
    ]))
    elems.append(table)
    elems.append(Spacer(1, 12))
    # อัตราค่าปรับคืนเกินกำหนดที่ล็อกตอนอนุมัติ (23 พ.ย. 69) — ผู้ยืมต้องรู้ก่อนรับของ เป็นหลักฐานคู่กับใบยืม
    # ไม่เพิ่มคอลัมน์เพราะตารางแคบอยู่แล้ว · ร่าง (ยังไม่อนุมัติ) ยังไม่มีอัตราจึงไม่พิมพ์
    if not is_return:
        rates: dict[float, list[str]] = {}
        for n, it in enumerate(items, 1):
            if getattr(it, "fine_rate_snapshot", None) is not None:
                rates.setdefault(float(it.fine_rate_snapshot), []).append(str(n))
        if rates:
            txt = " · ".join(f"รายการที่ {', '.join(ns)} = {_fmt_money(r)} บาท/วัน" for r, ns in sorted(rates.items()))
            elems.append(Paragraph(f"<b>อัตราค่าปรับคืนเกินกำหนด</b> {txt}", _style("FRATE", fontSize=10.5, leading=15)))
            elems.append(Spacer(1, 8))

    elems.append(Paragraph(
        f"&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;{_RETURN_NOTE if is_return else _PLEDGE}",
        _style("P", fontSize=11, leading=18)))
    elems.append(Spacer(1, 18))

    # ── ลายเซ็น: ใบยืม = ผู้ยืม/ผู้อนุมัติ, ใบคืน = ผู้คืน/ผู้รับคืน (แยกใบกันตามข้อ 1.10) ──
    blank = "(............................................)"
    borrower = f"({name})" if getattr(req, "student_name", None) else blank
    approver = _e(getattr(req, "approver_name", None))
    receiver = _e(getattr(req, "receiver_name", None))
    signer = receiver if is_return else approver
    right_name = f"({signer})" if signer else blank
    line = "............................................"
    # ทุกบรรทัดในบล็อกลายเซ็นจัดกึ่งกลางคอลัมน์เหมือนกันหมด (รูป → ป้าย+เส้น → ชื่อ → วันที่)
    # เดิมป้ายกับวันที่ชิดซ้าย ชื่อกึ่งกลาง รูปชิดซ้าย = สามแนวคนละที่ ดูเหมือนวางผิดตำแหน่ง
    sig = _style("S", fontSize=11, leading=22, alignment=1)
    sig_c = _style("SC", fontSize=10, leading=16, alignment=1)
    date_line = "วันที่ .......... เดือน .................... พ.ศ. .........."
    left_label, right_label = ("ผู้คืน", "ผู้รับคืน") if is_return else ("ผู้ยืม", "ผู้อนุมัติ")

    # ลายเซ็นบนหน้าจอ (เฟส 11) — มีไฟล์ = วางรูปแทนเส้นประของฝั่งนั้น พร้อมบอกว่าเซ็นในระบบเมื่อไหร่
    left_field, right_field = (
        ("return_sig_borrower", "return_sig_staff") if is_return
        else ("handover_sig_borrower", "handover_sig_staff")
    )
    left_kind, right_kind = (
        ("return_borrower", "return_staff") if is_return else ("handover_borrower", "handover_staff")
    )
    # รูป (คำขอเก่า) ก่อน ไม่มีรูปแต่ลงนามด้วยรหัสผ่านแล้ว (E-sign) = ข้อความระบุผู้ลงนาม+เลขอ้างอิงแทนรูป
    left_img = _signature_image(req, left_field) or _esign_block(req, left_kind)
    right_img = _signature_image(req, right_field) or _esign_block(req, right_kind)
    # วันที่บนเอกสาร = **วันที่รับลายเซ็นนั้นจริง ๆ** ของแต่ละฝั่ง (จาก signature_meta) ไม่ใช่เวลาจ่ายของรวม
    # เพราะผู้ยืมกับเจ้าหน้าที่อาจเซ็นคนละจังหวะ — ฝั่งที่ยังไม่เซ็นคงเส้นว่างไว้ให้ลงวันที่ด้วยมือเหมือนเดิม
    left_date = _signed_date_line(req, left_kind) or date_line
    right_date = _signed_date_line(req, right_kind) or date_line
    e_note = _style("SE", fontSize=8, alignment=1, textColor=colors.gray)

    # เรียงเป็นแกนเดียวกันทั้งบล็อก: ลายเซ็น → เส้น → ชื่อ → ตำแหน่ง → วันที่ (ทุกบรรทัดกึ่งกลาง)
    # ป้าย "ผู้ยืม/ผู้อนุมัติ" ต้องอยู่คนละบรรทัดกับเส้น ไม่งั้นความกว้างของป้ายจะดันจุดกึ่งกลางของเส้นให้
    # เยื้องไปจากลายเซ็นและชื่อที่อยู่กึ่งกลางคอลัมน์
    sig_rows = []
    if left_img or right_img:
        sig_rows.append([left_img or Spacer(1, SIGNATURE_IMG_H), right_img or Spacer(1, SIGNATURE_IMG_H)])
    sig_rows.append([Paragraph(line, sig), Paragraph(line, sig)])
    sig_rows.append([Paragraph(borrower, sig_c), Paragraph(right_name, sig_c)])
    sig_rows.append([Paragraph(left_label, sig_c), Paragraph(right_label, sig_c)])
    sig_rows.append([Paragraph(left_date, sig), Paragraph(right_date, sig)])
    sig_table = Table(sig_rows, colWidths=[W / 2, W / 2])
    sig_style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]
    if left_img or right_img:
        # รูปใน cell ชิดซ้ายเสมอ (hAlign ของ flowable ไม่มีผลใน Table) ต้องสั่ง ALIGN ที่แถวนี้เอง
        # ไม่งั้นลายเซ็นไปกองซ้าย ไม่ตรงกับเส้น/ชื่อ/วันที่ที่จัดกึ่งกลาง
        sig_style.append(("ALIGN", (0, 0), (-1, 0), "CENTER"))
    sig_table.setStyle(TableStyle(sig_style))
    elems.append(sig_table)
    # ป้ายกำกับท้ายเอกสาร — ให้คนที่ถือกระดาษรู้ว่าฉบับนี้ลงลายมือชื่อในระบบแล้ว ไม่ต้องตามหาใบเซ็นอีกใบ
    if left_img or right_img:
        elems.append(Spacer(1, 6))
        elems.append(Paragraph(
            "เอกสารฉบับนี้ลงลายมือชื่ออิเล็กทรอนิกส์ในระบบแล้ว "
            "ตรวจสอบต้นฉบับได้จากเลขที่คำขอในระบบยืม-คืนอุปกรณ์"
            + (f"<br/>เลขอ้างอิงการลงนาม: {refs}" if (refs := _esign_refs(req, (left_kind, right_kind))) else ""),
            _style("EN", fontSize=8, leading=12, alignment=1, textColor=colors.gray)))

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
        Paragraph(f"<b>ส่วนงาน</b> {_e(unit)} {dots}", body),
        Paragraph(f"<b>ที่</b> ....................................... <b>วันที่</b> {d} {m} {y}", body),
        Paragraph("<b>เรื่อง</b> ขออนุมัติซ่อมแซมครุภัณฑ์", body),
        Spacer(1, 6),
        Paragraph("<b>เรียน</b> ผู้มีอำนาจอนุมัติวงเงิน", body),
        Spacer(1, 4),
        Paragraph(f"&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;ด้วยหน่วยงาน {_e(unit)} "
                  "มีความประสงค์จะขออนุมัติซ่อมแซมครุภัณฑ์ รายละเอียดดังนี้", body),
        Spacer(1, 8),
    ]

    data = [[_h("ลำดับที่"), _h("รายการ"), _h("รหัสครุภัณฑ์"), _h("ลักษณะ/สภาพที่ชำรุด"), _h("หมายเหตุ")]]
    for i, r in enumerate(rows, 1):
        data.append([
            Paragraph(str(i), _style(f"ri{i}", fontSize=9.5, alignment=1)),
            Paragraph(_e(r.get("name")) or "-", _style(f"rn{i}", fontSize=9.5)),
            Paragraph(_e(r.get("code")) or "-", _style(f"rc{i}", fontSize=8.5, alignment=1)),
            Paragraph(_e(r.get("damage")) or "-", _style(f"rd{i}", fontSize=9.5)),
            Paragraph(_e(r.get("note")) or "", _style(f"rm{i}", fontSize=9)),
        ])
    # ไม่เติมแถวว่าง (8 ก.ย. 69) — เอกสารขออนุมัติที่มีบรรทัดว่างต่อท้ายคือช่องให้เติมรายการหลังเซ็น

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
                  f"&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;( {_e(requester)} )<br/>"
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
        Paragraph(f"ชื่อ-สกุล <u>{_e(generated_by)}</u> &nbsp;&nbsp; ตำแหน่ง ......................... "
                  "&nbsp;&nbsp; หน่วยงาน <u>คณะเทคโนโลยีดิจิทัล</u>", body),
        Paragraph(f"รายการที่นำเข้าคลังระหว่างวันที่ {date_from} ถึง {date_to} "
                  f"รวม {len(rows)} รายการ", small),
        Spacer(1, 8),
    ]

    def _h(t: str) -> Paragraph:
        return Paragraph(t, _style(f"kh{t}", fontName="Thai-Bold", fontSize=9.5, alignment=1))

    # คอลัมน์ตามใบจริง — ราคาดึงจาก audit log ของตอนรับเข้า/ปลดระวาง (log เก่าที่ไม่มีราคาเว้นว่างให้กรอกมือ)
    data = [[_h("ลำดับ"), _h("รายการ"), _h("จำนวน"), _h("ราคาต่อหน่วย"), _h("จำนวนเงิน"), _h("รหัสครุภัณฑ์")]]
    for i, r in enumerate(rows, 1):
        unit_th = {"durable": "เครื่อง/ชิ้น", "material": "ชิ้น", "consumable": "หน่วย"}.get(
            r.get("item_type") or "", "")
        qty = r.get("quantity")
        price = r.get("unit_value")
        amount = price * qty if price is not None and qty is not None else None
        data.append([
            Paragraph(str(i), _style(f"ka{i}", fontSize=9, alignment=1)),
            Paragraph(_e(r.get("name") or "-"), _style(f"kb{i}", fontSize=9)),
            Paragraph(f"{qty} {unit_th}" if qty is not None else "-",
                      _style(f"kc{i}", fontSize=9, alignment=1)),
            Paragraph(_fmt_money(price), _style(f"kp{i}", fontSize=9, alignment=2)) if price is not None else "",
            Paragraph(_fmt_money(amount), _style(f"km{i}", fontSize=9, alignment=2)) if amount is not None else "",
            Paragraph(_e(r.get("code") or "-"), _style(f"kd{i}", fontSize=8.5, alignment=1)),
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
                  f"&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;( {_e(generated_by)} )<br/>"
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
        type_th = _ITEM_TYPE_TH.get(
            r.get("item_type") or "", "-")
        last_val = (r.get("reason") or "-") if is_disposal else _fmt_date(r.get("date"))
        table_rows.append([
            Paragraph(str(i), _style(f"a{i}", fontSize=9, alignment=1)),
            Paragraph(_e(r.get("code") or "-"), _style(f"b{i}", fontSize=9)),
            Paragraph(_e(r.get("name") or "-"), _style(f"c{i}", fontSize=9)),
            Paragraph(type_th, _style(f"d{i}", fontSize=9, alignment=1)),
            Paragraph(str(r.get("quantity") if r.get("quantity") is not None else "-"),
                      _style(f"e{i}", fontSize=9, alignment=1)),
            Paragraph(_e(r.get("actor") or "-"), _style(f"f{i}", fontSize=9)),
            Paragraph(_e(last_val), _style(f"g{i}", fontSize=9)),
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


SIGNATURE_IMG_W, SIGNATURE_IMG_H = 110, 34


def _signature_image(req: object, field: str):
    """รูปลายเซ็นบนหน้าจอของฝั่งนั้น (ถ้ามี) — ไม่มีไฟล์ = คืน None แล้วใช้เส้นประให้เซ็นมือเหมือนเดิม

    ไฟล์อยู่ใน PRIVATE_UPLOAD_DIR ซึ่งไม่ได้เสิร์ฟสาธารณะ — อ่านตรงจากดิสก์ตอนสร้าง PDF เท่านั้น
    ใบเก่าที่ยังไม่มีลายเซ็นต้องพิมพ์ออกมาเหมือนเดิมทุกจุด จึงต้องไม่พังเมื่อไฟล์หาย
    """
    filename = getattr(req, field, None)
    if not filename:
        return None
    path = os.path.join(settings.PRIVATE_UPLOAD_DIR, os.path.basename(filename))
    if not os.path.isfile(path):
        return None
    try:
        # ต้องบังคับให้ PIL อ่านไฟล์จริงตรงนี้ — ReportLab เปิดรูปตอน build เอกสาร ถ้าไฟล์เสียจะระเบิด
        # กลางทางแล้วใบยืมทั้งใบออกไม่ได้ (ทั้งที่ลายเซ็นเป็นแค่ส่วนประกอบ) จับให้จบตั้งแต่ตรงนี้
        from PIL import Image as PILImage
        with PILImage.open(path) as im:
            im.load()
            ratio = im.height / im.width if im.width else 1
        # คงสัดส่วนเดิมของลายเซ็น (canvas กว้างกว่าสูง) ไม่งั้นบีบจนลายเซ็นเพี้ยนรูป
        img = Image(path, width=SIGNATURE_IMG_W, height=min(SIGNATURE_IMG_W * ratio, SIGNATURE_IMG_H))
        img.hAlign = "CENTER"   # ต้องสั่งเอง — ปกติรูปใน cell ชิดซ้าย ไม่ตรงกับเส้นและชื่อที่อยู่กึ่งกลาง
        return img
    except Exception:   # ไฟล์เสีย/ไม่ใช่รูป — ใบยืมต้องออกได้เสมอ ห้ามล้มทั้งเอกสารเพราะลายเซ็นเดียว
        return None


def _esign_block(req: object, kind: str):
    """ลงนามอิเล็กทรอนิกส์ด้วยรหัสผ่าน (16 พ.ย. 69) — ไม่มีรูปลายมือ พิมพ์ผู้ลงนาม + เลขอ้างอิงในกรอบขนาดเท่ารูปเดิม
    เลขอ้างอิงใช้ตามหาบันทึกการลงนาม (เวลา/เครื่อง/hash ของเนื้อหา) ในระบบได้"""
    meta = (getattr(req, "signature_meta", None) or {}).get(kind)
    if not isinstance(meta, dict) or meta.get("method") != "password":
        return None
    # ชื่อด้วยฟอนต์ลายมือตรงช่องเซ็นเท่านั้น — เลขอ้างอิงย้ายไปบรรทัดท้ายเอกสาร (_esign_refs) ผู้ใช้เห็นแล้วแปลก (23 พ.ย. 69)
    style = _style(f"ES{kind}", fontName="Thai-Script", fontSize=18, leading=SIGNATURE_IMG_H, alignment=1,
                   textColor=colors.HexColor("#1E3A8A"))
    return Paragraph(_e(meta.get("signer_name")) or "-", style)


def _esign_refs(req: object, kinds: tuple[str, ...]) -> str:
    """เลขอ้างอิงการลงนามของแต่ละฝั่ง สำหรับบรรทัดเล็กท้ายเอกสาร — ใช้ตามหาบันทึก (เวลา/เครื่อง/hash) ในระบบ"""
    metas = getattr(req, "signature_meta", None) or {}
    return " · ".join(
        f"{SIGNATURE_LABEL_TH.get(k, k)} {_e(m.get('ref'))}" for k in kinds
        if isinstance(m := metas.get(k), dict) and m.get("method") == "password" and m.get("ref"))


def _signed_date_line(req: object, kind: str) -> str | None:
    """บรรทัดวันที่ของลายเซ็นฝั่งนั้น — ใช้เวลาที่ระบบรับลายเซ็นจริง (signature_meta[kind].signed_at)

    ไม่ใช้ handover_at/returned_at รวม เพราะผู้ยืมกับเจ้าหน้าที่อาจเซ็นคนละจังหวะ วันที่บนเอกสารต้องตรงกับ
    ลายเซ็นที่อยู่เหนือมันจริง ๆ · ยังไม่เซ็น = คืน None แล้วผู้เรียกใช้เส้นว่างให้ลงวันที่ด้วยมือเหมือนเดิม
    """
    meta = (getattr(req, "signature_meta", None) or {}).get(kind)
    if not isinstance(meta, dict) or not meta.get("signed_at"):
        return None
    try:
        signed = datetime.fromisoformat(meta["signed_at"])
    except (TypeError, ValueError):
        return None
    d, m, y = _thai_date_parts(signed)
    return f"วันที่ {d} เดือน {m} พ.ศ. {y}"


def _sig_cell(label: str, name: str):
    style_label = _style("SL", fontSize=10, alignment=1)
    style_name = _style("SN", fontSize=9, textColor=colors.gray, alignment=1)
    return Table(
        [
            [Paragraph("_" * 30, _style("Line", alignment=1))],
            [Paragraph(label, style_label)],
            [Paragraph(f"({_e(name)})" if name else "", style_name)],
        ],
        colWidths=["100%"],
    )


_STOCKTAKE_TH = {
    "found": "พบ", "moved_here": "ย้ายมา", "missing": "ไม่พบ", "on_loan": "ถูกยืมอยู่", "pending": "ยังไม่ตรวจ",
    "elsewhere": "พบที่ห้องอื่น",
}
# 5 ช่องติ๊กตามแบบรายงานทะเบียนคุมทรัพย์สินของคณะ — ลำดับเดียวกับเอกสารต้นฉบับ (ใช้ร่วมกับ stocktake_xlsx)
CONDITION_COLUMNS = [("normal", "ปกติ"), ("damaged", "ชำรุด"), ("deteriorated", "เสื่อม\nสภาพ"),
                     ("lost", "สูญหาย\n(ไม่พบ)"), ("wrong_category", "รายการ\nผิดประเภท")]


def stocktake_note(i: object) -> str:
    """หมายเหตุของ 1 แถวในใบตรวจ = ที่มาจากระบบ (ย้ายห้อง/ถูกยืม/ยังไม่พบ) + ที่ผู้ตรวจพิมพ์"""
    sys_note = {
        "moved_here": f"ย้ายจาก {i.from_location or '(ไม่ระบุ)'}",
        "elsewhere": f"อยู่ที่ {i.from_location}",
        "on_loan": "ถูกยืมอยู่",
        # ไม่ติ๊กสูญหายให้เอง (ผู้ใช้เลือก 23 พ.ย. 69) — อาจไปเจอที่ห้องอื่นภายหลัง แค่บอกว่ารอบนี้ยังไม่เจอ
        "missing": "" if i.condition == "lost" else "ยังไม่พบระหว่างตรวจ",
    }.get(i.result, "")
    return " · ".join(x for x in (sys_note, i.note) if x)


def _tick() -> Drawing:
    """เครื่องหมายถูกแบบวาดเส้น — ฟอนต์ไทยไม่มี ✓ และ ZapfDingbats บางโปรแกรมไม่มีจริง (เคยขึ้นเป็น ■)"""
    d = Drawing(4 * mm, 4 * mm)
    d.add(PolyLine([0.4 * mm, 2.1 * mm, 1.5 * mm, 0.7 * mm, 3.6 * mm, 3.5 * mm], strokeWidth=1.3, strokeColor=colors.black))
    return d


@dataclass
class SheetRow:
    """1 แถวของใบตรวจ (รายห้องหรือรวมทุกห้อง) — PDF / Excel / พรีวิว ใช้ชุดเดียวกัน"""
    room: str | None
    code: str
    asset_number: str | None
    name: str
    location_detail: str | None
    unit_value: float | None
    acquired_at: object
    condition: str | None
    note: str


def round_rows(rnd: object) -> list[SheetRow]:
    # ใบตรวจตามแบบทะเบียนคุมทรัพย์สิน = ชื่อตามบัญชี (0059) · หน้าจอเดินตรวจยังโชว์ชื่อในระบบ
    return [SheetRow(rnd.location, i.equipment_code, i.asset_number, i.asset_name or i.equipment_name, i.location_detail,
                     i.unit_value, i.acquired_at, i.condition, stocktake_note(i)) for i in rnd.items]


def _condition_summary(rows: list[SheetRow]) -> str:
    marked = {k: sum(1 for r in rows if r.condition == k) for k, _ in CONDITION_COLUMNS}
    unmarked = sum(1 for r in rows if not r.condition)
    return " · ".join([f"{label.replace(chr(10), '')} {marked[k]}" for k, label in CONDITION_COLUMNS if marked[k]]
                      + ([f"ยังไม่ได้ติ๊ก {unmarked}"] if unmarked else []))


def _inspection_pdf(title: str, info: list[str], rows: list[SheetRow], show_room: bool, signer: str | None) -> bytes:
    """ใบตรวจครุภัณฑ์ตามแบบรายงานทะเบียนคุมทรัพย์สินของคณะ — A4 แนวนอน · ติ๊กสภาพ 5 ช่อง (ยังไม่ติ๊ก = ว่าง)
    · ไม่เติมแถวว่างตามกฎเอกสาร · show_room = ใบรวมทุกห้อง (เพิ่มคอลัมน์ห้อง)"""
    _register_fonts()
    buf = io.BytesIO()
    page = landscape(A4)
    doc = SimpleDocTemplate(
        buf, pagesize=page, leftMargin=10 * mm, rightMargin=10 * mm, topMargin=12 * mm, bottomMargin=10 * mm,
        title=_doc_title(title), author="ระบบยืม-คืนอุปกรณ์ คณะเทคโนโลยีดิจิทัล",
    )
    W = page[0] - 20 * mm
    body = _style("STB", fontSize=11, leading=16)
    cell = _style("STC", fontSize=9, leading=12)
    mid = _style("STM", fontSize=9, leading=12, alignment=1)
    head = _style("STH", fontName="Thai-Bold", fontSize=8, leading=10, alignment=1)
    elems: list = [
        Paragraph(title, _style("STT", fontName="Thai-Bold", fontSize=16, leading=22, alignment=1)),
        Paragraph("สถาบันเทคโนโลยีจิตรลดา · คณะเทคโนโลยีดิจิทัล", _style("STS", fontSize=11, leading=15, alignment=1)),
        Spacer(1, 4),
        *(Paragraph(line, body) for line in info),
        Paragraph(f"<b>สรุป</b> {_condition_summary(rows) or '-'} (ทั้งหมด {len(rows)} รายการ)", body),
        Spacer(1, 6),
    ]
    heads = ["ลำดับ", "รหัสครุภัณฑ์", "รายการครุภัณฑ์ (รุ่น/ยี่ห้อ)", *(["ห้อง"] if show_room else []), "ราคา",
             "ว/ด/ป<br/>ที่รับ", *(label for _, label in CONDITION_COLUMNS), "หมายเหตุ"]
    data = [[Paragraph(h.replace("\n", "<br/>"), head) for h in heads]]
    for n, r in enumerate(rows, 1):
        code = _e(r.asset_number or r.code) + (f"<br/><font size=7.5>{_e(r.code)}</font>" if r.asset_number else "")
        name = _e(r.name) + (f"<br/><font size=8>ตำแหน่ง: {_e(r.location_detail)}</font>" if r.location_detail else "")
        data.append([
            Paragraph(str(n), mid), Paragraph(code, cell), Paragraph(name, cell),
            *([Paragraph(_e(r.room) or "-", mid)] if show_room else []),
            Paragraph(_fmt_money(r.unit_value), _style("STR", fontSize=9, leading=12, alignment=2)),
            Paragraph(_fmt_date_short(r.acquired_at), mid),
            *(_tick() if r.condition == k else "" for k, _ in CONDITION_COLUMNS),
            Paragraph(_e(r.note), cell),
        ])
    ticks = [12 * mm, 12 * mm, 13 * mm, 19 * mm, 19 * mm]  # สูญหาย(ไม่พบ)/รายการผิดประเภท หัวยาวกว่า
    room_w = [16 * mm] if show_room else []
    fixed = 13 * mm + 40 * mm + sum(room_w) + 20 * mm + 18 * mm + sum(ticks) + 50 * mm
    first_tick = 6 if show_room else 5
    table = Table(data, colWidths=[13 * mm, 40 * mm, W - fixed, *room_w, 20 * mm, 18 * mm, *ticks, 50 * mm],
                  repeatRows=1)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.6, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (first_tick, 1), (first_tick + 4, -1), "CENTER"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F3F4F6")),
    ]))
    elems += [table, Spacer(1, 16), Paragraph(
        "ลงชื่อ ........................................ ผู้ตรวจ"
        f"<br/>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;( {_e(signer) or '........................................'} )"
        "<br/>วันที่ ........ / ........ / ........", body)]
    doc.build(elems)
    return buf.getvalue()


def generate_stocktake_pdf(rnd: object) -> bytes:
    """ใบตรวจครุภัณฑ์ประจำห้อง (23 พ.ย. 69)"""
    started, finished = _local(rnd.started_at), _local(rnd.finished_at) if rnd.finished_at else None
    date_txt = _fmt_date_th_full(started)
    if finished and finished.date() != started.date():
        date_txt += f" – {_fmt_date_th_full(finished)}"
    info = [f"<b>ห้อง</b> {_e(rnd.location)} &nbsp;&nbsp; <b>วันที่ตรวจ</b> {date_txt} &nbsp;&nbsp; "
            f"<b>ผู้ตรวจ</b> {_e(rnd.started_by_name) or '-'} &nbsp;&nbsp; "
            f"<b>สถานะ</b> {'ปิดรอบแล้ว' if finished else 'กำลังตรวจ'}"]
    if rnd.note:
        info.append(f"<b>หมายเหตุรอบตรวจ</b> {_e(rnd.note)}")
    return _inspection_pdf("ใบตรวจครุภัณฑ์ประจำห้อง (รายงานทะเบียนคุมทรัพย์สิน)", info, round_rows(rnd),
                           show_room=False, signer=rnd.started_by_name)


def generate_stocktake_summary_pdf(rows: list[SheetRow], as_of: object) -> bytes:
    """ใบตรวจครุภัณฑ์รวมทุกห้อง — แบบเดียวกับไฟล์รายงานทะเบียนคุมทรัพย์สินทั้งคณะ (สภาพ = ผลตรวจล่าสุดของแต่ละชิ้น)"""
    return _inspection_pdf("รายงานทะเบียนคุมทรัพย์สิน (รวมทุกห้อง)",
                           [f"<b>ข้อมูล ณ วันที่</b> {_fmt_date_th_full(as_of)}"], rows, show_room=True, signer=None)


def generate_room_qr_pdf(rooms: list[tuple[str, int, bytes]]) -> bytes:
    """QR ประจำห้องสำหรับติดหน้าห้อง — 2×3 ใบต่อหน้า แต่ละใบ: QR + ชื่อห้อง + จำนวนครุภัณฑ์ตามทะเบียน
    rooms: [(ชื่อห้อง, จำนวน, PNG ของ QR)]"""
    _register_fonts()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=12 * mm, rightMargin=12 * mm,
                            topMargin=12 * mm, bottomMargin=12 * mm, title="QR ประจำห้อง ตรวจครุภัณฑ์")
    W = A4[0] - 24 * mm
    name_style = _style("RQN", fontName="Thai-Bold", fontSize=14, leading=19, alignment=1)
    sub_style = _style("RQS", fontSize=9, leading=13, alignment=1)
    cards = [[Image(io.BytesIO(png), width=55 * mm, height=55 * mm),
              Paragraph(_e(loc), name_style),
              Paragraph(f"สแกนเพื่อตรวจครุภัณฑ์ห้องนี้ ({n} รายการ)", sub_style)] for loc, n, png in rooms]
    if not cards:  # ยังไม่มีอุปกรณ์ที่ระบุสถานที่ — Table ว่างทำ ReportLab ล้ม
        doc.build([Paragraph("ยังไม่มีอุปกรณ์ที่ระบุสถานที่เก็บ", name_style)])
        return buf.getvalue()
    rows = [cards[i:i + 2] for i in range(0, len(cards), 2)]
    if len(rows[-1]) == 1:
        rows[-1].append("")
    table = Table(rows, colWidths=[W / 2, W / 2], rowHeights=[88 * mm] * len(rows))
    table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.4, colors.grey), ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    doc.build([table])
    return buf.getvalue()
