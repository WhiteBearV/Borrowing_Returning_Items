"""อ่านไฟล์ "รายชื่อนักศึกษาในที่ปรึกษา" จากสำนักทะเบียน → รายชื่อที่มีสิทธิ์สมัคร (เฟส 9)

ไฟล์จริงที่ได้มาเป็น **.xls รุ่นเก่า** (ระบบสำนักทะเบียน export แบบนั้น) หน้าตาแบบนี้:

    (หัวกระดาษ)  คณะ ....... เทคโนโลยีดิจิทัล
                 สาขาวิชา ... วิศวกรรมคอมพิวเตอร์      รุ่น 631 หมู่เรียน วค.
                 อาจารย์ที่ปรึกษา ... สุมาลี อุณหวณิชย์ , กฤษฎา พรหมสุทธิรักษ์
    (หัวตาราง)   ที่ | รหัสนักศึกษา | ชื่อ-นามสกุล | สถานะ | หมายเหตุ
    (ข้อมูล)     1  | 6310301030   | ธนพัฒน์ สุขทิพย์กิจ | 12 |

**สาขา/รุ่น/อาจารย์อยู่บนหัวกระดาษ ไม่ได้อยู่ในตาราง** — ต้องอ่านทั้งสองส่วนเสมอ เพราะจุดสำคัญของ
เฟส 9 คือ "สาขามาจากรายชื่อ ไม่ใช่ผู้สมัครเลือกเอง" ถ้าอ่านมาแต่ตารางก็จะไม่รู้สาขาของใครเลย

รองรับ 4 นามสกุล — ปลายทางคือ rows ชุดเดียวกันหมด:
  .xls  → xlrd (openpyxl อ่านไฟล์รุ่นเก่าไม่ได้)   .xlsx → openpyxl
  .csv  → csv (เผื่อ export เป็น csv หรือแก้ด้วยมือ)
  .pdf  → pypdf ดึงข้อความก่อน ถ้าเป็นไฟล์สแกน (ไม่มี text layer) ค่อยตกไป OCR ชุดเดิมของทะเบียนวัสดุ

ponytail: ไม่ทำหน้า "ร่างนำเข้า" แบบทะเบียนอุปกรณ์ — ตารางนี้เป็นแค่ whitelist ไม่ผูกกับสต็อก/เงิน
นำเข้าผิดก็นำเข้าไฟล์ที่ถูกทับได้ทันที (อัปเดตทับด้วย student_id) จึงคืนสรุปผลไปเลยพอ
"""
import csv
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.eligible_student import EligibleStudent
from app.models.user import User
from app.schemas.student import (
    EligibleStudentResponse,
    PaginatedEligibleStudents,
    StudentImportResult,
)
from app.services import audit_service

SUPPORTED_EXTS = (".xls", ".xlsx", ".csv", ".pdf")
MAX_IMPORT_BYTES = 10 * 1024 * 1024

# รหัสนักศึกษาไทย 10 หลัก (6310301030) — ใช้ทั้งจับคอลัมน์ในตารางและจับบรรทัดใน PDF
_STUDENT_ID = re.compile(r"\b(\d{10})\b")
# คำนำหน้าที่ระบบทะเบียนใส่มาบ้างไม่ใส่บ้าง — ตัดทิ้งก่อนเทียบชื่อ ไม่งั้น "นาย ก" ≠ "ก" ทั้งที่คนเดียวกัน
_NAME_PREFIX = re.compile(r"^(นาย|นางสาว|นาง|น\.ส\.|ด\.ช\.|ด\.ญ\.|MR\.?|MS\.?|MISS)\s*", re.IGNORECASE)

# ชื่อสาขาในไฟล์ทะเบียน → ค่าที่ระบบใช้ (users.major) — เทียบแบบ "มีคำนี้อยู่ในข้อความ"
_MAJOR_KEYWORDS = [
    ("วิศวกรรมคอมพิวเตอร์", "comp_eng"),
    ("computer engineering", "comp_eng"),
    ("ออกแบบดิจิทัล", "digital_design"),
    ("digital design", "digital_design"),
]

_HEADER_LABELS = {
    "faculty": ("คณะ",),
    "major": ("สาขาวิชา", "สาขา"),
    "advisor": ("อาจารย์ที่ปรึกษา", "ที่ปรึกษา"),
}


@dataclass
class ParsedStudents:
    """ผลการอ่านไฟล์ 1 ไฟล์ — meta คือค่าที่ใช้กับ *ทุกแถว* ในไฟล์นั้น (มาจากหัวกระดาษ)"""
    rows: list[dict[str, Any]] = field(default_factory=list)
    faculty: str | None = None
    major: str | None = None          # comp_eng / digital_design
    major_raw: str | None = None      # ข้อความสาขาตามไฟล์ (เก็บไว้เตือนเมื่อ map ไม่ได้)
    generation: str | None = None
    advisor: str | None = None
    warnings: list[str] = field(default_factory=list)


def normalize_name(name: str) -> str:
    """ชื่อสำหรับ "เทียบว่าคนเดียวกันไหม" — ตัดคำนำหน้า ช่องว่าง และวรรณยุกต์ที่พิมพ์ต่างกันออก

    ระบบทะเบียนกับที่ผู้สมัครพิมพ์เอง เว้นวรรคไม่เหมือนกันเป็นเรื่องปกติ ("ธนพัฒน์  สุขทิพย์กิจ")
    ถ้าเทียบสตริงตรง ๆ คนที่ควรผ่านจะตกคิวรออนุมัติทั้งรุ่น
    """
    name = _NAME_PREFIX.sub("", (name or "").strip())
    return "".join(name.split()).lower()


def map_major(text: str | None) -> str | None:
    """ข้อความสาขาจากไฟล์ → ค่าที่ระบบใช้ · ไม่รู้จัก = None (ไม่เดา ปล่อยให้แอดมินเติมทีหลัง)"""
    if not text:
        return None
    low = text.strip().lower()
    for keyword, value in _MAJOR_KEYWORDS:
        if keyword.lower() in low:
            return value
    return None


def _cells_to_text(cells: list[str]) -> str:
    return " ".join(c for c in cells if c).strip()


def _parse_grid(grid: list[list[str]], parsed: ParsedStudents) -> None:
    """อ่านตารางที่เป็น "ช่อง ๆ" (xls/xlsx/csv) — หาหัวตารางจากคำว่า "รหัสนักศึกษา" ไม่ยึดตำแหน่งตายตัว

    ไฟล์ของสำนักทะเบียนมีเซลล์ว่างคั่นเยอะและตำแหน่งขยับได้ตามการตั้งค่าหน้ากระดาษ
    การไล่หาจากคำในหัวตารางจึงทนกว่าการอ้าง index คงที่
    """
    header_idx, cols = None, {}
    for i, row in enumerate(grid):
        for j, cell in enumerate(row):
            text = (cell or "").strip()
            if "รหัสนักศึกษา" in text:
                header_idx = i
                cols["student_id"] = j
            elif header_idx == i and ("ชื่อ" in text and "สกุล" in text or text == "ชื่อ"):
                cols["full_name"] = j
            elif header_idx == i and text == "สถานะ":
                cols["status_code"] = j
        if header_idx == i and "student_id" in cols:
            break

    # หัวกระดาษ (คณะ/สาขา/อาจารย์/รุ่น) อยู่เหนือหัวตาราง — ค่าคือเซลล์ถัดไปทางขวาที่ไม่ว่าง
    for row in grid[: header_idx if header_idx is not None else len(grid)]:
        for j, cell in enumerate(row):
            label = (cell or "").strip().rstrip(":")
            for key, labels in _HEADER_LABELS.items():
                if label in labels and getattr(parsed, "faculty" if key == "faculty" else key, None) is None:
                    value = next((c.strip() for c in row[j + 1:] if c and c.strip()), None)
                    if value:
                        if key == "major":
                            parsed.major_raw = value
                            parsed.major = map_major(value)
                        else:
                            setattr(parsed, key, value)
        line = _cells_to_text(row)
        if parsed.generation is None and ("รุ่น" in line or "หมู่เรียน" in line):
            m = re.search(r"(รุ่น\s*\S+.*)$", line)
            if m:
                parsed.generation = m.group(1).strip()[:100]

    if header_idx is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="ไม่พบหัวตาราง 'รหัสนักศึกษา' ในไฟล์ — ตรวจว่าเป็นไฟล์รายชื่อนักศึกษาหรือไม่")

    name_col = cols.get("full_name")
    for row in grid[header_idx + 1:]:
        sid_cell = row[cols["student_id"]] if cols["student_id"] < len(row) else ""
        m = _STUDENT_ID.search(sid_cell or "")
        if not m:
            continue
        name = (row[name_col].strip() if name_col is not None and name_col < len(row) else "")
        if not name:  # ชื่ออาจถูก merge ไปอยู่เซลล์ถัดไป — กวาดที่เหลือในแถวหาข้อความยาวสุด
            name = max((c.strip() for c in row[cols["student_id"] + 1:] if c and not c.strip().isdigit()),
                       key=len, default="")
        status_col = cols.get("status_code")
        status_code = (row[status_col].strip() if status_col is not None and status_col < len(row) else None)
        parsed.rows.append({
            "student_id": m.group(1),
            "full_name": name,
            "status_code": _clean_status(status_code),
        })


def _clean_status(value: str | None) -> str | None:
    """สถานะจาก xls มาเป็น float ("12.0") เพราะเซลล์เป็นตัวเลข — เก็บเป็น "12" ให้อ่านออก"""
    if not value:
        return None
    value = value.strip()
    return value[:-2] if value.endswith(".0") else value[:20]


def _parse_text(text: str, parsed: ParsedStudents) -> None:
    """อ่านจากข้อความล้วน (PDF) — 1 บรรทัด = 1 คน ถ้ามีรหัส 10 หลักอยู่ในบรรทัดนั้น"""
    for raw_line in text.splitlines():
        line = " ".join(raw_line.split())
        if not line:
            continue
        for key, labels in _HEADER_LABELS.items():
            if getattr(parsed, key, None) is None and any(line.startswith(lb) for lb in labels):
                value = line
                for lb in labels:
                    value = value.replace(lb, "", 1)
                value = value.strip(" :.…-")
                if value:
                    if key == "major":
                        parsed.major_raw = value
                        parsed.major = map_major(value)
                    else:
                        setattr(parsed, key, value)
        if parsed.generation is None and "รุ่น" in line:
            m = re.search(r"(รุ่น\s*\S+.*)$", line)
            if m:
                parsed.generation = m.group(1).strip()[:100]

        m = _STUDENT_ID.search(line)
        if not m or "รหัสนักศึกษา" in line:
            continue
        # ตัดเลขลำดับหน้ารหัส และรหัสออก เหลือชื่อ — ตัดตัวเลข/จุดท้ายบรรทัด (คอลัมน์สถานะ) ทิ้ง
        name = line[m.end():].strip(" .|")
        name = re.sub(r"[\d.\s]+$", "", name).strip()
        if name:
            parsed.rows.append({"student_id": m.group(1), "full_name": name, "status_code": None})


def _grid_from_xlsx(path: str) -> list[list[str]]:
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheet = wb[wb.sheetnames[0]]
    return [[("" if c is None else str(c)) for c in row] for row in sheet.iter_rows(values_only=True)]


def _grid_from_xls(path: str) -> list[list[str]]:
    try:
        import xlrd
    except ImportError:  # pragma: no cover - ขึ้นเฉพาะตอนยังไม่ได้ลง dependency
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED,
                            detail="ยังไม่ได้ติดตั้งตัวอ่านไฟล์ .xls บนเซิร์ฟเวอร์ (xlrd)")
    book = xlrd.open_workbook(path)
    sheet = book.sheet_by_index(0)
    return [[str(sheet.cell_value(r, c)).strip() for c in range(sheet.ncols)]
            for r in range(sheet.nrows)]


def _grid_from_csv(path: str) -> list[list[str]]:
    # utf-8-sig — ไฟล์ที่ Excel บันทึกมามี BOM นำหน้า ถ้าไม่ตัดจะทำให้คำแรกของไฟล์เทียบไม่ตรง
    with open(path, encoding="utf-8-sig", errors="replace", newline="") as f:
        return [list(row) for row in csv.reader(f)]


def _text_from_pdf(path: str) -> str:
    """ดึงข้อความจาก PDF — ไฟล์ที่ export มาจากระบบมี text layer อยู่แล้ว อ่านตรงได้เร็วและแม่นกว่า OCR
    ไฟล์สแกน (ไม่มี text layer) ค่อยตกไปใช้ OCR ตัวเดียวกับที่ทะเบียนวัสดุใช้อยู่
    """
    from pypdf import PdfReader

    text = "\n".join((page.extract_text() or "") for page in PdfReader(path).pages)
    if len(text.strip()) >= 40:
        return text
    from app.services import ocr_import
    return ocr_import._ocr_text(path)


def parse_file(path: str, filename: str) -> ParsedStudents:
    """ไฟล์ 1 ไฟล์ → รายชื่อ + ข้อมูลหัวกระดาษ (ยังไม่แตะฐานข้อมูล)"""
    ext = os.path.splitext(filename or "")[1].lower()
    if ext not in SUPPORTED_EXTS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"รองรับเฉพาะไฟล์ {', '.join(SUPPORTED_EXTS)}")
    parsed = ParsedStudents()
    if ext == ".pdf":
        _parse_text(_text_from_pdf(path), parsed)
    else:
        grid = {".xlsx": _grid_from_xlsx, ".xls": _grid_from_xls, ".csv": _grid_from_csv}[ext](path)
        _parse_grid(grid, parsed)

    if not parsed.rows:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="ไม่พบรายชื่อนักศึกษาในไฟล์ (ต้องมีรหัสนักศึกษา 10 หลัก)")
    if parsed.major is None:
        parsed.warnings.append(
            f"อ่านสาขาจากไฟล์ไม่ได้{f' (พบข้อความ: {parsed.major_raw})' if parsed.major_raw else ''}"
            " — รายชื่อชุดนี้จะไม่มีสาขากำกับ ผู้สมัครต้องเลือกสาขาเองเหมือนเดิม")
    # ชื่อว่าง = แถวที่ตัดคอลัมน์ผิด ปล่อยผ่านไปจะได้ whitelist ที่เทียบชื่อไม่ได้
    blanks = [r["student_id"] for r in parsed.rows if not r["full_name"]]
    if blanks:
        parsed.warnings.append(f"อ่านชื่อไม่ได้ {len(blanks)} แถว (รหัส {', '.join(blanks[:5])})")
    return parsed


def read_upload(content: bytes, filename: str) -> ParsedStudents:
    """เวอร์ชันที่รับ bytes ตรง ๆ (ใช้ในเทส) — เขียนลงไฟล์ชั่วคราวเพราะทุกไลบรารีอ่านจาก path"""
    import tempfile

    ext = os.path.splitext(filename or "")[1].lower()
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name
    try:
        return parse_file(tmp_path, filename)
    finally:
        os.unlink(tmp_path)


# ── บันทึกลงฐานข้อมูล / ใช้ตอนสมัคร ──────────────────────────────────────────

async def import_students(
    db: AsyncSession, admin: User, path: str, filename: str
) -> StudentImportResult:
    """นำเข้าไฟล์รายชื่อ 1 ไฟล์ — เพิ่มคนใหม่ / อัปเดตทับคนเดิมด้วย student_id

    **ไม่ล้างตารางก่อนนำเข้า** เพราะไฟล์จริงคือ "รายชื่อของอาจารย์ที่ปรึกษา 1 คน"
    ล้างทุกครั้งที่นำเข้า = นำเข้าไฟล์ของอาจารย์คนที่สองแล้วรายชื่อของคนแรกหายหมด
    """
    parsed = parse_file(path, filename)
    existing = {
        s.student_id: s for s in (await db.execute(
            select(EligibleStudent).where(
                EligibleStudent.student_id.in_([r["student_id"] for r in parsed.rows]))
        )).scalars().all()
    }

    added = updated = 0
    now = datetime.now(timezone.utc)
    for row in parsed.rows:
        values = {
            "full_name": row["full_name"] or (existing.get(row["student_id"]).full_name
                                              if row["student_id"] in existing else ""),
            "status_code": row["status_code"],
            "faculty": parsed.faculty,
            "generation": parsed.generation,
            "advisor": parsed.advisor,
            "source_file": (filename or "")[:255],
            "imported_at": now,
            "imported_by": admin.id,
        }
        # สาขาที่อ่านไม่ได้ต้องไม่ไปล้างค่าเดิมที่เคยนำเข้าถูกต้องแล้วทิ้ง
        if parsed.major:
            values["major"] = parsed.major
        student = existing.get(row["student_id"])
        if student:
            for key, value in values.items():
                setattr(student, key, value)
            updated += 1
        else:
            db.add(EligibleStudent(student_id=row["student_id"], **values))
            added += 1

    await audit_service.log_action(db, admin, "import_eligible_students", "users", admin.id, {
        "source": filename, "count": len(parsed.rows), "added": added, "updated": updated,
        "major": parsed.major_raw, "generation": parsed.generation, "advisor": parsed.advisor,
    })
    await db.commit()
    return StudentImportResult(
        added=added, updated=updated, total=len(parsed.rows),
        faculty=parsed.faculty, major=parsed.major, major_raw=parsed.major_raw,
        generation=parsed.generation, advisor=parsed.advisor, warnings=parsed.warnings,
    )


async def list_students(
    db: AsyncSession, page: int, page_size: int, search: str | None = None, cohort: str | None = None,
) -> PaginatedEligibleStudents:
    """รายชื่อที่รับรองไว้ + ธงว่าคนนั้นสมัครใช้งานแล้วหรือยัง (ไล่ตามคนที่ยังไม่เข้าระบบได้)

    cohort = 2 หลักแรกของรหัสนักศึกษา (ปีที่เข้า เช่น "66") — หลักเดียวกับ study_year.enrollment_year_from_student_id
    """
    query = select(EligibleStudent)
    if cohort:
        query = query.where(EligibleStudent.student_id.like(f"{cohort}%"))
    if search:
        kw = f"%{search.strip()}%"
        query = query.where(or_(EligibleStudent.student_id.ilike(kw),
                                EligibleStudent.full_name.ilike(kw),
                                EligibleStudent.advisor.ilike(kw)))
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    rows = list((await db.execute(
        query.order_by(EligibleStudent.student_id).offset((page - 1) * page_size).limit(page_size)
    )).scalars().all())

    registered = set((await db.execute(
        select(User.student_id).where(User.student_id.in_([r.student_id for r in rows]))
    )).scalars().all()) if rows else set()

    items = []
    for row in rows:
        item = EligibleStudentResponse.model_validate(row, from_attributes=True)
        item.has_account = row.student_id in registered
        items.append(item)
    prefix = func.left(EligibleStudent.student_id, 2)
    cohorts = dict((await db.execute(
        select(prefix, func.count()).group_by(prefix).order_by(prefix))).all())
    return PaginatedEligibleStudents(items=items, total=total, page=page, page_size=page_size, cohorts=cohorts)


async def delete_student(db: AsyncSession, admin: User, row_id: uuid.UUID) -> None:
    """ถอนรายชื่อออกจาก whitelist — ไม่กระทบบัญชีที่สมัครไปแล้ว (คนละตาราง)"""
    row = (await db.execute(
        select(EligibleStudent).where(EligibleStudent.id == row_id))).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ไม่พบรายชื่อนี้")
    await audit_service.log_action(db, admin, "delete_eligible_student", "users", admin.id, {
        "identifier": row.student_id, "full_name": row.full_name,
    })
    await db.delete(row)
    await db.commit()


async def find_eligible(db: AsyncSession, student_id: str | None) -> EligibleStudent | None:
    """หาแถวในรายชื่อจากรหัสนักศึกษา — จุดเดียวที่ auth_service ใช้ตอนสมัคร"""
    if not student_id:
        return None
    return (await db.execute(
        select(EligibleStudent).where(EligibleStudent.student_id == student_id.strip())
    )).scalar_one_or_none()
