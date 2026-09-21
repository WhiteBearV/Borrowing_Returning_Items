"""รายชื่อนักศึกษาที่สาขารับรอง + คิวอนุมัติผู้สมัคร (เฟส 9 — feedback อาจารย์ ข้อ 3)

โจทย์: "ตอนนี้กันได้แค่โดเมนอีเมล ใครมีเมล cdti ก็เลือกสาขามั่วได้"
สิ่งที่ต้องไม่พัง:
- อ่านไฟล์รายชื่อได้ทั้ง .xls (ของจริงจากสำนักทะเบียน) / .xlsx / .csv / .pdf และได้สาขาจาก **หัวกระดาษ**
- สมัครด้วยรหัสที่อยู่ในรายชื่อ → ผ่านทันที และ **สาขา/ชื่อ ถูกทับด้วยค่าจากรายชื่อ**
- ไม่อยู่ในรายชื่อ/ชื่อไม่ตรง → ไม่ปิดตาย แต่เข้าคิวรออนุมัติ ล็อกอินยังไม่ได้จนกว่าแอดมินจะกดอนุมัติ
"""
import csv
import io
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, or_, select

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.auth_token import AuthToken
from app.models.eligible_student import EligibleStudent
from app.models.notification import Notification
from app.models.user import User
from app.services import student_import_service
from tests.conftest import auth

# หน้าตาไฟล์จริง: หัวกระดาษ 3 บรรทัด แล้วค่อยหัวตาราง (เซลล์ว่างคั่นเยอะเหมือนของจริง)
CSV_ROWS = [
    ["", "", "", "", "", "สถาบันเทคโนโลยีจิตรลดา", "", "", "รายชื่อนักศึกษาในที่ปรึกษา"],
    ["", "คณะ", "", "", "", "เทคโนโลยีดิจิทัล"],
    ["", "สาขาวิชา", "", "", "", "วิศวกรรมคอมพิวเตอร์", "", "", "", "", "", "รุ่น 631 หมู่เรียน วค."],
    ["", "อาจารย์ที่ปรึกษา", "", "", "", "สุมาลี อุณหวณิชย์ , กฤษฎา พรหมสุทธิรักษ์"],
    ["ที่", "", "", "รหัสนักศึกษา", "", "", "", "ชื่อ-นามสกุล", "", "สถานะ"],
]


def _csv_bytes(students: list[tuple[str, str]]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    for row in CSV_ROWS:
        writer.writerow(row)
    for i, (sid, name) in enumerate(students, 1):
        writer.writerow([str(i), "", "", sid, "", "", "", name, "", "11"])
    return buf.getvalue().encode("utf-8-sig")


@pytest_asyncio.fixture(loop_scope="session")
async def clean_eligible():
    """คืน list ว่างให้เทสเติม student_id ที่ตัวเองสร้าง/นำเข้าเข้ามาเอง — ลบเฉพาะรหัสที่อยู่ใน list นี้เป๊ะ
    ตอน teardown (แก้ตามรีวิวรอบ 4, M-i: เดิมใช้ `LIKE '99%'` กวาดทั้งช่วงรหัส เสี่ยงชน/ลบข้อมูลจริงหรือของ
    เทสไฟล์อื่นที่บังเอิญใช้ prefix เดียวกันพร้อมกัน — ตอนนี้ลบด้วย `.in_(student_ids)` ที่เทสระบุเองเป๊ะแทน)

    started ถ่ายก่อนตัวเทสเริ่มทำงานจริง (fixture setup ก่อน yield) — ใช้ scope การลบแจ้งเตือนที่ปกติไม่ผูก
    กับ user_id/target_id ของบัญชีทดสอบเลย (ตามกฎ CLAUDE.md ห้ามลบ log ด้วย target_id/actor_id ของแอดมิน
    จริงเพียว ๆ เพราะจะลบ log จริงของคนอื่นที่ใช้แอดมินคนเดียวกันไปด้วย):
    - "registration_pending" ที่ /auth/register ส่งไปหา staff จริงทุกคน (ข้อความมีรหัสนักศึกษาฝังอยู่
      ไม่ได้อยู่ใต้ user_id ของผู้สมัคร) — กรองเฉพาะข้อความที่มี student_id ที่เทสนี้สร้างจริงเป๊ะ (exact
      match ต่อรหัส ไม่ใช่ LIKE prefix กว้าง ๆ)
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
            # token ยืนยันอีเมลที่สร้างตอนสมัคร ชี้กลับมาที่ user — ต้องลบก่อน ไม่งั้นชน FK
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


def test_parse_real_registrar_xls_file():
    """ไฟล์ .xls ตัวจริงจากสำนักทะเบียน — ต้องได้ทั้งรายชื่อและสาขา/รุ่น/อาจารย์จากหัวกระดาษ"""
    import os
    path = "/home/maeb/Downloads/repofficeradvisor.xls"
    if not os.path.exists(path):
        pytest.skip("ไม่มีไฟล์ตัวอย่างจากสำนักทะเบียนบนเครื่องนี้")
    parsed = student_import_service.parse_file(path, "repofficeradvisor.xls")
    assert parsed.major == "comp_eng", parsed.major_raw
    assert parsed.faculty == "เทคโนโลยีดิจิทัล"
    assert "631" in (parsed.generation or "")
    assert parsed.advisor and "สุมาลี" in parsed.advisor
    assert len(parsed.rows) == 3
    assert parsed.rows[0] == {"student_id": "6310301030", "full_name": "ธนพัฒน์ สุขทิพย์กิจ",
                              "status_code": "12"}


def test_parse_csv_and_name_normalisation():
    parsed = student_import_service.read_upload(
        _csv_bytes([("9910301001", "ทดสอบ ระบบหนึ่ง")]), "list.csv")
    assert parsed.major == "comp_eng"
    assert parsed.rows[0]["student_id"] == "9910301001"
    # ชื่อที่พิมพ์เว้นวรรคไม่เหมือนกัน/มีคำนำหน้า ต้องถือว่าเป็นคนเดียวกัน
    n = student_import_service.normalize_name
    assert n("นาย ธนพัฒน์  สุขทิพย์กิจ") == n("ธนพัฒน์ สุขทิพย์กิจ")
    assert n("ธนพัฒน์ สุขทิพย์กิจ") != n("ธนพัฒน์ สุขทิพย์กิจจ")


def test_parse_pdf_text_layer():
    """ไฟล์ PDF ที่ export มาจากระบบ (มี text layer) ต้องอ่านตรงได้โดยไม่ต้องพึ่ง OCR"""
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.setFont("Helvetica", 12)
    for i, line in enumerate([
        "faculty report", "student list",
        "1. 9910301001 Test Student One 11",
        "2. 9910301002 Test Student Two 11",
    ]):
        c.drawString(60, 750 - i * 20, line)
    c.showPage()
    c.save()
    parsed = student_import_service.read_upload(buf.getvalue(), "list.pdf")
    assert [r["student_id"] for r in parsed.rows] == ["9910301001", "9910301002"]
    assert parsed.rows[0]["full_name"] == "Test Student One"


@pytest.mark.asyncio(loop_scope="session")
async def test_import_is_additive_and_updates_by_student_id(
    client: AsyncClient, admin_token: str, clean_eligible,
):
    """นำเข้าไฟล์ของอาจารย์คนที่สองต้องไม่ลบรายชื่อของคนแรก และชื่อที่แก้แล้วต้องอัปเดตทับ"""
    clean_eligible.extend(["9910301001", "9910301002"])
    first = await client.post("/eligible-students/import", headers=auth(admin_token),
                              files={"file": ("a.csv", _csv_bytes([("9910301001", "ทดสอบ ระบบหนึ่ง")]),
                                              "text/csv")})
    assert first.status_code == 200, first.text
    assert first.json()["added"] == 1 and first.json()["major"] == "comp_eng"

    second = await client.post("/eligible-students/import", headers=auth(admin_token),
                               files={"file": ("b.csv", _csv_bytes([
                                   ("9910301001", "ทดสอบ ระบบหนึ่งแก้ชื่อ"),
                                   ("9910301002", "ทดสอบ ระบบสอง")]), "text/csv")})
    assert second.status_code == 200, second.text
    assert second.json() == {**second.json(), "added": 1, "updated": 1, "total": 2}

    listed = (await client.get("/eligible-students", params={"search": "99103010"},
                               headers=auth(admin_token))).json()
    assert listed["total"] == 2
    names = {r["student_id"]: r["full_name"] for r in listed["items"]}
    assert names["9910301001"] == "ทดสอบ ระบบหนึ่งแก้ชื่อ"
    assert all(r["has_account"] is False for r in listed["items"])


@pytest.mark.asyncio(loop_scope="session")
async def test_register_uses_list_as_source_of_truth(
    client: AsyncClient, admin_token: str, clean_eligible,
):
    """อยู่ในรายชื่อ + ชื่อตรง → ผ่านทันที และสาขาถูกทับด้วยค่าจากรายชื่อแม้ผู้สมัครเลือกมาผิด"""
    clean_eligible.append("9910301003")
    await client.post("/eligible-students/import", headers=auth(admin_token),
                      files={"file": ("a.csv", _csv_bytes([("9910301003", "ทดสอบ ระบบสาม")]), "text/csv")})

    r = await client.post("/auth/register", json={
        "full_name": "นาย ทดสอบ  ระบบสาม", "student_id": "9910301003",
        "email": f"stu{uuid.uuid4().hex[:6]}@student.cdti.ac.th",
        "password": "Test1234!", "major": "digital_design", "phone": "0812345678", "pdpa_consent": True,
    })
    assert r.status_code in (200, 201), r.text

    async with AsyncSessionLocal() as db:
        user = (await db.execute(
            select(User).where(User.student_id == "9910301003"))).scalar_one()
        assert user.approval_status == "approved"
        assert user.major == "comp_eng", "สาขาต้องมาจากรายชื่อ ไม่ใช่ที่ผู้สมัครเลือก"
        assert user.full_name == "ทดสอบ ระบบสาม", "ชื่อต้องใช้ตามทะเบียน"


@pytest.mark.asyncio(loop_scope="session")
async def test_unknown_student_goes_to_approval_queue(
    client: AsyncClient, admin_token: str, clean_eligible,
):
    """ไม่อยู่ในรายชื่อ → สมัครได้แต่ล็อกอินไม่ได้จนกว่าแอดมินจะอนุมัติ (ไม่ปิดตาย)"""
    clean_eligible.append("9910309999")
    email = f"stu{uuid.uuid4().hex[:6]}@student.cdti.ac.th"
    r = await client.post("/auth/register", json={
        "full_name": "ทดสอบ ไม่อยู่ในรายชื่อ", "student_id": "9910309999",
        "email": email, "password": "Test1234!", "major": "comp_eng", "phone": "0812345678", "pdpa_consent": True,
    })
    assert r.status_code in (200, 201), r.text

    async with AsyncSessionLocal() as db:
        user = (await db.execute(
            select(User).where(User.student_id == "9910309999"))).scalar_one()
        assert user.approval_status == "pending"
        assert "ไม่พบรหัสนักศึกษา" in (user.approval_note or "")
        user.email_verified = True  # ตัดเรื่องยืนยันอีเมลออก ให้เหลือทดสอบเฉพาะด่านอนุมัติ
        await db.commit()
        user_id = user.id

    blocked = await client.post("/auth/login", json={"identifier": email, "password": "Test1234!"})
    assert blocked.status_code == 403 and "รอเจ้าหน้าที่อนุมัติ" in blocked.json()["detail"]

    # แอดมินเห็นคิวและกดอนุมัติได้
    queue = (await client.get("/users", params={"approval_status": "pending"},
                              headers=auth(admin_token))).json()
    assert any(u["id"] == str(user_id) for u in queue["items"])

    ok = await client.patch(f"/users/{user_id}/approval", headers=auth(admin_token),
                            json={"approve": True, "note": "ยืนยันกับสาขาแล้ว"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["approval_status"] == "approved"
    assert (await client.post("/auth/login",
                              json={"identifier": email, "password": "Test1234!"})).status_code == 200


@pytest.mark.asyncio(loop_scope="session")
async def test_name_mismatch_also_queues(client: AsyncClient, admin_token: str, clean_eligible):
    """รหัสตรงแต่ชื่อคนละคน = สัญญาณของการสวมรหัส → ต้องเข้าคิวให้คนตรวจ ไม่ผ่านอัตโนมัติ"""
    clean_eligible.append("9910301004")
    await client.post("/eligible-students/import", headers=auth(admin_token),
                      files={"file": ("a.csv", _csv_bytes([("9910301004", "ทดสอบ ระบบสี่")]), "text/csv")})
    r = await client.post("/auth/register", json={
        "full_name": "คนอื่น ไม่ใช่เจ้าของรหัส", "student_id": "9910301004",
        "email": f"stu{uuid.uuid4().hex[:6]}@student.cdti.ac.th",
        "password": "Test1234!", "major": "comp_eng", "phone": "0812345678", "pdpa_consent": True,
    })
    assert r.status_code in (200, 201), r.text
    async with AsyncSessionLocal() as db:
        user = (await db.execute(
            select(User).where(User.student_id == "9910301004"))).scalar_one()
        assert user.approval_status == "pending"
        assert "ชื่อไม่ตรง" in (user.approval_note or "")


@pytest.mark.asyncio(loop_scope="session")
async def test_import_requires_staff_and_rejects_junk_file(
    client: AsyncClient, admin_token: str, student_token: str,
):
    assert (await client.get("/eligible-students", headers=auth(student_token))).status_code == 403
    bad = await client.post("/eligible-students/import", headers=auth(admin_token),
                            files={"file": ("notes.txt", b"hello", "text/plain")})
    assert bad.status_code == 400
    empty = await client.post("/eligible-students/import", headers=auth(admin_token),
                              files={"file": ("empty.csv", b"a,b,c\n1,2,3\n", "text/csv")})
    assert empty.status_code == 400


@pytest.mark.asyncio(loop_scope="session")
async def test_filter_by_cohort(client: AsyncClient, admin_token: str, clean_eligible):
    """กรองตามรุ่น (2 หลักแรกของรหัส) + นับจำนวนต่อรุ่นของทั้งตาราง ให้หน้าเว็บทำปุ่มกรองจากรุ่นที่มีจริง"""
    clean_eligible.extend(["9810301001", "9910301003"])
    h = auth(admin_token)
    r = await client.post("/eligible-students/import", headers=h, files={"file": ("c.csv", _csv_bytes([
        ("9810301001", "ทดสอบ รุ่นเก้าแปด"), ("9910301003", "ทดสอบ รุ่นเก้าเก้า")]), "text/csv")})
    assert r.status_code == 200, r.text

    listed = (await client.get("/eligible-students", params={"cohort": "98", "search": "ทดสอบ รุ่นเก้า"},
                               headers=h)).json()
    assert [row["student_id"] for row in listed["items"]] == ["9810301001"]
    assert listed["cohorts"]["98"] >= 1 and listed["cohorts"]["99"] >= 1  # นับทั้งตาราง ไม่สนตัวกรอง
    assert (await client.get("/eligible-students", params={"cohort": "9"}, headers=h)).status_code == 422
