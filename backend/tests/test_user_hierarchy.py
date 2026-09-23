"""ลำดับยศในการจัดการบัญชี (22 ก.ย. 69) — เจอจริง: ผู้ดูแลคลังปิดบัญชีผู้ดูแลระบบสูงสุดได้

endpoint จัดการผู้ใช้กั้นแค่ require_admin แต่ไม่ดูยศของบัญชีเป้าหมาย ผลคือผู้ดูแลคลัง:
ปิดบัญชี / ปฏิเสธการอนุมัติ / แก้ชั้นปี ของ superadmin ได้ และยิง API สร้างบัญชี superadmin ให้ตัวเองได้
กฎใหม่ (roles.can_manage_user): จัดการได้เฉพาะยศที่ต่ำกว่า · สร้างได้ไม่เกินยศตัวเอง · ห้ามปิดตัวเอง
หมายเหตุ: PYTEST_ALLOW_DB=1 รันใส่ DB dev จริง — ลบทุกบัญชีที่สร้าง + audit ของมันใน finally
"""
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.user import User
from tests.conftest import auth
from tests.test_roles_and_change_requests import _cleanup_users, _make_user


async def test_admin_cannot_manage_same_or_higher_rank(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    boss, peer, student = await _make_user("superadmin"), await _make_user("admin"), await _make_user("student")
    try:
        for target in (boss, peer):
            r = await client.patch(f"/users/{target.id}/status", headers=h, json={"is_active": False})
            assert r.status_code == 403, f"{target.role}: {r.text}"
            r = await client.patch(f"/users/{target.id}/approval", headers=h, json={"approve": False, "note": "x"})
            assert r.status_code == 403, f"{target.role}: {r.text}"
            r = await client.patch(f"/users/{target.id}/study", headers=h, json={"study_years": 4, "reason": "x"})
            assert r.status_code == 403, f"{target.role}: {r.text}"
        async with AsyncSessionLocal() as db:
            for target in (boss, peer):
                row = await db.get(User, target.id)
                assert (row.is_active, row.approval_status) == (True, "approved")   # ไม่ถูกแตะเลย

        # ยศต่ำกว่า (ผู้ใช้งาน) ยังจัดการได้ตามปกติ
        r = await client.patch(f"/users/{student.id}/status", headers=h, json={"is_active": False})
        assert r.status_code == 200 and r.json()["is_active"] is False
    finally:
        await _cleanup_users(boss.id, peer.id, student.id)


async def test_admin_cannot_create_superadmin(client: AsyncClient, admin_token: str):
    """เดิมหน้าเว็บไม่มีตัวเลือกนี้ แต่ยิง API ตรง ๆ ได้ = ผู้ดูแลคลังยกระดับตัวเองเป็น superadmin"""
    h = auth(admin_token)
    base = {"full_name": "ทดสอบ ลำดับยศ", "password": "Test1234!"}
    emails = ["hier_super@cdti.ac.th", "hier_admin@cdti.ac.th"]
    try:
        # ส่ง username ที่ถูกรูปแบบมาด้วย ไม่งั้นจะโดน schema เตะที่ 422 ก่อน แล้วเทสนี้จะผ่านโดยไม่ได้
        # พิสูจน์เรื่องลำดับยศเลย (บัญชีที่ไม่ใช่นักศึกษาต้องมีรหัสประจำตัวเสมอ — ดู UserCreateRequest)
        r = await client.post("/users", headers=h, json={**base, "email": emails[0], "role": "superadmin",
                                                          "username": "hier_super"})
        assert r.status_code == 403, r.text
        # สร้างบัญชียศเดียวกับตัวเอง (ผู้ดูแลคลัง) ยังทำได้เหมือนเดิม — หน้าเว็บมีปุ่มนี้อยู่
        r = await client.post("/users", headers=h, json={**base, "email": emails[1], "role": "admin",
                                                          "username": "hier_admin"})
        assert r.status_code == 201, r.text
    finally:
        async with AsyncSessionLocal() as db:
            ids = (await db.execute(select(User.id).where(User.email.in_(emails)))).scalars().all()
        await _cleanup_users(*ids)


async def test_approval_only_for_student_accounts(client: AsyncClient, superadmin_token: str):
    """คิวอนุมัติมีไว้สำหรับผู้สมัคร — "ปฏิเสธ" บัญชีเจ้าหน้าที่ = ล็อกเอาต์เขาทางอ้อม แม้คนกดเป็น superadmin"""
    staff = await _make_user("admin")
    try:
        r = await client.patch(f"/users/{staff.id}/approval", headers=auth(superadmin_token),
                               json={"approve": False, "note": "x"})
        assert r.status_code == 400, r.text
    finally:
        await _cleanup_users(staff.id)


async def test_cannot_deactivate_self(client: AsyncClient, superadmin_token: str, test_superadmin: User):
    r = await client.patch(f"/users/{test_superadmin.id}/status", headers=auth(superadmin_token),
                           json={"is_active": False})
    assert r.status_code == 400, r.text
