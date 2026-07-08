"""Test อัปโหลดรูปโปรไฟล์ของผู้ใช้เอง (#2)"""
import os

from httpx import AsyncClient

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.user import User
from tests.conftest import auth

# PNG 1x1 เล็กสุด (valid header) พอให้ save_image รับได้
_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


async def test_upload_avatar_sets_url(client: AsyncClient, student_token: str, test_student: User):
    r = await client.post(
        "/users/me/avatar",
        headers=auth(student_token),
        files={"file": ("me.png", _PNG, "image/png")},
    )
    assert r.status_code == 200, r.text
    avatar_url = r.json()["avatar_url"]
    assert avatar_url and avatar_url.startswith("/uploads/")
    # /users/me ต้องคืน avatar เดียวกัน
    me = await client.get("/users/me", headers=auth(student_token))
    assert me.json()["avatar_url"] == avatar_url

    # cleanup: ลบไฟล์ที่เขียนจริง + reset field
    fpath = os.path.join(settings.UPLOAD_DIR, os.path.basename(avatar_url))
    if os.path.exists(fpath):
        os.remove(fpath)
    async with AsyncSessionLocal() as db:
        u = await db.get(User, test_student.id)
        u.avatar_url = None
        await db.commit()


async def test_upload_avatar_rejects_non_image(client: AsyncClient, student_token: str):
    r = await client.post(
        "/users/me/avatar",
        headers=auth(student_token),
        files={"file": ("evil.txt", b"not an image", "text/plain")},
    )
    assert r.status_code == 400
