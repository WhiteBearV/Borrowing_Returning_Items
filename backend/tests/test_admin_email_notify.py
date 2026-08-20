"""แจ้งเตือนทางอีเมล (นอกเหนือจาก in-app): admin เมื่อมีคำขอใหม่/เกินกำหนดคืน,
นักศึกษาเมื่ออนุมัติ/ปฏิเสธ/รับคืน

MAIL_USERNAME ใน .env test เป็น placeholder → send_email() แค่ print แทนส่งจริง
(ดู app/utils/email.py::_email_configured) จึงตรวจผลจาก stdout ผ่าน capsys
"""
import uuid
from datetime import date, timedelta

from httpx import AsyncClient
from sqlalchemy import delete, select, update

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.borrow_item import BorrowItem
from app.models.borrow_request import BorrowRequest
from app.models.equipment import Equipment
from app.models.notification import Notification
from app.models.user import User
from tests.conftest import auth


async def _create_request(client: AsyncClient, student_token: str, equipment: Equipment, purpose: str) -> dict:
    r = await client.post("/borrow-requests", headers=auth(student_token), json={
        "purpose": purpose,
        "requested_due_date": "2028-06-01", "items": [{"equipment_id": str(equipment.id), "quantity": 1}],
    })
    assert r.status_code == 201
    return r.json()


async def _cleanup_request(req_id: str, eq_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(AuditLog).where(AuditLog.target_id == uuid.UUID(req_id)))
        await db.execute(delete(Notification).where(Notification.borrow_request_id == req_id))
        await db.execute(delete(BorrowItem).where(BorrowItem.borrow_request_id == req_id))
        await db.execute(delete(BorrowRequest).where(BorrowRequest.id == req_id))
        eq = await db.get(Equipment, eq_id)
        if eq:
            eq.quantity_available = eq.quantity_total
            eq.status = "available"
        await db.commit()


async def test_new_request_emails_every_active_admin(
    client: AsyncClient, capsys, student_token: str, test_admin: User, test_equipment: Equipment,
):
    r = await client.post("/borrow-requests", headers=auth(student_token), json={
        "purpose": "ทดสอบแจ้งเตือน admin ทางอีเมล",
        "requested_due_date": "2028-06-01", "items": [{"equipment_id": str(test_equipment.id), "quantity": 1}],
    })
    assert r.status_code == 201
    req = r.json()

    out = capsys.readouterr().out
    assert f"[DEV EMAIL] To: {test_admin.email}" in out
    assert req["request_code"] in out

    await _cleanup_request(req["id"], test_equipment.id)


async def test_admin_borrowing_for_self_does_not_self_notify(
    client: AsyncClient, capsys, admin_token: str, test_admin: User, test_equipment: Equipment,
):
    """admin ยืมของตัวเอง (self-borrow) ต้องไม่ได้ 'new_request_admin' แจ้งคำขอของตัวเอง

    ก่อนแก้: loop แจ้ง admin ทุกคนไม่ยกเว้นตัวเอง — admin คนเดียวในระบบที่ยืมของตัวเอง
    จะเห็นทั้ง in-app และอีเมล "มีคำขอใหม่" ซ้อนกับคำขอที่ตัวเองเพิ่งส่ง
    """
    r = await client.post("/borrow-requests", headers=auth(admin_token), json={
        "purpose": "admin ยืมของตัวเอง",
        "requested_due_date": "2028-06-01", "items": [{"equipment_id": str(test_equipment.id), "quantity": 1}],
    })
    assert r.status_code == 201
    req = r.json()

    out = capsys.readouterr().out
    assert f"[DEV EMAIL] To: {test_admin.email}" not in out
    assert "new_request_admin" not in out

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Notification).where(
                Notification.user_id == test_admin.id,
                Notification.type == "new_request_admin",
                Notification.borrow_request_id == uuid.UUID(req["id"]),
            )
        )
        assert result.scalar_one_or_none() is None

    await _cleanup_request(req["id"], test_equipment.id)


async def test_overdue_job_sends_admin_digest_email(
    client: AsyncClient, capsys, student_token: str, admin_token: str,
    test_admin: User, test_equipment: Equipment,
):
    from app.utils.scheduler import _check_overdue

    r = await client.post("/borrow-requests", headers=auth(student_token), json={
        "purpose": "ทดสอบ overdue digest",
        "requested_due_date": "2028-06-01", "items": [{"equipment_id": str(test_equipment.id), "quantity": 1}],
    })
    req = r.json()
    assert (await client.patch(f"/borrow-requests/{req['id']}/approve", headers=auth(admin_token))).status_code == 200

    # ปั้นให้เกินกำหนดคืนไปแล้วเมื่อวาน กัน scheduler รอจริงข้ามคืน
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(BorrowRequest).where(BorrowRequest.id == uuid.UUID(req["id"]))
            .values(due_date=date.today() - timedelta(days=1))
        )
        await db.commit()

    capsys.readouterr()  # ล้าง output สะสมจากขั้นตอนก่อนหน้า
    await _check_overdue()

    out = capsys.readouterr().out
    assert f"[DEV EMAIL] To: {test_admin.email}" in out
    assert req["request_code"] in out
    assert "เกินกำหนดคืน" in out

    await _cleanup_request(req["id"], test_equipment.id)


async def test_approve_emails_student(
    client: AsyncClient, capsys, student_token: str, admin_token: str,
    test_student: User, test_equipment: Equipment,
):
    req = await _create_request(client, student_token, test_equipment, "ทดสอบอีเมลอนุมัติ")
    capsys.readouterr()  # ล้าง output จากอีเมลแจ้ง admin ตอนสร้างคำขอ

    r = await client.patch(f"/borrow-requests/{req['id']}/approve", headers=auth(admin_token))
    assert r.status_code == 200

    out = capsys.readouterr().out
    assert f"[DEV EMAIL] To: {test_student.email}" in out
    assert req["request_code"] in out

    await _cleanup_request(req["id"], test_equipment.id)


async def test_reject_emails_student(
    client: AsyncClient, capsys, student_token: str, admin_token: str,
    test_student: User, test_equipment: Equipment,
):
    req = await _create_request(client, student_token, test_equipment, "ทดสอบอีเมลปฏิเสธ")
    capsys.readouterr()

    r = await client.patch(
        f"/borrow-requests/{req['id']}/reject",
        headers=auth(admin_token),
        json={"rejection_reason": "อุปกรณ์ต้องเก็บไว้ใช้ในห้องแล็บ"},
    )
    assert r.status_code == 200

    out = capsys.readouterr().out
    assert f"[DEV EMAIL] To: {test_student.email}" in out
    assert req["request_code"] in out
    assert "อุปกรณ์ต้องเก็บไว้ใช้ในห้องแล็บ" in out

    await _cleanup_request(req["id"], test_equipment.id)


async def test_return_item_emails_student(
    client: AsyncClient, capsys, student_token: str, admin_token: str,
    test_student: User, test_equipment: Equipment,
):
    req = await _create_request(client, student_token, test_equipment, "ทดสอบอีเมลรับคืนรายชิ้น")
    assert (await client.patch(f"/borrow-requests/{req['id']}/approve", headers=auth(admin_token))).status_code == 200
    item_id = req["items"][0]["id"]
    capsys.readouterr()

    r = await client.post(
        f"/borrow-requests/{req['id']}/items/{item_id}/return",
        headers=auth(admin_token),
        json={"condition_on_return": "ok"},
    )
    assert r.status_code == 200

    out = capsys.readouterr().out
    assert f"[DEV EMAIL] To: {test_student.email}" in out
    assert req["request_code"] in out

    await _cleanup_request(req["id"], test_equipment.id)


async def test_return_all_emails_student(
    client: AsyncClient, capsys, student_token: str, admin_token: str,
    test_student: User, test_equipment: Equipment,
):
    req = await _create_request(client, student_token, test_equipment, "ทดสอบอีเมลรับคืนทั้งหมด")
    assert (await client.patch(f"/borrow-requests/{req['id']}/approve", headers=auth(admin_token))).status_code == 200
    capsys.readouterr()

    r = await client.post(f"/borrow-requests/{req['id']}/return-all", headers=auth(admin_token))
    assert r.status_code == 200

    out = capsys.readouterr().out
    assert f"[DEV EMAIL] To: {test_student.email}" in out
    assert req["request_code"] in out

    await _cleanup_request(req["id"], test_equipment.id)
