"""ชั้นปีนักศึกษา (เฟส 10 — feedback 15 ก.ย. 69)

จุดที่ต้องไม่พังเด็ดขาด:
- สูตรมีจุดเดียวที่ app.utils.study_year.compute_study_year() — ไม่มีสูตรคู่แฝดฝั่งอื่น
- เลื่อนชั้นปีที่ขอบวันเลื่อนชั้นปี (ค่าเริ่มต้น 1 มิ.ย.) ต้องตรงเป๊ะ ไม่ใช่ ± 1 วัน
- รหัสรุ่นเทียบโอน ("ทอ") แต่เลือกหลักสูตรปกติตอนสมัคร ต้องถูกกันไว้ ไม่ให้สร้างบัญชีผิดหลักสูตร
- แอดมินแก้ชั้นปีรายคนได้ บังคับเหตุผลเสมอ ลง audit update_user_study

หมายเหตุ: conftest.py มี PYTEST_ALLOW_DB=1 รันใส่ DB dev จริง — ทุกเทสต้อง cleanup ใน fixture teardown
รวม audit_logs ของตัวเอง (ตามกฎ CLAUDE.md)
"""
import csv
import io
import uuid
from datetime import date, datetime, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, or_, select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.audit_log import AuditLog
from app.models.auth_token import AuthToken
from app.models.eligible_student import EligibleStudent
from app.models.notification import Notification
from app.models.setting import Setting
from app.models.user import User
from app.utils.study_year import (
    DEFAULT_ACADEMIC_YEAR_START,
    academic_year,
    compute_study_year,
    enrollment_year_from_student_id,
)
from tests.conftest import auth


async def _current_academic_year_start() -> str:
    """อ่านค่า setting จริงตอนรันเทส — ไม่ hardcode "06-01" (แอดมินปรับค่านี้ได้เองผ่านหน้าตั้งค่า)"""
    async with AsyncSessionLocal() as db:
        row = (await db.execute(
            select(Setting.value).where(Setting.key == "academic_year_start"))).scalar_one_or_none()
    return row or DEFAULT_ACADEMIC_YEAR_START

TAG_PREFIX = "98"  # รหัสทดสอบขึ้นต้นด้วย 98 กันชนกับของจริง/เทสอื่น


# ── สูตร (ฟังก์ชันบริสุทธิ์) ──────────────────────────────────────────────────

def test_academic_year_rolls_over_at_configured_boundary():
    """ค่าเริ่มต้น 1 มิ.ย. — 31 พ.ค. ยังเป็นปีเก่า, 1 มิ.ย. เป็นปีใหม่แล้ว"""
    assert academic_year(date(2027, 5, 31)) == academic_year(date(2026, 9, 15))
    assert academic_year(date(2027, 6, 1)) == academic_year(date(2027, 5, 31)) + 1


def test_compute_study_year_worked_examples_from_plan():
    """ณ 15 ก.ย. 2569 (ปีการศึกษา 2569): รหัส 69 = ปี 1 · 66 = ปี 4 · 65 = ตกค้าง (ปีที่ 5)"""
    today = date(2026, 9, 15)  # ตรงกับ "15 ก.ย. 2569" ในแผน
    ay = academic_year(today)
    assert ay == 2569

    info_69 = compute_study_year(2569, 4, today=today)
    assert info_69.year_level == 1 and not info_69.is_retained and info_69.remaining_study_years == 4
    assert info_69.label == "ปีที่ 1"

    info_66 = compute_study_year(2566, 4, today=today)
    assert info_66.year_level == 4 and not info_66.is_retained and info_66.remaining_study_years == 1
    assert info_66.label == "ปีที่ 4"

    info_65 = compute_study_year(2565, 4, today=today)
    assert info_65.year_level == 5 and info_65.is_retained and info_65.remaining_study_years == 1
    assert info_65.label == "ตกค้าง (ปีที่ 5)"


def test_compute_study_year_advances_after_rollover_date():
    """พอถึง 1 มิ.ย. 2570 รหัส 69 ต้องเป็นปี 2 และ 66 กลายเป็นตกค้าง"""
    after_rollover = date(2027, 6, 1)
    info_69 = compute_study_year(2569, 4, today=after_rollover)
    assert info_69.year_level == 2 and not info_69.is_retained

    info_66 = compute_study_year(2566, 4, today=after_rollover)
    assert info_66.year_level == 5 and info_66.is_retained


def test_compute_study_year_transfer_student_custom_years():
    """เทียบโอน 2 ปี — ปีที่ 2 คือปีสุดท้าย ไม่ใช่ตกค้าง"""
    today = date(2026, 9, 15)
    info = compute_study_year(2568, 2, today=today)  # เข้าปี 2568, วันนี้ 2569 → ปีที่ 2
    assert info.year_level == 2 and not info.is_retained and info.remaining_study_years == 1


def test_compute_study_year_clamps_level_to_at_least_one():
    """สมัครด้วยรหัสของรุ่นที่ยังไม่เริ่มปีการศึกษา (เช่น backfill/สมัครก่อนถึงวันเลื่อนชั้นของรุ่นตัวเอง)
    ต้องไม่ได้ "ปีที่ 0"/ติดลบ — YEAR_GROUP_ORDER ฝั่ง dashboard_service มีแค่ "1".."4" การ์ดจะทิ้งกลุ่มนี้
    เงียบ ๆ ถ้าไม่ clamp (แก้ตามรีวิวรอบ 3, MINOR-2)
    """
    today = date(2026, 9, 15)
    ay = academic_year(today)  # 2569

    info = compute_study_year(ay + 1, 4, today=today)  # รหัสรุ่นถัดไปที่ยังไม่ถึงวันเข้าเรียนจริง
    assert info.year_level == 1
    assert not info.is_retained
    assert info.remaining_study_years == 4
    assert info.label == "ปีที่ 1"

    info_far_future = compute_study_year(ay + 5, 4, today=today)
    assert info_far_future.year_level == 1


def test_compute_study_year_staff_has_no_enrollment_year():
    info = compute_study_year(None, 4)
    assert info.year_level is None
    assert info.is_retained is False
    assert info.remaining_study_years is None
    assert info.label == "บุคลากร"


def test_enrollment_year_from_student_id():
    assert enrollment_year_from_student_id("6910301234") == 2569
    assert enrollment_year_from_student_id("6610301234") == 2566
    assert enrollment_year_from_student_id(None) is None
    assert enrollment_year_from_student_id("abc") is None


# ── GET /auth/study-year-preview (public) ────────────────────────────────────

@pytest.mark.asyncio(loop_scope="session")
async def test_study_year_preview_endpoint(client: AsyncClient):
    """ไม่ hardcode "ปีที่ 1" — ค่านั้นถูกแค่ ณ วันที่เขียนเทส (15 ก.ย. 2569) กับ setting เริ่มต้น (1 มิ.ย.)
    เท่านั้น เลยวันเลื่อนชั้นปีหรือแอดมินปรับ setting นี้เมื่อไหร่ก็พังทันที (time bomb ที่พบตอนรีวิวรอบ 2)
    คำนวณค่าที่ควรได้จาก academic_year()/compute_study_year() ตัวเดียวกับ production ด้วยค่า setting จริง
    ในระบบตอนรันเทสแทน
    """
    start = await _current_academic_year_start()
    info = compute_study_year(2569, 4, academic_year_start=start)

    r = await client.get("/auth/study-year-preview", params={"student_id": "6910301234"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enrollment_year"] == 2569
    assert body["year_level"] == info.year_level
    assert body["label"] == info.label


@pytest.mark.asyncio(loop_scope="session")
async def test_study_year_preview_rejects_non_digit_id(client: AsyncClient):
    r = await client.get("/auth/study-year-preview", params={"student_id": "abcdefghij"})
    assert r.status_code == 400


# ── สมัครด้วยรหัสรุ่นเทียบโอน ("ทอ") ──────────────────────────────────────────

def _csv_bytes(students: list[tuple[str, str]], generation: str) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["", "", "", "", "", "สถาบันเทคโนโลยีจิตรลดา", "", "", "รายชื่อนักศึกษาในที่ปรึกษา"])
    writer.writerow(["", "คณะ", "", "", "", "เทคโนโลยีดิจิทัล"])
    writer.writerow(["", "สาขาวิชา", "", "", "", "วิศวกรรมคอมพิวเตอร์", "", "", "", "", "", generation])
    writer.writerow(["", "อาจารย์ที่ปรึกษา", "", "", "", "ทดสอบ อาจารย์ที่ปรึกษา"])
    writer.writerow(["ที่", "", "", "รหัสนักศึกษา", "", "", "", "ชื่อ-นามสกุล", "", "สถานะ"])
    for i, (sid, name) in enumerate(students, 1):
        writer.writerow([str(i), "", "", sid, "", "", "", name, "", "11"])
    return buf.getvalue().encode("utf-8-sig")


@pytest_asyncio.fixture(loop_scope="session")
async def clean_transfer_students():
    """คืน list ว่างให้เทสเติม student_id ที่ตัวเองสร้างเข้ามาเอง — ลบเฉพาะรหัสที่อยู่ใน list นี้เป๊ะตอน
    teardown (แก้ตามรีวิวรอบ 4, M-i: เดิมใช้ `LIKE '{TAG_PREFIX}%'` กวาดทั้งช่วงรหัส เสี่ยงชน/ลบข้อมูลจริง
    หรือของเทสไฟล์อื่นที่บังเอิญใช้ prefix เดียวกันพร้อมกัน — ตอนนี้ลบด้วย `.in_(student_ids)` ที่เทสระบุเอง
    เป๊ะแทน)

    started ถ่ายก่อนตัวเทสเริ่มทำงานจริง — ใช้ scope การลบแจ้งเตือนที่ไม่ได้ผูกกับ user_id/target_id ของ
    บัญชีทดสอบเลย (ตามกฎ CLAUDE.md ห้ามลบ log ด้วย target_id/actor_id ของแอดมินจริงเพียว ๆ):
    - "registration_pending" ที่ /auth/register ส่งไปหา staff จริงทุกคนตอนบัญชีเข้าคิวรออนุมัติ (ข้อความมี
      รหัสนักศึกษาฝังอยู่ ไม่ได้อยู่ใต้ user_id ของผู้สมัคร — เช่น test_register_regular_program_defaults_to_4_years
      ที่ไม่ได้อยู่ในรายชื่อเลยเข้าคิว pending) — กรองเฉพาะข้อความที่มี student_id ที่เทสนี้สร้างจริงเป๊ะ
    audit "import_eligible_students" ไม่ต้องตามลบที่นี่ — actor คือแอดมินทดสอบ (`admin_token`) ซึ่ง
    `conftest._delete_user_cascade` ลบ log ของมันตอนจบ session อยู่แล้ว (กรองด้วย action+เวลาเสี่ยงลบ log จริง)
    """
    started = datetime.now(timezone.utc)
    student_ids: list[str] = []
    yield student_ids
    if not student_ids:
        return
    async with AsyncSessionLocal() as db:
        ids = (await db.execute(
            select(User.id).where(User.student_id.in_(student_ids)))).scalars().all()
        for uid in ids:
            await db.execute(delete(Notification).where(Notification.user_id == uid))
            await db.execute(delete(AuthToken).where(AuthToken.user_id == uid))
            await db.execute(delete(AuditLog).where(AuditLog.actor_id == uid))
            await db.execute(delete(AuditLog).where(AuditLog.target_id == uid))
        await db.execute(delete(User).where(User.student_id.in_(student_ids)))
        await db.execute(delete(EligibleStudent).where(EligibleStudent.student_id.in_(student_ids)))
        await db.execute(delete(Notification).where(
            Notification.type == "registration_pending",
            Notification.sent_at >= started,
            or_(*[Notification.message.like(f"%({sid})%") for sid in student_ids]),
        ))
        await db.commit()


@pytest.mark.asyncio(loop_scope="session")
async def test_register_transfer_generation_requires_transfer_program(
    client: AsyncClient, admin_token: str, clean_transfer_students,
):
    """รหัสอยู่ในรุ่นที่มี "ทอ" แต่เลือกหลักสูตรปกติ → 400 ให้เลือกเทียบโอนก่อน"""
    sid = f"{TAG_PREFIX}10301001"
    clean_transfer_students.append(sid)
    await client.post("/eligible-students/import", headers=auth(admin_token),
                      files={"file": ("a.csv", _csv_bytes([(sid, "ทดสอบ เทียบโอนหนึ่ง")], "รุ่น 66 วค.ทอ"),
                                      "text/csv")})

    blocked = await client.post("/auth/register", json={
        "full_name": "ทดสอบ เทียบโอนหนึ่ง", "student_id": sid,
        "email": f"tr{uuid.uuid4().hex[:6]}@student.cdti.ac.th",
        "password": "Test1234!", "major": "comp_eng", "phone": "0812345678", "pdpa_consent": True,
        "is_transfer": False,
    })
    assert blocked.status_code == 400
    assert "เทียบโอน" in blocked.json()["detail"]

    ok = await client.post("/auth/register", json={
        "full_name": "ทดสอบ เทียบโอนหนึ่ง", "student_id": sid,
        "email": f"tr{uuid.uuid4().hex[:6]}@student.cdti.ac.th",
        "password": "Test1234!", "major": "comp_eng", "phone": "0812345678", "pdpa_consent": True,
        "is_transfer": True, "study_years": 2,
    })
    assert ok.status_code in (200, 201), ok.text

    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.student_id == sid))).scalar_one()
        assert user.is_transfer is True
        assert user.study_years == 2
        assert user.enrollment_year == enrollment_year_from_student_id(sid)


@pytest.mark.asyncio(loop_scope="session")
async def test_register_regular_program_defaults_to_4_years(client: AsyncClient, clean_transfer_students):
    sid = f"{TAG_PREFIX}10301099"
    clean_transfer_students.append(sid)
    r = await client.post("/auth/register", json={
        "full_name": "ทดสอบ หลักสูตรปกติ", "student_id": sid,
        "email": f"reg{uuid.uuid4().hex[:6]}@student.cdti.ac.th",
        "password": "Test1234!", "major": "comp_eng", "phone": "0812345678", "pdpa_consent": True,
    })
    assert r.status_code in (200, 201), r.text
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.student_id == sid))).scalar_one()
        assert user.is_transfer is False
        assert user.study_years == 4
        assert user.enrollment_year == enrollment_year_from_student_id(sid)


# ── แอดมินแก้ชั้นปีรายคน ──────────────────────────────────────────────────────

@pytest_asyncio.fixture(loop_scope="session")
async def temp_student():
    uid = uuid.uuid4()
    sid = f"{TAG_PREFIX}10309999"
    async with AsyncSessionLocal() as db:
        db.add(User(
            id=uid, full_name="นักศึกษา ทดสอบชั้นปี", email=f"stuyear_{uid.hex[:6]}@cdti.ac.th",
            password_hash=hash_password("Test1234!"), role="student", student_id=sid,
            email_verified=True, is_active=True, enrollment_year=2569, study_years=4,
        ))
        await db.commit()
    yield uid
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Notification).where(Notification.user_id == uid))
        await db.execute(delete(AuthToken).where(AuthToken.user_id == uid))
        await db.execute(delete(AuditLog).where(AuditLog.actor_id == uid))
        await db.execute(delete(AuditLog).where(AuditLog.target_id == uid))
        await db.execute(delete(User).where(User.id == uid))
        await db.commit()


@pytest.mark.asyncio(loop_scope="session")
async def test_admin_update_study_requires_reason_and_logs_audit(
    client: AsyncClient, admin_token: str, temp_student,
):
    uid = temp_student
    missing_reason = await client.patch(f"/users/{uid}/study", headers=auth(admin_token),
                                        json={"enrollment_year": 2568})
    assert missing_reason.status_code == 422

    r = await client.patch(f"/users/{uid}/study", headers=auth(admin_token), json={
        "enrollment_year": 2568, "study_years": 3, "is_transfer": True,
        "reason": "ย้ายสาขามาเทียบโอน",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enrollment_year"] == 2568
    assert body["study_years"] == 3
    assert body["is_transfer"] is True
    assert body["year_level"] is not None

    async with AsyncSessionLocal() as db:
        log = (await db.execute(
            select(AuditLog).where(AuditLog.action == "update_user_study", AuditLog.target_id == uid)
        )).scalars().first()
        assert log is not None
        assert log.detail["reason"] == "ย้ายสาขามาเทียบโอน"
        assert log.detail["changes"]["enrollment_year"] == [2569, 2568]


@pytest.mark.asyncio(loop_scope="session")
async def test_user_response_exposes_computed_year_fields(
    client: AsyncClient, admin_token: str, temp_student,
):
    """GET /users ต้องเห็น year_level/is_retained/remaining_study_years/study_year_label คำนวณสด

    ไม่ hardcode "ปีที่ 1" (ขึ้นกับวันนี้ + setting academic_year_start — time bomb เดียวกับเทสด้านบน) และ
    ไม่สมมติว่า temp_student จะอยู่ในหน้าแรก 100 คนเสมอ (ไม่มี ORDER BY การันตี DB dev มีผู้ใช้จริงปนอยู่
    อาจเกิน 100 คนได้ — ทั้งสองจุดพบตอนรีวิวรอบ 2) ไล่ทุกหน้าจนกว่าจะเจอหรือหมด total แทนการเดาหน้าเดียว
    """
    uid = temp_student
    start = await _current_academic_year_start()
    info = compute_study_year(2569, 4, academic_year_start=start)

    match, page = None, 1
    while match is None:
        listed = (await client.get("/users", params={"role": "student", "page_size": 100, "page": page},
                                   headers=auth(admin_token))).json()
        match = next((u for u in listed["items"] if u["id"] == str(uid)), None)
        if match is not None or page * 100 >= listed["total"]:
            break
        page += 1
    assert match is not None, "หา temp_student ไม่เจอในทุกหน้าของ GET /users"
    assert match["year_level"] == info.year_level
    assert match["is_retained"] == info.is_retained
    assert match["remaining_study_years"] == info.remaining_study_years
    assert match["study_year_label"] == info.label


# ── list_users(year_group=retained|staff) (M6 — รีวิวรอบ 2) ──────────────────────────────────────────

@pytest_asyncio.fixture(loop_scope="session")
async def temp_retained_student():
    """enrollment_year เก่ามาก (พ.ศ. 2500) การันตีว่า "ตกค้าง" เสมอไม่ว่าจะรันเทสวันไหน"""
    uid = uuid.uuid4()
    sid = f"{TAG_PREFIX}10309998"
    async with AsyncSessionLocal() as db:
        db.add(User(
            id=uid, full_name="นักศึกษา ทดสอบตกค้าง", email=f"retained_{uid.hex[:6]}@cdti.ac.th",
            password_hash=hash_password("Test1234!"), role="student", student_id=sid,
            email_verified=True, is_active=True, enrollment_year=2500, study_years=4,
        ))
        await db.commit()
    yield uid
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Notification).where(Notification.user_id == uid))
        await db.execute(delete(AuthToken).where(AuthToken.user_id == uid))
        await db.execute(delete(AuditLog).where(AuditLog.actor_id == uid))
        await db.execute(delete(AuditLog).where(AuditLog.target_id == uid))
        await db.execute(delete(User).where(User.id == uid))
        await db.commit()


async def _find_in_users_pages(client: AsyncClient, headers: dict, uid, **params) -> dict | None:
    """ไล่ทุกหน้าของ GET /users จนกว่าจะเจอ id ที่ต้องการหรือหมด total (ไม่มี ORDER BY การันตี/DB มีคนจริงปน)"""
    page = 1
    while True:
        listed = (await client.get("/users", params={**params, "page_size": 100, "page": page},
                                   headers=headers)).json()
        match = next((u for u in listed["items"] if u["id"] == str(uid)), None)
        if match is not None or page * 100 >= listed["total"]:
            return match
        page += 1


@pytest.mark.asyncio(loop_scope="session")
async def test_list_users_filters_by_year_group_retained_and_staff(
    client: AsyncClient, admin_token: str, test_admin: User, temp_retained_student,
):
    """?year_group=retained ต้องเจอนักศึกษาตกค้างแต่ไม่เจอเจ้าหน้าที่ · ?year_group=staff กลับกัน — role
    != student ต้องถือเป็นบุคลากรเสมอ ไม่ปนกับกลุ่มตกค้าง แม้จะยังมี enrollment_year ค้างอยู่ก็ตาม (MINOR 6)
    """
    headers = auth(admin_token)
    retained_uid = temp_retained_student

    in_retained = await _find_in_users_pages(client, headers, retained_uid, year_group="retained")
    assert in_retained is not None, "นักศึกษาที่ enrollment_year เก่ามากต้องอยู่ในกลุ่มตกค้าง"
    assert in_retained["is_retained"] is True

    admin_in_retained = await _find_in_users_pages(client, headers, test_admin.id, year_group="retained")
    assert admin_in_retained is None, "เจ้าหน้าที่ต้องไม่โผล่ในกลุ่มตกค้าง"

    admin_in_staff = await _find_in_users_pages(client, headers, test_admin.id, year_group="staff")
    assert admin_in_staff is not None, "เจ้าหน้าที่ต้องอยู่ในกลุ่มบุคลากร"

    retained_in_staff = await _find_in_users_pages(client, headers, retained_uid, year_group="staff")
    assert retained_in_staff is None, "นักศึกษาต้องไม่โผล่ในกลุ่มบุคลากร แม้จะตกค้างก็ตาม"


# ── Dashboard การ์ดชั้นปีต้องไม่ทิ้งกลุ่มนอกช่วง 1-4 (MINOR-2 รีวิวรอบ 3) ─────────

@pytest_asyncio.fixture(loop_scope="session")
async def temp_wide_study_years_student():
    """จำลองข้อมูลเก่า/ผิดปกติที่ study_years > 4 (ก่อนจำกัดช่วง 2-4 ที่ schema — ดู CLAUDE.md) จนได้ชั้นปี
    ที่ไม่อยู่ในช่วง 1-4 ปกติ แต่ก็ยังไม่ "ตกค้าง" ตามนิยาม (level <= study_years) — สร้างตรงผ่าน ORM
    ข้าม endpoint สมัคร/แก้ไขที่ถูกจำกัดช่วงแล้วโดยตั้งใจ เพื่อทดสอบว่า dashboard ยังนับครบแม้เจอแถวแบบนี้
    """
    start = await _current_academic_year_start()
    ay = academic_year(date.today(), start)
    uid = uuid.uuid4()
    sid = f"{TAG_PREFIX}10309000"
    async with AsyncSessionLocal() as db:
        db.add(User(
            id=uid, full_name="นักศึกษา ทดสอบ study_years กว้าง", email=f"wide_{uid.hex[:6]}@cdti.ac.th",
            password_hash=hash_password("Test1234!"), role="student", student_id=sid,
            email_verified=True, is_active=True, enrollment_year=ay - 5, study_years=10,
        ))
        await db.commit()
    yield uid
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Notification).where(Notification.user_id == uid))
        await db.execute(delete(AuthToken).where(AuthToken.user_id == uid))
        await db.execute(delete(AuditLog).where(AuditLog.actor_id == uid))
        await db.execute(delete(AuditLog).where(AuditLog.target_id == uid))
        await db.execute(delete(User).where(User.id == uid))
        await db.commit()


@pytest.mark.asyncio(loop_scope="session")
async def test_dashboard_year_buckets_do_not_drop_out_of_range_levels(
    client: AsyncClient, admin_token: str, temp_wide_study_years_student,
):
    """ชั้นปี 6 (ไม่ตกค้างเพราะ study_years=10) ต้องไม่ถูก YEAR_GROUP_ORDER (มีแค่ "1".."4"/retained/staff/
    unknown) ทิ้งเงียบ ๆ — ผลรวมทุกการ์ดชั้นปีต้องเท่ากับ users_total เสมอ (invariant ที่พังได้ถ้ามีการ fold
    ที่ตกหล่นแม้แค่คนเดียว ไม่ต้องพึ่งเลขที่ต้องรันในสภาพ DB ว่างเปล่า)
    """
    r = await client.get("/dashboard/summary", headers=auth(admin_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert sum(g["count"] for g in body["users_by_year"]) == body["users_total"]
