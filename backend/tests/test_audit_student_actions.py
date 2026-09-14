"""เฟส 1 (feedback อาจารย์ 5 ก.ย. 69) — audit log ต้องครอบคลุมฝั่งนักศึกษาและการแก้ค่าระบบด้วย
ไม่ใช่เฉพาะ action ของแอดมิน + ต้องกรองตามผู้ทำ/สิทธิ์ได้

หมายเหตุ: conftest.py มี PYTEST_ALLOW_DB=1 รันใส่ DB dev จริง — ทุกเทสต้อง cleanup ใน finally เสมอ
(รวมถึงแถว audit_logs ที่เทสสร้างเอง ไม่งั้นขยะสะสมในประวัติจริง)
"""
import uuid

from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.borrow_item import BorrowItem
from app.models.borrow_request import BorrowRequest
from app.models.notification import Notification
from app.models.setting import Setting
from tests.conftest import auth


async def _logs_for(target_id: uuid.UUID) -> list[AuditLog]:
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(AuditLog).where(AuditLog.target_id == target_id).order_by(AuditLog.created_at)
        )).scalars().all()
        return list(rows)


async def _cleanup_request(req_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(AuditLog).where(AuditLog.target_id == req_id))
        await db.execute(delete(Notification).where(Notification.borrow_request_id == req_id))
        await db.execute(delete(BorrowItem).where(BorrowItem.borrow_request_id == req_id))
        await db.execute(delete(BorrowRequest).where(BorrowRequest.id == req_id))
        await db.commit()


async def test_student_create_and_cancel_are_audited(client: AsyncClient, student_token: str, test_equipment):
    """ยื่นคำขอและยกเลิกคำขอต้องถูกบันทึก พร้อม snapshot สิทธิ์ ณ ตอนทำ (actor_role)"""
    h = auth(student_token)
    r = await client.post("/borrow-requests", headers=h, json={
        "purpose": "ทดสอบ audit ฝั่งนักศึกษา",
        "requested_due_date": "2028-06-01",
        "items": [{"equipment_id": str(test_equipment.id), "quantity": 1}],
    })
    assert r.status_code == 201, r.text
    req_id = uuid.UUID(r.json()["id"])
    req_code = r.json()["request_code"]
    try:
        logs = await _logs_for(req_id)
        assert [lg.action for lg in logs] == ["create_request"]
        created = logs[0]
        assert created.actor_role == "student"
        assert created.actor_name
        assert created.detail["request_code"] == req_code
        assert created.detail["items"], "ต้อง snapshot ชื่ออุปกรณ์ไว้ใน log ไม่ใช่ join ทีหลัง"

        r = await client.patch(f"/borrow-requests/{req_id}/cancel", headers=h, json={"reason": "ทดสอบยกเลิก"})
        assert r.status_code == 200, r.text
        assert [lg.action for lg in await _logs_for(req_id)] == ["create_request", "cancel_request"]
    finally:
        await _cleanup_request(req_id)


async def test_audit_filter_by_actor_and_role(client: AsyncClient, admin_token: str, student_token: str,
                                              test_student, test_equipment):
    """หน้า audit ต้องกรองด้วยชื่อ/รหัสผู้ทำ และกรองด้วยสิทธิ์ได้"""
    h_admin, h_student = auth(admin_token), auth(student_token)
    r = await client.post("/borrow-requests", headers=h_student, json={
        "purpose": "ทดสอบ audit filter",
        "requested_due_date": "2028-06-01",
        "items": [{"equipment_id": str(test_equipment.id), "quantity": 1}],
    })
    assert r.status_code == 201, r.text
    req_id = uuid.UUID(r.json()["id"])
    try:
        r = await client.get("/audit-logs", headers=h_admin,
                             params={"actor": test_student.student_id, "page_size": 100})
        assert r.status_code == 200, r.text
        assert str(req_id) in {i["target_id"] for i in r.json()["items"]}

        # กรองสิทธิ์คนละระดับต้องไม่เจอ log ของนักศึกษา
        r = await client.get("/audit-logs", headers=h_admin,
                             params={"actor_role": "admin", "action": "create_request", "page_size": 100})
        assert str(req_id) not in {i["target_id"] for i in r.json()["items"]}
    finally:
        await _cleanup_request(req_id)


async def test_setting_change_is_audited_with_diff(client: AsyncClient, superadmin_token: str):
    """แก้ค่าระบบต้องบันทึกว่าใครเปลี่ยนจากเท่าไหร่เป็นเท่าไหร่ — ค่าเดิมต้องถูกคืนหลังเทส
    (endpoint นี้ย้ายไปเป็นสิทธิ์ของผู้ดูแลระบบสูงสุดตั้งแต่เฟส 2)"""
    key = "due_soon_notify_days_before"
    async with AsyncSessionLocal() as db:
        original = (await db.execute(select(Setting).where(Setting.key == key))).scalar_one().value
    new_value = str(int(original) + 1)
    target_id = uuid.uuid5(uuid.NAMESPACE_OID, f"setting:{key}")
    try:
        r = await client.patch(f"/settings/{key}", headers=auth(superadmin_token), json={"value": new_value})
        assert r.status_code == 200, r.text
        logs = await _logs_for(target_id)
        assert logs and logs[-1].action == "update_setting"
        assert logs[-1].detail["changes"][key] == [original, new_value]
        assert logs[-1].actor_role == "superadmin"

        # เขียนค่าเดิมซ้ำต้องไม่สร้าง log ขยะ
        before = len(logs)
        await client.patch(f"/settings/{key}", headers=auth(superadmin_token), json={"value": new_value})
        assert len(await _logs_for(target_id)) == before
    finally:
        await client.patch(f"/settings/{key}", headers=auth(superadmin_token), json={"value": original})
        async with AsyncSessionLocal() as db:
            await db.execute(delete(AuditLog).where(AuditLog.target_id == target_id))
            await db.commit()


async def test_cancel_requires_reason(client: AsyncClient, student_token: str, test_equipment):
    """ยกเลิกคำขอต้องมีเหตุผลเสมอ (8 ก.ย. 69) — ของถูกกันไว้ให้แล้ว คนอื่นรอคิวอยู่"""
    h = auth(student_token)
    r = await client.post("/borrow-requests", headers=h, json={
        "purpose": "ทดสอบยกเลิกต้องมีเหตุผล", "requested_due_date": "2028-06-01",
        "items": [{"equipment_id": str(test_equipment.id), "quantity": 1}],
    })
    assert r.status_code == 201, r.text
    req_id = r.json()["id"]
    try:
        # ช่องว่างล้วน = ไม่มีเหตุผล (service strip ก่อนตรวจ) · ไม่ส่ง reason เลย = 422 จาก schema
        assert (await client.patch(f"/borrow-requests/{req_id}/cancel", headers=h,
                                   json={"reason": "   "})).status_code == 400
        assert (await client.patch(f"/borrow-requests/{req_id}/cancel", headers=h,
                                   json={})).status_code == 422
        ok = await client.patch(f"/borrow-requests/{req_id}/cancel", headers=h,
                                json={"reason": "เลือกอุปกรณ์ผิดรายการ"})
        assert ok.status_code == 200, ok.text
        body = (await client.get(f"/borrow-requests/{req_id}", headers=h)).json()
        assert body["status"] == "cancelled"
        assert body["cancel_reason"] == "เลือกอุปกรณ์ผิดรายการ"
    finally:
        await _cleanup_request(req_id)
