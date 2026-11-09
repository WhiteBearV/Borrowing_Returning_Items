"""ช่องค้นหาหน้าจัดการผู้ใช้ — GET /users?q= ค้นชื่อ / รหัส / อีเมล (cleanup ใน finally เพราะรันใส่ DB dev จริง)"""
import uuid

from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.user import User
from tests.conftest import auth


async def test_search_users_by_name_code_email(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    tag = uuid.uuid4().hex[:6]
    email = f"srch_{tag}@cdti.ac.th"
    uname = f"S{tag.upper()}"
    try:
        r = await client.post("/users", json={
            "email": email, "full_name": f"ค้นหา ทดสอบ{tag}", "password": "Test1234!",
            "role": "admin", "username": uname,
        }, headers=h)
        assert r.status_code == 201, r.text
        for q in (f"ทดสอบ{tag}", uname.lower(), f"SRCH_{tag}".upper()):  # ชื่อ / รหัส / อีเมล ไม่สนตัวพิมพ์
            res = (await client.get("/users", params={"q": q}, headers=h)).json()
            assert [u["email"] for u in res["items"]] == [email], q
        assert (await client.get("/users", params={"q": f"ไม่มีแน่{tag}"}, headers=h)).json()["total"] == 0
    finally:
        async with AsyncSessionLocal() as db:
            uid = (await db.execute(select(User.id).where(User.email == email))).scalar()
            if uid:
                await db.execute(delete(AuditLog).where(AuditLog.target_id == uid))
            await db.execute(delete(User).where(User.email == email))
            await db.commit()
