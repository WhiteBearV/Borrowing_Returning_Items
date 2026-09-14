"""เฟส 2 (feedback อาจารย์ 5 ก.ย. 69) — 3 ระดับสิทธิ์ + คิวคำขอแก้ไขข้อมูล

หมายเหตุ: conftest.py มี PYTEST_ALLOW_DB=1 รันใส่ DB dev จริง — ทุกเทสต้อง cleanup ใน finally เสมอ
"""
import uuid

from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token, hash_password
from app.models.audit_log import AuditLog
from app.models.change_request import ChangeRequest
from app.models.user import User
from tests.conftest import auth


async def _make_user(role: str) -> User:
    uid = uuid.uuid4()
    async with AsyncSessionLocal() as db:
        user = User(
            id=uid, full_name=f"ทดสอบสิทธิ์ {role}",
            email=f"roletest_{uid.hex[:6]}@cdti.ac.th",
            password_hash=hash_password("Test1234!"),
            role=role, email_verified=True, is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


async def _cleanup_users(*ids: uuid.UUID) -> None:
    async with AsyncSessionLocal() as db:
        for uid in ids:
            await db.execute(delete(AuditLog).where(AuditLog.actor_id == uid))
            await db.execute(delete(AuditLog).where(AuditLog.target_id == uid))
            await db.execute(delete(User).where(User.id == uid))
        await db.commit()


async def _cleanup_change_requests(*ids: uuid.UUID) -> None:
    async with AsyncSessionLocal() as db:
        for cid in ids:
            await db.execute(delete(AuditLog).where(AuditLog.target_id == cid))
            await db.execute(delete(ChangeRequest).where(ChangeRequest.id == cid))
        await db.commit()


async def test_superadmin_inherits_all_admin_permissions(client: AsyncClient, superadmin_token: str):
    """สิทธิ์ต้องเป็นชั้น ไม่ใช่แยกขา — superadmin ต้องทำทุกอย่างที่ผู้ดูแลคลังทำได้"""
    h = auth(superadmin_token)
    for path in ("/equipment", "/borrow-requests", "/audit-logs", "/dashboard/summary", "/users"):
        r = await client.get(path, headers=h)
        assert r.status_code == 200, f"{path} -> {r.status_code} {r.text}"


async def test_restricted_endpoints_reject_plain_admin(client: AsyncClient, admin_token: str):
    """endpoint ที่ยังเป็นของผู้ดูแลระบบสูงสุด ต้องปฏิเสธผู้ดูแลคลัง (403 ไม่ใช่ 200/500)

    ปรับตามที่ตกลงกับผู้ใช้ 8 ก.ย. 69: settings กลุ่มงานประจำ (นัดรับ/แจ้งเตือน/โควต้า) และการลบอุปกรณ์
    ถาวร **ย้ายมาให้ผู้ดูแลคลังทำได้** เพราะเป็นงานเติม/เคลียร์คลังประจำวัน — ที่เหลือยังกันไว้เหมือนเดิม
    """
    h = auth(admin_token)
    victim = await _make_user("student")
    try:
        # ค่าที่เกี่ยวกับเงิน/ตัวเลขย้อนหลัง ยังเป็นของ superadmin
        assert (await client.patch("/settings/fine_per_day_per_item", headers=h,
                                   json={"value": "10"})).status_code == 403
        assert (await client.patch("/settings/pdf_value_source", headers=h,
                                   json={"value": "book"})).status_code == 403
        assert (await client.delete(f"/users/{victim.id}", headers=h)).status_code == 403
        assert (await client.patch(f"/users/{victim.id}/role", headers=h,
                                   json={"role": "admin"})).status_code == 403
        assert (await client.get("/change-requests/system-check", headers=h)).status_code == 403
    finally:
        await _cleanup_users(victim.id)


async def test_admin_can_edit_operational_settings(client: AsyncClient, admin_token: str):
    """ค่ากลุ่มงานประจำ (นัดรับ/แจ้งเตือน/โควต้า) ผู้ดูแลคลังแก้เองได้ตั้งแต่ 8 ก.ย. 69"""
    h = auth(admin_token)
    before = next(s for s in (await client.get("/settings", headers=h)).json()
                  if s["key"] == "default_pickup_time")["value"]
    try:
        r = await client.patch("/settings/default_pickup_time", headers=h, json={"value": "09:30"})
        assert r.status_code == 200, r.text
        assert r.json()["value"] == "09:30"
    finally:
        await client.patch("/settings/default_pickup_time", headers=h, json={"value": before})


async def test_superadmin_can_change_role(client: AsyncClient, superadmin_token: str):
    """เปลี่ยนสิทธิ์ได้และต้องมี audit ว่าใครเปลี่ยนจากอะไรเป็นอะไร"""
    h = auth(superadmin_token)
    user = await _make_user("student")
    try:
        r = await client.patch(f"/users/{user.id}/role", headers=h,
                               json={"role": "admin", "reason": "ทดสอบเลื่อนสิทธิ์"})
        assert r.status_code == 200, r.text
        assert r.json()["role"] == "admin"

        async with AsyncSessionLocal() as db:
            logs = (await db.execute(
                select(AuditLog).where(AuditLog.target_id == user.id, AuditLog.action == "update_user_role")
            )).scalars().all()
        assert len(logs) == 1
        assert logs[0].detail["changes"]["role"] == ["student", "admin"]

        assert (await client.patch(f"/users/{user.id}/role", headers=h,
                                   json={"role": "ไม่มีสิทธิ์นี้"})).status_code == 400
    finally:
        await _cleanup_users(user.id)


async def test_change_request_flow(client: AsyncClient, admin_token: str, superadmin_token: str,
                                   student_token: str):
    """ผู้ดูแลคลังยื่นคำขอ → ผู้ดูแลระบบสูงสุดเห็นและปิดงานได้ / นักศึกษายื่นไม่ได้"""
    h_admin, h_super, h_student = auth(admin_token), auth(superadmin_token), auth(student_token)
    body = {
        "target_table": "equipment",
        "target_label": "NB-001 โน้ตบุ๊คทดสอบ",
        "reason": "รหัสครุภัณฑ์พิมพ์ผิดตั้งแต่นำเข้า แก้เองไม่ได้",
        "detail": "ขอเปลี่ยนรหัสจาก 671001 เป็น 671010",
    }
    assert (await client.post("/change-requests", headers=h_student, json=body)).status_code == 403

    r = await client.post("/change-requests", headers=h_admin, json=body)
    assert r.status_code == 201, r.text
    cr_id = uuid.UUID(r.json()["id"])
    try:
        assert r.json()["status"] == "pending"
        assert r.json()["requester_name"]

        seen = await client.get("/change-requests", headers=h_super, params={"status": "pending"})
        assert str(cr_id) in {i["id"] for i in seen.json()["items"]}

        # ผู้ดูแลคลังปิดงานเองไม่ได้
        assert (await client.patch(f"/change-requests/{cr_id}/approve", headers=h_admin,
                                   json={})).status_code == 403
        # ปฏิเสธต้องมีเหตุผล
        assert (await client.patch(f"/change-requests/{cr_id}/reject", headers=h_super,
                                   json={})).status_code == 400

        r = await client.patch(f"/change-requests/{cr_id}/approve", headers=h_super,
                               json={"decision_note": "แก้รหัสให้แล้ว"})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "approved"
        assert r.json()["decided_by_name"]

        # ตัดสินซ้ำไม่ได้
        assert (await client.patch(f"/change-requests/{cr_id}/reject", headers=h_super,
                                   json={"decision_note": "x"})).status_code == 400
    finally:
        await _cleanup_change_requests(cr_id)


async def test_system_check_returns_counts(client: AsyncClient, superadmin_token: str):
    """หน้าตรวจสุขภาพข้อมูลต้องนับแถวได้จริงและไม่รับ SQL จากผู้ใช้ (ไม่มีพารามิเตอร์ให้ส่ง)"""
    r = await client.get("/change-requests/system-check", headers=auth(superadmin_token))
    assert r.status_code == 200, r.text
    data = r.json()
    tables = {c["table"]: c["count"] for c in data["counts"]}
    assert tables["users"] > 0 and "equipment" in tables
    assert isinstance(data["issues"], list)


async def test_staff_notifications_include_superadmin(client: AsyncClient, student_token: str,
                                                      test_superadmin, test_equipment):
    """แจ้งเตือน "มีคำขอใหม่" ต้องส่งถึงผู้ดูแลระบบสูงสุดด้วย ไม่ใช่เฉพาะ role admin
    (จุดที่พลาดง่ายที่สุดตอนเพิ่ม role ใหม่ — query เดิมเขียน role == "admin" ตรง ๆ)"""
    from app.models.notification import Notification

    r = await client.post("/borrow-requests", headers=auth(student_token), json={
        "purpose": "ทดสอบแจ้งเตือนถึงผู้ดูแลระบบสูงสุด",
        "requested_due_date": "2028-06-01",
        "items": [{"equipment_id": str(test_equipment.id), "quantity": 1}],
    })
    assert r.status_code == 201, r.text
    req_id = uuid.UUID(r.json()["id"])
    try:
        async with AsyncSessionLocal() as db:
            got = (await db.execute(select(Notification).where(
                Notification.borrow_request_id == req_id,
                Notification.user_id == test_superadmin.id,
            ))).scalars().all()
        assert len(got) == 1, "ผู้ดูแลระบบสูงสุดต้องได้รับแจ้งเตือนคำขอใหม่ด้วย"
    finally:
        from app.models.borrow_item import BorrowItem
        from app.models.borrow_request import BorrowRequest
        async with AsyncSessionLocal() as db:
            await db.execute(delete(AuditLog).where(AuditLog.target_id == req_id))
            await db.execute(delete(Notification).where(Notification.borrow_request_id == req_id))
            await db.execute(delete(BorrowItem).where(BorrowItem.borrow_request_id == req_id))
            await db.execute(delete(BorrowRequest).where(BorrowRequest.id == req_id))
            await db.commit()


async def test_admin_can_delete_equipment_permanently(client: AsyncClient, admin_token: str):
    """ลบอุปกรณ์ถาวรเป็นงานของผู้ดูแลคลังตั้งแต่ 8 ก.ย. 69 (เติม/เคลียร์คลังคืองานประจำของคลัง)

    เงื่อนไขเดิมยังอยู่ครบ: ต้องปลดระวางก่อน และห้ามมีประวัติการยืมค้าง
    """
    h = auth(admin_token)
    code = f"{uuid.uuid4().int % 10**15:015d}"
    created = await client.post("/equipment", headers=h, json={
        "code": code, "name": f"อุปกรณ์ทดสอบลบถาวร {uuid.uuid4().hex[:5]}", "category_ids": [],
        "item_type": "durable", "quantity_total": 1, "image_urls": ["/uploads/test.jpg"],
        "unit_value": 100, "acquired_at": "2024-01-15",
    })
    assert created.status_code == 201, created.text
    eq_id = created.json()["id"]
    # ยังไม่ปลดระวาง = ลบไม่ได้ (กฎเดิมต้องไม่หายไปพร้อมกับการเปิดสิทธิ์)
    assert (await client.delete(f"/equipment/{eq_id}/permanent", headers=h)).status_code == 400
    assert (await client.patch(f"/equipment/{eq_id}", headers=h,
                               json={"status": "retired", "status_reason": "ทดสอบ"})).status_code == 200
    assert (await client.delete(f"/equipment/{eq_id}/permanent", headers=h)).status_code == 204
