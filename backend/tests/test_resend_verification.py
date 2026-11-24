"""POST /auth/resend-verification — แก้อีเมลที่พิมพ์ผิดตอนสมัคร / ส่งลิงก์ยืนยันใหม่ (feedback 16 พ.ย. 69)"""
import random
import uuid

from httpx import AsyncClient
from sqlalchemy import delete, select, update

from app.core.database import AsyncSessionLocal
from app.models.auth_token import AuthToken
from app.models.user import User
from tests.conftest import _delete_user_cascade

PW = "Test1234!"


async def _register(client: AsyncClient) -> tuple[str, str]:
    sid = f"65{random.randint(0, 10 ** 8 - 1):08d}"
    email = f"resend_{uuid.uuid4().hex[:8]}@cdti.ac.th"
    r = await client.post("/auth/register", json={
        "full_name": "นาย ทดสอบ ส่งใหม่", "student_id": sid, "email": email,
        "phone": "0812345678", "password": PW, "major": "comp_eng", "pdpa_consent": True,
    })
    assert r.status_code == 201, r.text
    # dev อาจเปิด DEV_AUTO_VERIFY_EMAIL — บังคับให้เป็นบัญชียังไม่ยืนยันเสมอ
    async with AsyncSessionLocal() as db:
        await db.execute(update(User).where(User.student_id == sid).values(email_verified=False))
        await db.commit()
    return sid, email


async def _cleanup(sid: str) -> None:
    async with AsyncSessionLocal() as db:
        uid = (await db.execute(select(User.id).where(User.student_id == sid))).scalar_one_or_none()
        if uid is None:
            return
        await db.execute(delete(AuthToken).where(AuthToken.user_id == uid))
        await db.commit()
    await _delete_user_cascade(uid)


async def test_resend_changes_email_and_invalidates_old_link(client: AsyncClient):
    sid, email = await _register(client)
    try:
        async with AsyncSessionLocal() as db:
            uid = (await db.execute(select(User.id).where(User.student_id == sid))).scalar_one()
            old_tokens = (await db.execute(select(AuthToken.token).where(AuthToken.user_id == uid))).scalars().all()

        new_email = f"fixed_{uuid.uuid4().hex[:8]}@CDTI.ac.th"
        r = await client.post("/auth/resend-verification",
                              json={"identifier": sid, "password": PW, "new_email": new_email})
        assert r.status_code == 200, r.text
        assert r.json()["email"] == new_email.lower()

        async with AsyncSessionLocal() as db:
            user = (await db.execute(select(User).where(User.id == uid))).scalar_one()
            assert user.email == new_email.lower()
            tokens = (await db.execute(select(AuthToken.token).where(AuthToken.user_id == uid))).scalars().all()
        assert len(tokens) == 1 and tokens[0] not in old_tokens  # ลิงก์เก่าที่ส่งไปอีเมลผิดใช้ไม่ได้แล้ว

        # ลิงก์ใหม่ยืนยันได้ แล้วเรียกซ้ำต้องโดนปฏิเสธ (อีเมลที่ยืนยันแล้วห้ามย้ายทางนี้)
        r = await client.post("/auth/verify-email", json={"token": tokens[0]})
        assert r.status_code == 200, r.text
        r = await client.post("/auth/resend-verification",
                              json={"identifier": sid, "password": PW, "new_email": email})
        assert r.status_code == 400, r.text
    finally:
        await _cleanup(sid)


async def test_resend_rejects_wrong_password_bad_domain_and_taken_email(client: AsyncClient):
    sid, email = await _register(client)
    sid2, email2 = await _register(client)
    try:
        r = await client.post("/auth/resend-verification", json={"identifier": sid, "password": "wrong-pass"})
        assert r.status_code == 401
        r = await client.post("/auth/resend-verification",
                              json={"identifier": sid, "password": PW, "new_email": "x@gmail.com"})
        assert r.status_code == 400
        r = await client.post("/auth/resend-verification",
                              json={"identifier": sid, "password": PW, "new_email": email2})
        assert r.status_code == 409
        # ไม่ส่งอีเมลใหม่ = ส่งไปที่เดิม
        r = await client.post("/auth/resend-verification", json={"identifier": sid, "password": PW})
        assert r.status_code == 200 and r.json()["email"] == email
    finally:
        await _cleanup(sid)
        await _cleanup(sid2)
