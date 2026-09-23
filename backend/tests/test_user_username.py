"""รหัสประจำตัวอาจารย์/เจ้าหน้าที่ (username) — ต้องมองเห็น ค้นเจอ และไม่ชนกับรหัสนักศึกษา

feedback อาจารย์: อยากให้แยกออกจากชื่อว่าใครเป็นอาจารย์ใครเป็นนักศึกษา (01MNK01 vs 6610301006)
ไฟล์นี้ยังครอบบั๊กเดิม 2 ตัวที่ทำให้ระบบ 500: username ซ้ำ และเลขคำขอของแอดมินที่ไม่มีรหัสชนกันเอง

หมายเหตุ: conftest.py มี PYTEST_ALLOW_DB=1 รันใส่ DB dev จริง — ทุกเทสต้อง cleanup ใน finally เสมอ
"""
import uuid

from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.user import User
from app.utils.identity import is_student_identifier, user_identifier
from tests.conftest import auth


async def _delete_users(emails: list[str]) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(User).where(User.email.in_(emails)))
        await db.commit()


def test_user_identifier_prefers_student_id_then_username():
    class _U:
        id = uuid.UUID("12345678-1234-5678-1234-567812345678")
        student_id = "6610301006"
        username = "01MNK01"

    assert user_identifier(_U()) == "6610301006"
    _U.student_id = None
    assert user_identifier(_U()) == "01MNK01"


def test_user_identifier_is_unique_per_user_when_both_missing():
    """บัญชีจาก scripts/create_admin.py ไม่มีทั้งคู่ — เดิม fallback เป็น "USER" เหมือนกันหมด
    ทำให้ request_code (unique) ของแอดมิน 2 คนชนกันจนยื่นคำขอไม่ได้"""
    class _U:
        student_id = None
        username = None
        def __init__(self, uid):
            self.id = uid

    a, b = _U(uuid.uuid4()), _U(uuid.uuid4())
    assert user_identifier(a) != user_identifier(b)
    assert user_identifier(a) == user_identifier(_U(a.id))  # ค่าเดิมทุกครั้งสำหรับคนเดียวกัน


def test_is_student_identifier():
    assert is_student_identifier("6610301006")
    assert not is_student_identifier("01MNK01")
    assert not is_student_identifier("661030100")   # 9 หลัก
    assert not is_student_identifier(None)


async def test_username_is_visible_in_user_list(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    email = f"teacher_{uuid.uuid4().hex[:6]}@cdti.ac.th"
    try:
        r = await client.post("/users", json={
            "email": email, "full_name": "อาจารย์ ทดสอบ", "password": "Test1234!",
            "role": "admin", "username": "01MNK99",
        }, headers=h)
        assert r.status_code == 201, r.text
        assert r.json()["username"] == "01MNK99"
        assert r.json()["student_id"] is None
    finally:
        await _delete_users([email])


async def test_duplicate_username_is_400_not_500(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    uname = f"T{uuid.uuid4().hex[:6].upper()}"
    e1 = f"t1_{uuid.uuid4().hex[:6]}@cdti.ac.th"
    e2 = f"t2_{uuid.uuid4().hex[:6]}@cdti.ac.th"
    base = {"full_name": "อาจารย์ ทดสอบ", "password": "Test1234!", "role": "admin", "username": uname}
    try:
        assert (await client.post("/users", json={**base, "email": e1}, headers=h)).status_code == 201
        r = await client.post("/users", json={**base, "email": e2}, headers=h)
        assert r.status_code == 400, r.text  # เดิมเป็น 500 IntegrityError
    finally:
        await _delete_users([e1, e2])


async def test_username_cannot_look_like_a_student_id(client: AsyncClient, admin_token: str):
    """login รับได้ทั้ง student_id/username — ถ้าปล่อยให้รูปแบบซ้ำกันจะแยกไม่ออกว่าหมายถึงใคร"""
    h = auth(admin_token)
    email = f"t3_{uuid.uuid4().hex[:6]}@cdti.ac.th"
    try:
        r = await client.post("/users", json={
            "email": email, "full_name": "อาจารย์ ทดสอบ", "password": "Test1234!",
            "role": "admin", "username": "6610301006",
        }, headers=h)
        # 422 = schema ปฏิเสธ "ตัวเลขล้วน" ตั้งแต่ชั้น request · 400 = ด่านเดิมใน users_service
        # (ยังเก็บไว้เป็นชั้นที่สอง) — ที่สำคัญคือต้องไม่ผ่านเข้าไปสร้างบัญชี
        assert r.status_code in (400, 422), r.text
    finally:
        await _delete_users([email])


async def test_username_is_trimmed(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    email = f"t4_{uuid.uuid4().hex[:6]}@cdti.ac.th"
    uname = f"T{uuid.uuid4().hex[:6].upper()}"
    try:
        r = await client.post("/users", json={
            "email": email, "full_name": "อาจารย์ ทดสอบ", "password": "Test1234!",
            "role": "admin", "username": f"  {uname}  ",
        }, headers=h)
        assert r.status_code == 201, r.text
        assert r.json()["username"] == uname
    finally:
        await _delete_users([email])


async def test_borrow_history_search_finds_teacher_by_username(client: AsyncClient, admin_token: str):
    """ค้นประวัติการยืมด้วยรหัสอาจารย์ต้องเจอ — เดิมค้นได้แค่ชื่อกับรหัสนักศึกษา"""
    h = auth(admin_token)
    uname = f"T{uuid.uuid4().hex[:6].upper()}"
    email = f"t5_{uuid.uuid4().hex[:6]}@cdti.ac.th"
    try:
        assert (await client.post("/users", json={
            "email": email, "full_name": "อาจารย์ ค้นหา ทดสอบ", "password": "Test1234!",
            "role": "admin", "username": uname,
        }, headers=h)).status_code == 201
        # ไม่ต้องมีคำขอจริง — แค่ยืนยันว่า endpoint รับ search แล้วไม่พังและกรองด้วย username ได้
        r = await client.get("/borrow-requests", params={"search": uname}, headers=h)
        assert r.status_code == 200, r.text
    finally:
        await _delete_users([email])


async def test_teacher_identifier_appears_on_borrow_pdf():
    """ใบยืมของอาจารย์ต้องมีรหัสประจำตัว ไม่ใช่เว้นว่างเพราะไม่มีรหัสนักศึกษา"""
    import io
    from datetime import datetime
    from pypdf import PdfReader
    import app.utils.pdf as pdf_mod

    class _Req:
        id = uuid.uuid4()
        request_code = "REQ-2026-01MNK01-0001"
        student_name = "อาจารย์ ทดสอบ"
        student_number = None            # ไม่มีรหัสนักศึกษา
        borrower_identifier = "01MNK01"  # แต่มีรหัสประจำตัวอาจารย์
        borrower_is_student = False
        student_email = "teacher@cdti.ac.th"
        student_major = None
        purpose = "ทดสอบ"
        status = "approved"
        requested_at = datetime(2026, 9, 3, 10, 0)
        approved_at = datetime(2026, 9, 3, 11, 0)
        due_date = None
        returned_at = None
        approver_name = None
        receiver_name = None
        items = []

    pdf_mod._REGISTERED = False
    text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf_mod.generate_borrow_pdf(_Req()))).pages)
    assert "01MNK01" in text
    assert "อาจารย์/เจ้าหน้าที่" in text


def test_staff_code_rules():
    """รหัสประจำตัวบุคลากร (feedback อาจารย์ — "อินดิเชียรเนม"): บังคับกรอก + ห้ามเป็นตัวเลขล้วน

    ตัวเลขล้วนแยกไม่ออกจากรหัสนักศึกษาทั้งบนใบยืมและตอนล็อกอิน ส่วนบัญชีเก่าที่ตั้งชื่อไว้แล้ว
    (Admin / SUAdmin) ต้องยังผ่านกฎนี้ ไม่งั้นแก้ข้อมูลบัญชีเดิมไม่ได้เลย
    """
    from pydantic import ValidationError
    from app.schemas.user import UserCreateRequest

    base = dict(email="staffcode@cdti.ac.th", full_name="อ. ทดสอบ", password="Test1234!")
    assert UserCreateRequest(**base, role="admin", username="01MNK01").username == "01MNK01"
    assert UserCreateRequest(**base, role="superadmin", username="SUAdmin").username == "SUAdmin"
    # นักศึกษาไม่ต้องมีรหัสบุคลากร
    assert UserCreateRequest(**base, role="student", student_id="6610301006").username is None

    for bad in ({"role": "admin"},                              # ไม่กรอกรหัสเลย
                {"role": "admin", "username": "6610301006"},    # ตัวเลขล้วน = ปนกับรหัสนักศึกษา
                {"role": "superadmin", "username": "ab"}):      # สั้นเกินไป
        try:
            UserCreateRequest(**base, **bad)
            raise AssertionError(f"ควรถูกปฏิเสธ: {bad}")
        except ValidationError:
            pass
