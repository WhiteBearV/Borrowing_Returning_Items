"""อ่านทะเบียนวัสดุจาก "รูปถ่าย/PDF" ด้วย Tesseract OCR — โหมดทดลอง (ทางเลือกแทนไฟล์ Excel)

ponytail: เลือก Tesseract เพราะไม่ผูกกับบัญชี/เครดิตของใคร ไม่ต้องต่อเน็ต และข้อมูลทะเบียน
ไม่ต้องออกนอกเซิร์ฟเวอร์คณะ — แลกกับความแม่นที่ต่ำกว่า vision API โดยเฉพาะลายมือ/รูปเอียง
รับได้เพราะทุกแถวไหลเข้าหน้า "ร่างนำเข้า" ให้แอดมินตรวจ/แก้/ตัดออกก่อนบันทึกจริงอยู่แล้ว

ถ้าใช้จริงแล้วแม่นไม่พอ: เปลี่ยนแค่ _ocr_text() ให้ไปเรียก vision API (Gemini/Claude) แทน
ส่วนที่เหลือ (แยกบรรทัด → rows → ร่างนำเข้า) ใช้ต่อได้ทั้งหมด

คืน rows รูปแบบเดียวกับ parse_workbook() เพื่อไหลเข้า diff_rows/commit ชุดเดิม
"""
import os
import re
from typing import Any

from fastapi import HTTPException, status

SCAN_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".pdf")

# รหัสวัสดุ/เลขครุภัณฑ์ต้นบรรทัด — ตัวเลขล้วน หรือมี - / . คั่น (เช่น 220015, 67-214-003-001-0017)
_CODE = re.compile(r"^(?P<code>\d[\d\-/.]{3,})\s+(?P<rest>\S.*)$")
# จำนวนท้ายบรรทัด (มีหน่วยต่อท้ายหรือไม่ก็ได้) เช่น "... 12 ชิ้น" / "... 3"
_QTY = re.compile(r"\s(?P<qty>\d{1,4})\s*(?P<unit>ชิ้น|ตัว|อัน|ชุด|กล่อง|แผ่น|เมตร|ม้วน)?\s*$")


def _ocr_text(path: str) -> str:
    """รูป/PDF → ข้อความดิบ (PDF แปลงเป็นรูปทีละหน้าก่อน เพราะส่วนใหญ่เป็นไฟล์สแกน)"""
    try:
        import pytesseract
        from PIL import Image
    except ImportError:  # pragma: no cover - ขึ้นเฉพาะตอนยังไม่ได้ลง dependency
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED,
                            detail="ยังไม่ได้ติดตั้ง OCR บนเซิร์ฟเวอร์ (pytesseract/tesseract-ocr-tha)")

    if path.lower().endswith(".pdf"):
        from pdf2image import convert_from_path
        pages = convert_from_path(path, dpi=300)  # 300 dpi — ต่ำกว่านี้ตัวหนังสือไทยแตก
    else:
        pages = [Image.open(path)]

    try:
        return "\n".join(pytesseract.image_to_string(p, lang="tha+eng") for p in pages)
    except pytesseract.TesseractNotFoundError:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED,
                            detail="ยังไม่ได้ติดตั้ง tesseract-ocr บนเซิร์ฟเวอร์")


def parse_line(line: str) -> dict[str, Any] | None:
    """หนึ่งบรรทัด OCR → หนึ่งรายการ ({code, name, quantity}) — ไม่เจอรหัสต้นบรรทัด = ไม่ใช่รายการ"""
    m = _CODE.match(" ".join(line.split()))
    if not m:
        return None
    rest = m.group("rest")
    qty_m = _QTY.search(rest)
    qty = int(qty_m.group("qty")) if qty_m else 1
    name = rest[: qty_m.start()].strip() if qty_m else rest.strip()
    if not name:
        return None
    return {"code": m.group("code"), "name": name, "quantity": qty,
            "unit": qty_m.group("unit") if qty_m else None}


def parse_scan(path: str) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """อ่านรูป/PDF ทะเบียนวัสดุ คืน (rows, skipped) รูปแบบเดียวกับ parse_workbook()

    ถือว่าของที่สแกนมาเป็น "วัสดุใช้ซ้ำ" และสถานะพร้อมให้ยืมไว้ก่อน — แอดมินแก้ในร่างได้ทุกช่อง
    """
    from app.services.import_service import _categorize  # วนกลับ import ตอนใช้งานจริงเท่านั้น

    rows: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for i, raw in enumerate(_ocr_text(path).splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        item = parse_line(line)
        if not item:
            skipped.append({"sheet": "สแกน", "seq": str(i), "name": line, "reason": "ไม่พบรหัสต้นบรรทัด"})
            continue
        rows.append({
            "code": item["code"], "name": item["name"], "location": None,
            "status": "available", "quantity_available": item["quantity"],
            "category": _categorize(item["name"], item["code"], "material"),
            "item_type": "material", "quantity_total": item["quantity"], "unit": item["unit"],
        })

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="อ่านไฟล์แล้วไม่พบรายการที่ขึ้นต้นด้วยรหัส — ลองถ่ายให้ชัด/ตรงขึ้น หรือใช้ไฟล์ Excel",
        )
    return rows, skipped


def is_scan(filename: str) -> bool:
    return os.path.splitext(filename or "")[1].lower() in SCAN_EXTS
