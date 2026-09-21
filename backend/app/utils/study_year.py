"""ชั้นปีนักศึกษา — ต้องมีจุดเดียวในระบบ (เฟส 10, feedback 15 ก.ย. 69)

เหตุผลเดียวกับ utils/duedate.py: ถ้าปล่อยให้แต่ละจุด (สมัครสมาชิก, หน้าจัดการผู้ใช้, Dashboard,
กฎจ่ายของ) คำนวณชั้นปีเองซ้ำที่อื่น จะเจอบั๊กแบบ "หน้านี้บอกปี 2 อีกหน้าบอกปี 3" ทันทีที่มีคนแก้สูตร
ที่เดียวแล้วลืมอีกที่ — ทุกจุดต้องเรียกฟังก์ชันในไฟล์นี้เท่านั้น (ห้าม coalesce/คำนวณเองซ้ำ)

ฟังก์ชันทั้งหมดบริสุทธิ์ (ไม่แตะ DB) — ผู้เรียกอ่านค่า setting `academic_year_start` มาเองแล้วส่งเข้ามา

หมายเหตุเรื่อง role: ฟังก์ชันในไฟล์นี้รับแค่ enrollment_year/study_years ตรง ๆ ไม่รู้จัก User/role — ผู้เรียก
ที่มี User object (เช่น users_service.attach_study_year, equipment_service.dispatch_order) ต้องเป็นคน
กันเองว่า role != "student" ถือเป็นบุคลากรเสมอ แม้จะยังมี enrollment_year ค้างจากตอนเป็นนักศึกษาก่อนถูก
เลื่อนสิทธิ์ (ดู CLAUDE.md — ห้ามคำนวณสูตรซ้ำที่อื่น แต่การ "ส่ง None แทน enrollment_year เมื่อไม่ใช่นักศึกษา"
ไม่ใช่สูตรคำนวณชั้นปี จึงทำที่ผู้เรียกได้โดยไม่ผิดกฎนี้)
"""
import re
from dataclasses import dataclass
from datetime import date

# ค่าเริ่มต้นวันเลื่อนชั้นปี (1 มิถุนายน) — ใช้เมื่อยังไม่มีแถว setting หรือ setting เพี้ยน (parse ไม่ได้)
DEFAULT_ACADEMIC_YEAR_START = "06-01"


def _parse_mmdd(value: str | None) -> tuple[int, int]:
    """แปลง "MM-DD" เป็น (month, day) — ค่าที่ parse ไม่ได้/นอกช่วง ใช้ค่าเริ่มต้นแทนเงียบ ๆ
    (ตั้งค่าเสีย ไม่ควรทำให้ระบบทั้งระบบคำนวณชั้นปีไม่ได้)
    """
    if value:
        try:
            month_s, day_s = value.split("-")
            month, day = int(month_s), int(day_s)
            if 1 <= month <= 12 and 1 <= day <= 31:
                return month, day
        except (ValueError, AttributeError):
            pass
    m, d = DEFAULT_ACADEMIC_YEAR_START.split("-")
    return int(m), int(d)


def academic_year(today: date, academic_year_start: str = DEFAULT_ACADEMIC_YEAR_START) -> int:
    """ปีการศึกษาปัจจุบัน (พ.ศ.) ของวันที่กำหนด

    ปีปัจจุบัน (พ.ศ. = ค.ศ. + 543) ถ้าวันนี้ถึงหรือเลยวันเริ่มปีการศึกษาแล้ว (ค่าเริ่มต้น 1 มิ.ย.)
    ไม่งั้นยังนับเป็นปีการศึกษาก่อนหน้า — ตัวอย่าง: 2027-05-31 ยังเป็นปีเก่า, 2027-06-01 เป็นปีใหม่แล้ว
    """
    month, day = _parse_mmdd(academic_year_start)
    be_year = today.year + 543
    if (today.month, today.day) < (month, day):
        be_year -= 1
    return be_year


@dataclass(frozen=True)
class StudyYearInfo:
    """ผลคำนวณชั้นปีของนักศึกษา 1 คน ณ วันที่กำหนด"""
    year_level: int | None            # ชั้นปีจริง (ตกค้างคำนวณต่อเนื่องได้ เช่น 5, 6, ...) — None = บุคลากร
    is_retained: bool                 # ชั้นปี > จำนวนปีที่ควรเรียนจบ
    remaining_study_years: int | None  # เวลาเรียนที่เหลือ (ปี) — อย่างน้อย 1 เสมอ, None = บุคลากร
    label: str                        # ป้ายภาษาไทยพร้อมใช้: "ปีที่ 2" / "ตกค้าง (ปีที่ 5)" / "บุคลากร"


def compute_study_year(
    enrollment_year: int | None,
    study_years: int,
    today: date | None = None,
    academic_year_start: str = DEFAULT_ACADEMIC_YEAR_START,
) -> StudyYearInfo:
    """คำนวณชั้นปี/สถานะตกค้าง/เวลาเรียนที่เหลือของนักศึกษา 1 คน

    ชั้นปี = ปีการศึกษาปัจจุบัน (พ.ศ.) − ปีที่เข้าศึกษา (พ.ศ.) + 1 · **อย่างน้อยปีที่ 1 เสมอ** — รุ่นที่เพิ่ง
    สมัคร/ backfill ด้วยรหัสของปีการศึกษาที่ยังไม่เริ่ม (เช่นสมัครก่อนถึงวันเลื่อนชั้น 1 มิ.ย. ด้วยรหัสรุ่นใหม่)
    จะได้ชั้นปี ≤ 0 ถ้าไม่ clamp — ถือว่าเป็นปี 1 ไปก่อน (ยังไม่มี "ปีที่ 0"/ติดลบจริงในระบบการศึกษาไทย
    แก้ตามรีวิวรอบ 3, MINOR-2 — เดิมปล่อยผ่านทำให้ Dashboard การ์ดชั้นปีนับไม่ครบ เพราะ YEAR_GROUP_ORDER
    ไม่มีช่อง "0"/ติดลบ)
    ตกค้าง = ชั้นปี > จำนวนปีที่ควรเรียนจบ (study_years — ปกติ 4, เทียบโอนได้ 2/3/4 แล้วแต่คน)
    เวลาเรียนที่เหลือ = max(study_years − ชั้นปี + 1, 1) — ใช้จับคู่กับอายุที่เหลือของอุปกรณ์ตอนจ่ายของ

    enrollment_year เป็น None (อาจารย์/เจ้าหน้าที่ที่ไม่มีรหัสนักศึกษา) → คืน "บุคลากร" เสมอ ไม่ใช่ 0/None ปนกับ
    นักศึกษาปี 0 ที่ไม่มีจริง
    """
    if enrollment_year is None:
        return StudyYearInfo(year_level=None, is_retained=False, remaining_study_years=None, label="บุคลากร")

    cur = academic_year(today or date.today(), academic_year_start)
    level = max(cur - enrollment_year + 1, 1)
    retained = level > study_years
    remaining = max(study_years - level + 1, 1)
    label = f"ตกค้าง (ปีที่ {level})" if retained else f"ปีที่ {level}"
    return StudyYearInfo(year_level=level, is_retained=retained, remaining_study_years=remaining, label=label)


YEAR_GROUP_ORDER = ("1", "2", "3", "4", "retained", "staff", "unknown")


def year_group_key(
    is_student: bool,
    enrollment_year: int | None,
    study_years: int,
    today: date | None = None,
    academic_year_start: str = DEFAULT_ACADEMIC_YEAR_START,
) -> str:
    """แปลงผู้ใช้ 1 คน → group key มาตรฐาน (`"1".."4"` / `"retained"` / `"staff"` / `"unknown"`) — **จุดเดียว**
    ที่ใช้ทั้งการ์ดชั้นปีบน Dashboard (dashboard_service.get_summary) และตัวกรอง `year_group` ของหน้าจัดการ
    ผู้ใช้ (users_service.list_users) เดิมสองจุดนี้คำนวณ "ตกค้าง"/"นอกช่วงปกติ" ไม่ตรงกัน (dashboard พับ
    ชั้นปีที่ไม่อยู่ในช่วง 1-4 แต่ `is_retained=False` — เช่นข้อมูลเก่าที่ `study_years` เคยกว้างกว่า 4 —
    เข้ากลุ่ม "retained" แต่ users_service ไม่พับ ทำให้ user แบบนี้หลุดจากทุกตัวกรอง year_group ทั้งที่การ์ด
    นับว่าอยู่กลุ่มตกค้าง) แก้ตามรีวิวรอบ 4, M-b — ต้องเรียกจุดนี้จุดเดียวทั้งสองที่ ห้ามคำนวณ/พับกลุ่มซ้ำเอง

    is_student ไม่ใช่ "สูตรคำนวณชั้นปี" (ผู้เรียกส่ง `role == "student"` เข้ามาเอง — กฎเดียวกับที่
    `attach_study_year`/`list_users.matches()` ทำอยู่แล้วเรื่อง role != student ถือเป็นบุคลากรเสมอ)
    """
    if not is_student:
        return "staff"
    if enrollment_year is None:
        return "unknown"
    info = compute_study_year(enrollment_year, study_years or 4, today=today, academic_year_start=academic_year_start)
    if info.is_retained or info.year_level is None or not (1 <= info.year_level <= 4):
        return "retained"
    return str(info.year_level)


_STUDENT_ID_RE = re.compile(r"\d{10}")


def enrollment_year_from_student_id(student_id: str | None) -> int | None:
    """อ่านปีที่เข้าศึกษา (พ.ศ.) จาก 2 หลักแรกของรหัสนักศึกษา 10 หลัก — จุดเดียวที่แปลงรหัส → ปีที่เข้า

    ใช้ทั้งตอนสมัคร (auth_service.register), พรีวิวปีการศึกษาก่อนสมัคร (GET /auth/study-year-preview)
    และ migration 0040 (backfill ของเดิม) — สูตรต้องตรงกันเป๊ะทั้ง 3 จุด

    บังคับรูปแบบเต็ม 10 หลักพอดี (`^\\d{10}$`) ให้ตรงกับ RegisterRequest.student_id/UserCreateRequest.student_id
    (schemas/auth.py, schemas/user.py — pattern `^\\d{10}$`) และ migration 0040 (`WHERE student_id ~
    '^[0-9]{10}$'`) เป๊ะ — เดิมเช็คแค่ "2 ตัวแรกเป็นเลข ยาวอย่างน้อย 2 ตัว" ทำให้ผ่านง่ายเกินไปกับรหัสที่ไม่ตรง
    รูปแบบจริง (เช่น "12abc" หรือรหัสสั้นกว่า 10 หลัก) ต่างจากอีก 3 จุดที่บังคับ 10 หลักเต็ม (พบตอนรีวิวรอบ 2)
    """
    if not student_id or not _STUDENT_ID_RE.fullmatch(student_id):
        return None
    return 2500 + int(student_id[:2])
