"""Unit tests for PDF generation — ไม่ต้องการ DB"""
import uuid
from datetime import date, datetime

import pytest

import app.utils.pdf as pdf_mod
from app.utils.pdf import generate_borrow_pdf, _condition_th, _status_th, _fmt_date


# ── fixtures ─────────────────────────────────────────────────────────────────

class _Item:
    def __init__(self, name, item_type="durable", qty=1, condition="ok"):
        self.id = uuid.uuid4()
        self.equipment_id = uuid.uuid4()
        self.equipment_name = name
        self.item_type_snapshot = item_type
        self.quantity = qty
        self.returned = True
        self.condition_on_return = condition
        self.damage_note = None
        self.renewed_count = 0


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
