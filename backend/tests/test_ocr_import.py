"""แยกบรรทัดจาก OCR → รายการวัสดุ (โหมดทดลอง — ไม่ต้องมี tesseract ก็รันได้)"""
import pytest

from app.services.ocr_import import is_scan, parse_line


@pytest.mark.parametrize("line,code,name,qty,unit", [
    ("220015  Arduino Nano  12 ชิ้น", "220015", "Arduino Nano", 12, "ชิ้น"),
    ("340002 ตะกั่วบัดกรี 5", "340002", "ตะกั่วบัดกรี", 5, None),
    ("610003  Router ISR-4321", "610003", "Router ISR-4321", 1, None),  # ไม่ระบุจำนวน = 1
    ("67-214-003-001-0017  โต๊ะเรียน  2 ตัว", "67-214-003-001-0017", "โต๊ะเรียน", 2, "ตัว"),
])
def test_parse_line(line, code, name, qty, unit):
    row = parse_line(line)
    assert row == {"code": code, "name": name, "quantity": qty, "unit": unit}


@pytest.mark.parametrize("line", [
    "รายการวัสดุคงคลัง ประจำปี 2569",  # หัวตาราง — ไม่มีรหัสต้นบรรทัด
    "รหัส  รายการ  จำนวน",
    "12",          # สั้นเกินกว่าจะเป็นรหัส
    "220015",      # มีรหัสแต่ไม่มีชื่อของ
])
def test_parse_line_rejects_non_items(line):
    assert parse_line(line) is None


def test_is_scan():
    assert is_scan("ทะเบียนวัสดุ.pdf") and is_scan("IMG_1234.JPG")
    assert not is_scan("register.xlsx")
