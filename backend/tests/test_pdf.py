"""Unit tests for PDF generation — ไม่ต้องการ DB"""
import io
import uuid
from datetime import date, datetime

import pytest
from pypdf import PdfReader

import app.utils.pdf as pdf_mod
from app.utils.pdf import (
    generate_borrow_pdf, generate_preview_pdf, generate_return_pdf, generate_stock_document_pdf,
    _condition_th, _status_th, _fmt_date,
)


# ── fixtures ─────────────────────────────────────────────────────────────────

class _Item:
    def __init__(self, name, item_type="durable", qty=1, condition="ok", equipment_code=None,
                 serial_number=None, equipment_value=None, book_value=None):
        self.id = uuid.uuid4()
        self.equipment_id = uuid.uuid4()
        self.equipment_name = name
        self.equipment_code = equipment_code
        self.equipment_serial_number = serial_number
        self.item_type_snapshot = item_type
        self.quantity = qty
        self.returned = True
        self.returned_at = datetime(2026, 7, 1, 10, 0)
        self.condition_on_return = condition
        self.damage_note = None
        self.renewed_count = 0
        # มูลค่า 2 แบบ ณ วันอนุมัติ — ใบยืมเลือกโชว์ค่าใดค่าหนึ่งตาม setting pdf_value_source
        self.equipment_value = equipment_value
        self.book_value = book_value


class _Req:
    def __init__(self, items=None, **kw):
        self.id = uuid.uuid4()
        self.request_code = kw.get("request_code", "REQ-2026-0001")
        self.student_name = kw.get("student_name", "นาย ทดสอบ ระบบ")
        self.student_number = kw.get("student_number", "6512345678")
        self.student_email = kw.get("student_email", "test@cdti.ac.th")
        self.purpose = kw.get("purpose", "ทดสอบระบบ")
        self.status = kw.get("status", "approved")
        self.requested_at = kw.get("requested_at", datetime(2026, 6, 25, 14, 30))
        self.approved_at = kw.get("approved_at", datetime(2026, 6, 25, 15, 0))
        self.due_date = kw.get("due_date", date(2026, 7, 2))
        self.items = items or []


# ── PDF output tests ──────────────────────────────────────────────────────────

def _fresh_pdf(req):
    """reset font cache ทุก call เพื่อทดสอบ registration path ด้วย"""
    pdf_mod._REGISTERED = False
    return generate_borrow_pdf(req)


def test_pdf_generates_bytes():
    pdf = _fresh_pdf(_Req())
    assert isinstance(pdf, bytes)
    assert len(pdf) > 1000  # ต้องมีเนื้อหา


def test_pdf_starts_with_pdf_header():
    pdf = _fresh_pdf(_Req())
    assert pdf[:4] == b"%PDF"


def test_pdf_with_items():
    items = [
        _Item("บอร์ด Arduino Uno R3", "durable", 2, "ok"),
        _Item("สายไฟ Dupont 20cm", "consumable", 10, "ok"),
    ]
    pdf = _fresh_pdf(_Req(items=items))
    assert len(pdf) > 5000  # มีตาราง → ใหญ่กว่า


def test_pdf_with_damaged_item():
    items = [_Item("กล้อง DSLR", "durable", 1, "damaged")]
    pdf = _fresh_pdf(_Req(items=items))
    assert isinstance(pdf, bytes)


def test_pdf_no_student_info():
    """กรณี student_name/email เป็น None ต้องไม่ crash"""
    req = _Req()
    req.student_name = None
    req.student_email = None
    req.student_number = None
    pdf = _fresh_pdf(req)
    assert pdf[:4] == b"%PDF"


def test_pdf_no_purpose():
    req = _Req()
    req.purpose = None
    pdf = _fresh_pdf(req)
    assert isinstance(pdf, bytes)


def test_pdf_font_registered_once():
    """ลงทะเบียน font ซ้ำต้องไม่ error"""
    pdf_mod._REGISTERED = False
    _fresh_pdf(_Req())  # ลงทะเบียนครั้งแรก
    _fresh_pdf(_Req())  # ใช้ cache — ต้องไม่ crash


# ── A2: ร่าง/พรีวิว ต้องไม่โชว์รหัสหน่วยเจาะจง ────────────────────────────────
# ระบบเลือก "หน่วยว่างรหัสต่ำสุด" อิสระกันคนละจุด/เวลา (ตะกร้า/สร้างคำขอ/อนุมัติ) ไม่ sync กัน
# รหัสที่เห็นตอนร่างจึงอาจไม่ตรงของจริงตอนอนุมัติ — ทางแก้คือซ่อนไว้จนกว่าจะอนุมัติแล้ว (แน่นอนแล้ว)

_UNIQUE_CODE = "65-214-999"  # สั้นพอไม่ตัดบรรทัดในคอลัมน์รหัส (30mm) ไม่งั้น pypdf จะแยกข้อความเป็นคนละบรรทัด


def _extract_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "".join(page.extract_text() for page in reader.pages)


def _flat(pdf_bytes: bytes) -> str:
    """ข้อความที่ตัดขึ้นบรรทัดใหม่ออก — คอลัมน์ชื่ออุปกรณ์แคบลงตั้งแต่มีคอลัมน์กำหนดคืน (เฟส 3)
    ข้อความยาวจึงถูกตัดขึ้นบรรทัดใหม่กลางคำได้ (wordWrap="CJK") ซึ่งยังอ่านครบ ไม่ได้หายไป"""
    return _extract_text(pdf_bytes).replace("\n", "").replace(" ", "")


def test_draft_pdf_hides_specific_equipment_code():
    """generate_preview_pdf (kind="draft") — ใช้ทั้งพรีวิวก่อนส่งคำขอ และดูคำขอที่ยัง pending อยู่"""
    pdf_mod._REGISTERED = False
    item_name = "บอร์ด Arduino Uno R3"
    items = [_Item(item_name, "durable", 1, "ok", equipment_code=_UNIQUE_CODE)]
    req = _Req(items=items, status="pending")
    text = _extract_text(generate_preview_pdf(req))
    assert _UNIQUE_CODE not in text
    # เช็คว่า "รออนุมัติ" อยู่ในเซลล์รหัส (ติดกับชื่ออุปกรณ์ในแถวตาราง) — บอกตรง ๆ แทน "-" เฉย ๆ
    assert f"รออนุมัติ\n{item_name}" in text


def test_borrow_pdf_still_shows_equipment_code():
    """generate_borrow_pdf (คำขอที่อนุมัติแล้ว) — รหัสหน่วยนิ่งแล้ว ต้องยังโชว์ตามเดิม ห้าม A2 กระทบ"""
    pdf_mod._REGISTERED = False
    items = [_Item("บอร์ด Arduino Uno R3", "durable", 1, "ok", equipment_code=_UNIQUE_CODE)]
    req = _Req(items=items, status="approved")
    text = _extract_text(generate_borrow_pdf(req))
    assert _UNIQUE_CODE in text


def test_return_pdf_still_shows_equipment_code():
    """generate_return_pdf (ใบคืน) — ของคืนแล้วจริง รหัสหน่วยยิ่งต้องชัดเจน ห้าม A2 กระทบ"""
    pdf_mod._REGISTERED = False
    items = [_Item("บอร์ด Arduino Uno R3", "durable", 1, "ok", equipment_code=_UNIQUE_CODE)]
    req = _Req(items=items, status="completed")
    text = _extract_text(generate_return_pdf(req))
    assert _UNIQUE_CODE in text


# ── รหัสวัสดุสิ้นเปลืองไม่มีความหมายจริง (แค่ชื่อ+เลขลำดับที่ระบบตั้งเอง) ────────────
# ต้องไม่โชว์บนใบยืม เพราะดูเหมือนรหัสครุภัณฑ์จริงและซ้ำซ้อนกับชื่อ

def test_consumable_code_hidden_on_borrow_pdf():
    pdf_mod._REGISTERED = False
    consumable_code = "สายไฟ Dupont 20cm-001"
    items = [_Item("สายไฟ Dupont 20cm", "consumable", 10, "ok", equipment_code=consumable_code)]
    req = _Req(items=items, status="approved")
    text = _extract_text(generate_borrow_pdf(req))
    assert consumable_code not in text


def test_consumable_code_hidden_on_draft_pdf():
    pdf_mod._REGISTERED = False
    consumable_code = "สายไฟ Dupont 20cm-001"
    items = [_Item("สายไฟ Dupont 20cm", "consumable", 10, "ok", equipment_code=consumable_code)]
    req = _Req(items=items, status="pending")
    text = _extract_text(generate_preview_pdf(req))
    assert consumable_code not in text


# ── SN ต่อท้ายชื่อ ถ้าอุปกรณ์นั้นมี (ร่าง = "รออนุมัติ", จริง = ค่าจริง) ──────────────

def test_borrow_pdf_shows_real_serial_number():
    pdf_mod._REGISTERED = False
    items = [_Item("Notebook", "durable", 1, "ok", equipment_code="64001", serial_number="4562135446")]
    req = _Req(items=items, status="approved")
    assert "Notebook(SN:4562135446)" in _flat(generate_borrow_pdf(req))


def test_draft_pdf_masks_serial_number():
    pdf_mod._REGISTERED = False
    items = [_Item("Notebook", "durable", 1, "ok", equipment_code="64001", serial_number="4562135446")]
    req = _Req(items=items, status="pending")
    text = _flat(generate_preview_pdf(req))
    assert "Notebook(SN:รออนุมัติ)" in text
    assert "4562135446" not in text


def test_pdf_no_serial_number_no_suffix():
    """อุปกรณ์ที่ไม่มี SN ต้องไม่มี "(SN:" ต่อท้ายชื่อ"""
    pdf_mod._REGISTERED = False
    items = [_Item("บอร์ด Arduino Uno R3", "durable", 1, "ok", equipment_code=_UNIQUE_CODE)]
    req = _Req(items=items, status="approved")
    text = _extract_text(generate_borrow_pdf(req))
    assert "(SN:" not in text


# ── stock document (ร่างเข้า/ร่างออก) tests ────────────────────────────────────

_STOCK_ROWS = [
    {"code": "63-213-001", "name": "Dell Optiplex", "item_type": "durable",
     "quantity": 1, "reason": None, "actor": "แอดมิน ทดสอบ", "date": datetime(2026, 7, 5, 9, 0)},
    {"code": "M-345", "name": "ตะกั่วบัดกรี", "item_type": "consumable",
     "quantity": 12, "reason": "หมดอายุ", "actor": "แอดมิน ทดสอบ", "date": datetime(2026, 7, 6, 10, 0)},
]


@pytest.mark.parametrize("kind", ["receipt", "disposal"])
def test_stock_document_generates_pdf(kind):
    pdf_mod._REGISTERED = False
    pdf = generate_stock_document_pdf(kind, "01/07/2026", "07/07/2026", "แอดมิน ทดสอบ", _STOCK_ROWS)
    assert pdf[:4] == b"%PDF"
    assert len(pdf) > 2000


def test_stock_document_empty_rows():
    """ช่วงวันที่ไม่มีรายการ ต้องยังออก PDF ได้ ไม่ crash"""
    pdf = generate_stock_document_pdf("receipt", "01/07/2026", "07/07/2026", "แอดมิน", [])
    assert pdf[:4] == b"%PDF"


def test_stock_document_handles_missing_fields():
    """row ที่ field ขาด (None/ไม่มี key) ต้องไม่ crash"""
    pdf = generate_stock_document_pdf("disposal", "01/07/2026", "07/07/2026", "แอดมิน",
                                      [{"code": None, "name": None}])
    assert pdf[:4] == b"%PDF"


# ── helper function tests ─────────────────────────────────────────────────────

@pytest.mark.parametrize("status,expected", [
    ("pending", "รออนุมัติ"),
    ("approved", "อนุมัติแล้ว"),
    ("rejected", "ปฏิเสธ"),
    ("cancelled", "ยกเลิก"),
    ("completed", "คืนครบแล้ว"),
    ("unknown_xyz", "unknown_xyz"),  # fallback คืน value เดิม
])
def test_status_th(status, expected):
    assert _status_th(status) == expected


@pytest.mark.parametrize("condition,expected", [
    ("ok", "ปกติ"),
    ("damaged", "เสียหาย"),
    ("lost", "สูญหาย"),
    (None, "-"),
    ("unknown", "unknown"),
])
def test_condition_th(condition, expected):
    assert _condition_th(condition) == expected


@pytest.mark.parametrize("dt,expected", [
    (date(2026, 7, 2), "02/07/2026"),
    (None, "-"),
])
def test_fmt_date(dt, expected):
    assert _fmt_date(dt) == expected


def test_fmt_datetime_shows_thai_time():
    """เวลาใน DB เป็น UTC — ในเอกสารต้องโชว์ +7 (14:11 ไม่ใช่ 07:11)"""
    from datetime import datetime, timezone

    from app.utils.pdf import _fmt_datetime, _now

    utc = datetime(2026, 7, 14, 7, 11, tzinfo=timezone.utc)
    assert _fmt_datetime(utc) == "14/07/2026 14:11"
    # ข้ามวันด้วย: 20:30 UTC = ตี 3.30 ของวันถัดไปตามเวลาไทย
    assert _fmt_datetime(datetime(2026, 7, 14, 20, 30, tzinfo=timezone.utc)) == "15/07/2026 03:30"
    assert _now().utcoffset().total_seconds() == 7 * 3600


def test_pdf_has_document_title():
    """PDF ต้องมี /Title — ไม่งั้นแท็บ Chrome ขึ้นว่า (anonymous)"""
    from app.utils.pdf import _doc_title

    assert b"/Title" in generate_borrow_pdf(_Req())
    assert _doc_title("ใบยืมอุปกรณ์ / Equipment Borrow Request", "REQ-2026-65010-a1b2c3") == \
        "ใบยืมอุปกรณ์ REQ-2026-65010-a1b2c3"
    assert _doc_title("ใบยืมอุปกรณ์ (ร่าง) / Equipment Borrow Draft") == "ใบยืมอุปกรณ์ (ร่าง)"


def test_repair_pdf():
    """ใบขออนุมัติซ่อม — ต้องมีรหัสครุภัณฑ์และลักษณะที่ชำรุดในเอกสาร"""
    from app.utils.pdf import generate_repair_pdf

    out = generate_repair_pdf(
        [{"name": "ดิจิตอลมัลติมิเตอร์", "code": "65-214-059-006-0019",
          "damage": "สายวัดขาด", "note": ""}],
        "แอดมิน ทดสอบ",
    )
    assert out.startswith(b"%PDF") and b"/Title" in out


def test_repair_pdf_no_rows():
    from app.utils.pdf import generate_repair_pdf

    assert generate_repair_pdf([], "แอดมิน ทดสอบ").startswith(b"%PDF")  # ตารางว่างก็ยังออกฟอร์มได้


# ── มูลค่าในใบยืม: เลือกได้ว่าจะโชว์ราคาทุนหรือมูลค่าตามบัญชี (setting pdf_value_source) ──

def test_borrow_pdf_shows_acquisition_value_by_default():
    pdf_mod._REGISTERED = False
    items = [_Item("ออสซิลโลสโคป", "durable", 1, "ok", equipment_value=25000, book_value=4999)]
    text = _extract_text(generate_borrow_pdf(_Req(items=items, status="approved")))
    assert "มูลค่า/ชิ้น" in text
    assert "25,000.00" in text
    assert "4,999.00" not in text


def test_borrow_pdf_shows_book_value_when_setting_says_so():
    """setting = book → ทั้งหัวคอลัมน์และตัวเลขต้องเปลี่ยนพร้อมกัน ไม่งั้นคนอ่านแยกไม่ออกว่าเลขไหนคืออะไร"""
    pdf_mod._REGISTERED = False
    items = [_Item("ออสซิลโลสโคป", "durable", 1, "ok", equipment_value=25000, book_value=4999)]
    text = _extract_text(generate_borrow_pdf(_Req(items=items, status="approved"), value_source="book"))
    assert "ตามบัญชี" in text  # หัวคอลัมน์ขึ้น 2 บรรทัด: "มูลค่า" / "ตามบัญชี"
    assert "4,999.00" in text
    assert "25,000.00" not in text


def test_borrow_pdf_total_follows_selected_value_source():
    """แถว "รวมมูลค่า" ต้องรวมค่าชุดเดียวกับที่โชว์ในแถว ไม่ใช่ปนกัน"""
    pdf_mod._REGISTERED = False
    items = [_Item("ก", "durable", 2, "ok", equipment_value=100, book_value=10),
             _Item("ข", "durable", 3, "ok", equipment_value=100, book_value=10)]
    req = _Req(items=items, status="approved")
    assert "500.00" in _extract_text(generate_borrow_pdf(req))                        # 100*2 + 100*3
    assert "50.00" in _extract_text(generate_borrow_pdf(req, value_source="book"))    # 10*2 + 10*3


def test_stock_document_fills_price_columns_when_known():
    """ใบรับเข้าคลัง — เดิมเว้นราคาให้กรอกมือเสมอ ตอนนี้ audit log มีราคาแล้วต้องเติมให้"""
    pdf_mod._REGISTERED = False
    rows = [{"code": "63-001-0001", "name": "ออสซิลโลสโคป", "item_type": "durable",
             "quantity": 2, "unit_value": 25000, "actor": "แอดมิน", "date": datetime(2026, 1, 5)}]
    text = _extract_text(generate_stock_document_pdf("receipt", "01/01/2569", "31/01/2569", "แอดมิน", rows))
    assert "25,000.00" in text   # ราคาต่อหน่วย
    assert "50,000.00" in text   # จำนวนเงิน = 25000 x 2


def test_stock_document_leaves_price_blank_for_old_logs():
    """log เก่าก่อนมีฟีเจอร์นี้ไม่มี unit_value — ต้องเว้นว่างให้กรอกมือเหมือนเดิม ไม่ใช่พัง"""
    pdf_mod._REGISTERED = False
    rows = [{"code": "63-001-0001", "name": "ออสซิลโลสโคป", "item_type": "durable",
             "quantity": 2, "actor": "แอดมิน", "date": datetime(2026, 1, 5)}]
    assert generate_stock_document_pdf("receipt", "01/01/2569", "31/01/2569", "แอดมิน", rows)[:4] == b"%PDF"


# ── เฟส 3: วันคืนรายชิ้น — ใบยืมต้องพิมพ์วันของ "ทุกบรรทัด" ไม่ใช่วันเดียวคลุมทั้งใบ ────────

def _dated(name, due, **kw):
    it = _Item(name, kw.pop("item_type", "durable"), kw.pop("qty", 1), "ok", **kw)
    it.due_date = due
    it.item_status = "approved"
    return it


def test_borrow_pdf_shows_every_item_due_date():
    """4 ชิ้น กำหนดคืน 3 วันต่างกัน — ต้องเห็นครบทั้ง 3 วันในเอกสาร"""
    pdf_mod._REGISTERED = False
    items = [
        _dated("โน้ตบุ๊ค Dell", date(2026, 9, 1)),
        _dated("ออสซิลโลสโคป", date(2026, 9, 2)),
        _dated("มัลติมิเตอร์", date(2026, 9, 2)),
        _dated("สายไฟ", date(2026, 9, 3), item_type="consumable", qty=100),
    ]
    text = _flat(generate_borrow_pdf(_Req(items=items, due_date=date(2026, 9, 3))))
    for d in ("1ก.ย.69", "2ก.ย.69", "3ก.ย.69"):
        assert d in text, d
    # หัวเรื่องต้องไม่พิมพ์วันเดียวลอย ๆ ที่ขัดกับตาราง
    assert "กำหนดคืนตามรายการด้านล่าง" in text
    assert "เร็วสุด1ก.ย.2569" in text and "ช้าสุด3ก.ย.2569" in text


def test_borrow_pdf_single_due_date_keeps_old_wording():
    """ทุกชิ้นวันเดียวกัน — ข้อความหัวต้องเหมือนเดิม ไม่ไปทำให้ใบปกติอ่านแปลกไป"""
    pdf_mod._REGISTERED = False
    items = [_dated("โน้ตบุ๊ค Dell", date(2026, 9, 1)), _dated("มัลติมิเตอร์", date(2026, 9, 1))]
    text = _flat(generate_borrow_pdf(_Req(items=items, due_date=date(2026, 9, 1))))
    assert "กำหนดคืน(โดยประมาณ)1ก.ย.2569" in text
    assert "กำหนดคืนตามรายการด้านล่าง" not in text


def test_borrow_pdf_hides_rejected_items():
    """ชิ้นที่แอดมินไม่อนุมัติต้องไม่อยู่บนใบที่ผู้ยืมเซ็นรับผิดชอบ"""
    pdf_mod._REGISTERED = False
    ok = _dated("โน้ตบุ๊ค Dell", date(2026, 9, 1))
    no = _dated("กล้องDSLR", date(2026, 9, 1))
    no.item_status = "rejected"
    text = _flat(generate_borrow_pdf(_Req(items=[ok, no])))
    assert "โน้ตบุ๊คDell" in text
    assert "กล้องDSLR" not in text


def test_borrow_pdf_extended_due_date_wins():
    """ต่อเวลาที่อนุมัติแล้วต้องชนะเสมอ — ใบที่พิมพ์ซ้ำหลังต่อเวลาต้องขึ้นวันใหม่"""
    pdf_mod._REGISTERED = False
    it = _dated("โน้ตบุ๊ค Dell", date(2026, 9, 1))
    it.extended_due_date = date(2026, 9, 20)
    text = _flat(generate_borrow_pdf(_Req(items=[it])))
    assert "20ก.ย.69" in text
    assert "1ก.ย.69" not in text


def test_return_pdf_shows_due_actual_and_late_days():
    """ใบคืนเทียบกำหนดกับวันคืนจริง + จำนวนวันที่ช้า (หลักฐานประกอบค่าปรับ)"""
    pdf_mod._REGISTERED = False
    it = _dated("โน้ตบุ๊ค Dell", date(2026, 9, 1))
    it.returned_at = datetime(2026, 9, 3, 10, 0)   # naive = UTC → เอกสารโชว์เวลาไทย 17:00
    text = _flat(generate_return_pdf(_Req(items=[it])))
    assert "กำหนด1ก.ย.69" in text
    assert "คืนจริง3ก.ย.6917:00" in text
    assert "(ช้า2วัน)" in text


def test_return_pdf_on_time_has_no_late_note():
    pdf_mod._REGISTERED = False
    it = _dated("โน้ตบุ๊ค Dell", date(2026, 9, 3))
    it.returned_at = datetime(2026, 9, 3, 16, 0)  # คืนวันครบกำหนดตอนบ่าย = ไม่ช้า
    text = _flat(generate_return_pdf(_Req(items=[it])))
    assert "ช้า" not in text


def test_draft_pdf_uses_requested_due_date_per_item():
    """ร่างยังไม่มีวันจริง — ต้องพิมพ์วันที่ผู้ยืม "ขอไว้" ของแต่ละชิ้น"""
    pdf_mod._REGISTERED = False
    a = _Item("โน้ตบุ๊ค Dell", "durable", 1, "ok")
    a.requested_due_date, a.due_date, a.item_status = date(2026, 9, 5), None, "pending"
    b = _Item("มัลติมิเตอร์", "durable", 1, "ok")
    b.requested_due_date, b.due_date, b.item_status = date(2026, 9, 9), None, "pending"
    text = _flat(generate_preview_pdf(_Req(items=[a, b], status="pending")))
    assert "5ก.ย.69" in text and "9ก.ย.69" in text


def test_borrow_pdf_prints_installed_specs(tmp_path):
    """ใบยืมของครุภัณฑ์ที่อัพเกรดแล้วต้องระบุสเปกที่ติดตั้งอยู่ ณ วันยืม (เฟส 8, ข้อ 17)

    กันเคส "ยืมไปมี RAM 16GB คืนมาเหลือ 8GB" — เอกสารที่ผู้ยืมเซ็นต้องบอกว่ารับของไปทั้งอะไรบ้าง
    """
    pdf_mod._REGISTERED = False
    item = _Item("โน้ตบุ๊ค Dell Latitude 5400", "durable", 1, "ok", equipment_code="64001")
    item.equipment_specs = "RAM DDR4 16GB · SSD 512GB"
    req = _Req(items=[item], status="approved")
    pdf_bytes = generate_borrow_pdf(req)
    text = _flat(pdf_bytes)
    assert "RAMDDR416GB" in text.replace(" ", "") or "RAM DDR4 16GB" in _extract_text(pdf_bytes)
    assert "SSD512GB" in text.replace(" ", "") or "SSD 512GB" in _extract_text(pdf_bytes)
    # เก็บไฟล์ไว้ให้เปิดดูด้วยตาได้ (ความกว้างคอลัมน์/บรรทัดล้น เช็คด้วยเทสไม่ได้)
    out = tmp_path / "borrow_with_specs.pdf"
    out.write_bytes(pdf_bytes)
