"""เทสกันถดถอยของบั๊กระดับกลาง/เล็กจาก QA 30 ก.ย. 69 (รายละเอียดแต่ละข้ออยู่ใน Plans/qa-2026-09-30/bugs.md)

หมายเหตุ: conftest.py มี PYTEST_ALLOW_DB=1 รันใส่ DB dev จริง — ลบทุกอย่างที่สร้าง + audit ใน finally
"""
import uuid
from datetime import date, datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token, create_refresh_token, hash_password
from app.models.audit_log import AuditLog
from app.models.borrow_item import BorrowItem
from app.models.borrow_request import BorrowRequest
from app.models.equipment import Equipment
from app.models.notification import Notification
from app.models.user import User
from app.utils.study_year import UNKNOWN_YEAR_LABEL, compute_study_year, display_label
from tests.conftest import auth


def test_unknown_year_student_is_not_labelled_staff():
    """QA-10: นักศึกษาที่ไม่ทราบปีเข้า ≠ บุคลากร"""
    info = compute_study_year(None, 4)
    assert display_label(True, None, info) == UNKNOWN_YEAR_LABEL
    assert display_label(False, None, info) == "บุคลากร"
    assert display_label(True, 2569, compute_study_year(2569, 4, today=date(2026, 10, 1))) == "ปีที่ 1"


async def test_nul_byte_is_400_not_500(client: AsyncClient, student_token: str, admin_token: str):
    """QA-05"""
    for url, tok in (("/equipment", student_token), ("/equipment/grouped", student_token),
                     ("/borrow-requests", admin_token)):
        r = await client.get(url, headers=auth(tok), params={"search": "\x00"})
        assert r.status_code == 400, (url, r.status_code)


async def test_input_validation_followups(client: AsyncClient, admin_token: str, student_token: str,
                                          test_equipment: Equipment):
    """QA-08 บรรทัดซ้ำ · QA-09/13 เหตุผลช่องว่าง · QA-20 ประเภท/สถานะ/เกณฑ์สต็อกที่ไม่มีจริง"""
    h, rid, iid = auth(admin_token), uuid.uuid4(), uuid.uuid4()
    line = {"equipment_id": str(test_equipment.id), "quantity": 1}
    r = await client.post("/borrow-requests", headers=auth(student_token), json={
        "purpose": "ซ้ำ", "requested_due_date": str(date.today() + timedelta(days=3)), "items": [line, line]})
    assert r.status_code == 400, r.text

    r = await client.patch(f"/borrow-requests/{rid}/reject", headers=h, json={"rejection_reason": "   "})
    assert r.status_code == 422, r.text
    r = await client.post(f"/borrow-requests/{rid}/items/{iid}/renew-request", headers=auth(student_token),
                          json={"requested_date": str(date.today() + timedelta(days=5)), "reason": "   "})
    assert r.status_code == 422, r.text

    for patch in ({"item_type": "gadget"}, {"status": "exploded", "status_reason": "x"}, {"low_stock_threshold": -3}):
        r = await client.patch(f"/equipment/{test_equipment.id}", headers=h, json=patch)
        assert r.status_code == 422, (patch, r.text)


async def test_request_search_code_and_appointment_cap(
    client: AsyncClient, admin_token: str, student_token: str, test_student: User, test_admin: User,
):
    """QA-14 ค้นด้วยเลขคำขอ · QA-21 นัดคืนล่วงหน้าเกิน 1 ปี"""
    rid, iid = uuid.uuid4(), uuid.uuid4()
    code = f"REQ-QAF-{rid.hex[:8]}"
    async with AsyncSessionLocal() as db:
        db.add(BorrowRequest(id=rid, request_code=code, student_id=test_student.id, status="approved",
                             purpose="ทดสอบค้นเลขคำขอ", approved_at=datetime.now(timezone.utc),
                             approved_by=test_admin.id, requested_due_date=date.today() + timedelta(days=3),
                             due_date=date.today() + timedelta(days=3)))
        db.add(BorrowItem(id=iid, borrow_request_id=rid, item_type_snapshot="durable", quantity=1,
                          item_status="approved", due_date=date.today() + timedelta(days=3)))
        await db.commit()
    try:
        r = await client.get("/borrow-requests", headers=auth(admin_token), params={"search": code[4:]})
        assert r.status_code == 200 and [i["request_code"] for i in r.json()["items"]] == [code], r.text

        body = {"item_ids": [str(iid)], "return_appoint_location": "ห้องพัสดุ"}
        r = await client.post(f"/borrow-requests/{rid}/request-return", headers=auth(student_token),
                              json={**body, "return_appoint_at": "2099-01-01T13:00"})
        assert r.status_code == 400, r.text
        soon = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%dT13:00")
        r = await client.post(f"/borrow-requests/{rid}/request-return", headers=auth(student_token),
                              json={**body, "return_appoint_at": soon})
        assert r.status_code == 200, r.text
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(AuditLog).where(AuditLog.target_id.in_([rid, iid])))
            await db.execute(delete(Notification).where(Notification.borrow_request_id == rid))
            await db.execute(delete(BorrowItem).where(BorrowItem.borrow_request_id == rid))
            await db.execute(delete(BorrowRequest).where(BorrowRequest.id == rid))
            await db.commit()


async def test_email_case_and_rejected_account_tokens(client: AsyncClient):
    """QA-15 อีเมลไม่สนตัวพิมพ์ · QA-16 บัญชีที่ถูกปฏิเสธใช้ token เดิม/ต่ออายุไม่ได้"""
    uid = uuid.uuid4()
    email = f"qaf_{uid.hex[:8]}@cdti.ac.th"
    async with AsyncSessionLocal() as db:
        db.add(User(id=uid, full_name="ทดสอบ อีเมล", email=email, student_id=f"65{uid.int % 10**8:08d}",
                    password_hash=hash_password("Test1234!"), role="student", email_verified=True,
                    is_active=True, approval_status="approved"))
        await db.commit()
    try:
        r = await client.post("/auth/login", json={"identifier": email.upper(), "password": "Test1234!"})
        assert r.status_code == 200, r.text
        r = await client.post("/auth/register", json={
            "email": email.upper().replace("@CDTI.AC.TH", "@cdti.ac.th"), "password": "Test1234!",
            "full_name": "ซ้ำ ตัวพิมพ์", "student_id": f"65{(uid.int + 1) % 10**8:08d}", "phone": "0811111111",
            "major": "comp_eng", "pdpa_consent": True})
        assert r.status_code == 409, r.text

        access = create_access_token(str(uid), extra={"role": "student"})
        refresh = create_refresh_token(str(uid))
        assert (await client.get("/users/me", headers=auth(access))).status_code == 200
        async with AsyncSessionLocal() as db:
            (await db.get(User, uid)).approval_status = "rejected"
            await db.commit()
        assert (await client.get("/users/me", headers=auth(access))).status_code == 403
        assert (await client.post("/auth/refresh", json={"refresh_token": refresh})).status_code == 401
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(AuditLog).where(AuditLog.actor_id == uid))
            await db.execute(delete(User).where(User.id == uid))
            await db.commit()
