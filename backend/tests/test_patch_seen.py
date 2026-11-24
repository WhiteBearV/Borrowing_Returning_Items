"""Patch Note: กดรับทราบแล้วจำในบัญชี (ไม่ใช่ในเบราว์เซอร์)"""
from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.models.user import User
from tests.conftest import auth


async def test_patch_seen_saved_on_account(client: AsyncClient, student_token: str, test_student: User):
    try:
        r = await client.post("/users/me/patch-seen", headers=auth(student_token), json={"version": "2026.11"})
        assert r.status_code == 204, r.text
        me = await client.get("/users/me", headers=auth(student_token))
        assert me.json()["seen_patch"] == "2026.11"
        bad = await client.post("/users/me/patch-seen", headers=auth(student_token), json={"version": ""})
        assert bad.status_code == 422
    finally:
        async with AsyncSessionLocal() as db:
            u = await db.get(User, test_student.id)
            u.seen_patch = None
            await db.commit()
