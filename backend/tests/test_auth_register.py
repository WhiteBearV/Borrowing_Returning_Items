"""Tests: trim + normalize student_id ก่อน validate (RegisterRequest / UserCreateRequest)

Bug เดิม (A3): RegisterPage.jsx ส่ง student_id แบบไม่ trim — เผลอมี space ต่อท้าย (เช่น autofill/มือถือ)
แล้วชน pattern \\d{10} ล่ม 422 แบบงงๆ (เลขที่กรอกดูถูกต้องทุกตัว) ซ้ำร้ายฝั่ง frontend catch block เดิม
สมมติว่า detail เป็น string เสมอ ทำให้ error array (Pydantic validation error) render พังหรือว่างเปล่า
แก้ที่ schema: strip whitespace ก่อนตรวจ pattern ทั้ง RegisterRequest และ UserCreateRequest
(ตัวหลังเดิมไม่มี pattern เลย — แอดมินเพิ่มผู้ใช้ผ่านฟอร์มนี้ตั้ง student_id เป็นอะไรก็ได้)
"""
import random
import uuid

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.auth_token import AuthToken
from app.models.user import User
from app.schemas.auth import RegisterRequest
from app.schemas.user import UserCreateRequest
from tests.conftest import _delete_user_cascade, auth


def _random_student_id() -> str:
    """เลขนักศึกษาทดสอบ 10 หลักล้วน — ต้องเป็นตัวเลขจริงเท่านั้น (uuid().hex มี a-f ปนจะไม่ผ่าน pattern)"""
    return f"65{random.randint(0, 10 ** 8 - 1):08d}"


# ── schema-level: RegisterRequest ───────────────────────────────────────────

def test_register_request_strips_trailing_whitespace():
    req = RegisterRequest(
        full_name="นาย ทดสอบ", student_id="6512345678 ", email="test@cdti.ac.th",
        password="Test1234!", major="comp_eng",
    )
    assert req.student_id == "6512345678"


def test_register_request_strips_leading_whitespace():
    req = RegisterRequest(
        full_name="นาย ทดสอบ", student_id=" 6512345678", email="test@cdti.ac.th",
        password="Test1234!", major="comp_eng",
    )
    assert req.student_id == "6512345678"


def test_register_request_still_rejects_malformed_after_strip():
    """strip ช่วยแค่เรื่อง whitespace — เลขไม่ครบ 10 หลักยังต้อง reject เหมือนเดิม"""
    with pytest.raises(ValidationError):
        RegisterRequest(
            full_name="นาย ทดสอบ", student_id=" 65123 ", email="test@cdti.ac.th",
            password="Test1234!", major="comp_eng",
        )


# ── schema-level: UserCreateRequest (แอดมินเพิ่มผู้ใช้) ──────────────────────

def test_user_create_request_now_validates_pattern():
    """เดิม UserCreateRequest.student_id ไม่มี pattern เลย — ตอนนี้ต้อง reject รูปแบบผิด"""
    with pytest.raises(ValidationError):
        UserCreateRequest(
            email="admin-add@cdti.ac.th", full_name="ผู้ใช้ทดสอบ",
            password="Test1234!", student_id="abc",
        )


def test_user_create_request_strips_and_accepts_valid():
    body = UserCreateRequest(
        email="admin-add@cdti.ac.th", full_name="ผู้ใช้ทดสอบ",
        password="Test1234!", student_id=" 6512345678 ",
    )
    assert body.student_id == "6512345678"


def test_user_create_request_student_id_still_optional():
    """student_id เป็น None ได้เหมือนเดิม (บัญชีอาจารย์/เจ้าหน้าที่ไม่มีรหัสนักศึกษา)"""
    body = UserCreateRequest(email="admin-add2@cdti.ac.th", full_name="อาจารย์ ทดสอบ", password="Test1234!")
    assert body.student_id is None


# ── endpoint-level: POST /auth/register ─────────────────────────────────────

async def test_register_endpoint_accepts_and_trims_whitespace_student_id(client: AsyncClient):
    email = f"regtest_{uuid.uuid4().hex[:8]}@cdti.ac.th"
    sid = _random_student_id()
    r = await client.post("/auth/register", json={
        "full_name": "นาย ทดสอบ Whitespace",
        "student_id": f"  {sid}  ",
        "email": email,
        "password": "Test1234!",
        "major": "comp_eng",
    })
    assert r.status_code == 201, r.text

    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()
        assert user.student_id == sid  # ต้อง trim แล้ว ไม่มี space เหลือติด DB
        uid = user.id
        # /auth/register สร้าง auth_tokens แถวยืนยันอีเมลด้วย — _delete_user_cascade (conftest) ไม่ได้ลบตารางนี้
        # ต้องลบเองก่อน ไม่งั้นลบ user ไม่ได้ (FK auth_tokens_user_id_fkey ไม่มี ON DELETE CASCADE)
        await db.execute(delete(AuthToken).where(AuthToken.user_id == uid))
        await db.commit()
    await _delete_user_cascade(uid)


async def test_register_endpoint_rejects_malformed_student_id_with_array_detail(client: AsyncClient):
    """ยืนยันว่า error ตอน validation fail เป็น array (FastAPI default, ไม่มี custom handler ใน main.py)
    ฝั่ง frontend (RegisterPage.jsx) ต้องรองรับรูปแบบนี้ ไม่ใช่สมมติว่าเป็น string เสมอ"""
    r = await client.post("/auth/register", json={
        "full_name": "นาย ทดสอบ Invalid",
        "student_id": "not-a-student-id",
        "email": f"regtest_{uuid.uuid4().hex[:8]}@cdti.ac.th",
        "password": "Test1234!",
        "major": "comp_eng",
    })
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert isinstance(detail, list)
    assert any("student_id" in str(e.get("loc", [])) for e in detail)


# ── endpoint-level: POST /users (แอดมินเพิ่มผู้ใช้) ──────────────────────────

async def test_admin_create_user_rejects_malformed_student_id(client: AsyncClient, admin_token: str):
    """เดิม endpoint นี้ยอมรับ student_id รูปแบบใดก็ได้ — ตอนนี้ต้อง 422 เหมือน /auth/register"""
    r = await client.post("/users", json={
        "email": f"adduser_{uuid.uuid4().hex[:8]}@cdti.ac.th",
        "full_name": "ผู้ใช้ทดสอบ Invalid",
        "password": "Test1234!",
        "role": "student",
        "student_id": "12345",
    }, headers=auth(admin_token))
    assert r.status_code == 422


async def test_admin_create_user_trims_whitespace_student_id(client: AsyncClient, admin_token: str):
    email = f"adduser_{uuid.uuid4().hex[:8]}@cdti.ac.th"
    sid = _random_student_id()
    r = await client.post("/users", json={
        "email": email,
        "full_name": "ผู้ใช้ทดสอบ Whitespace",
        "password": "Test1234!",
        "role": "student",
        "student_id": f" {sid} ",
    }, headers=auth(admin_token))
    assert r.status_code == 201, r.text
    uid = uuid.UUID(r.json()["id"])
    assert r.json()["student_id"] == sid
    await _delete_user_cascade(uid)
