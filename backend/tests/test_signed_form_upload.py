"""ใบยืมที่เซ็นแล้ว — อัปโหลด (POST) และเปิดดู (GET) /borrow-requests/{id}/signed-form

ผู้ยืมปริ้นใบยืมไปเซ็นแล้วส่งไฟล์กลับเข้าระบบแทนการถือกระดาษมา — เช็คว่า
เก็บไฟล์+เวลาลงคำขอ, อัปทับได้, กันคนอื่นอัปใส่คำขอที่ไม่ใช่ของตัวเอง และกันชนิดไฟล์แปลก ๆ

**เฟส 7 (ความปลอดภัยของไฟล์):** ไฟล์ต้องอยู่ใน PRIVATE_UPLOAD_DIR ที่ไม่ได้ mount เป็น static
(ไม่งั้นเอกสารที่มีลายเซ็น + ชื่อ + รหัส นศ. เปิดได้ด้วย URL เปล่า = ผิด PDPA) เปิดดูได้เฉพาะ
เจ้าของคำขอกับเจ้าหน้าที่ และไฟล์ที่เนื้อในไม่ตรงนามสกุลต้องถูกปฏิเสธตั้งแต่ตอนอัปโหลด
"""
import os
import uuid

from httpx import AsyncClient
from sqlalchemy import delete

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.borrow_item import BorrowItem
from app.models.borrow_request import BorrowRequest
from app.models.equipment import Equipment
from app.models.notification import Notification
from app.models.user import User
from tests.conftest import auth

PDF_BYTES = b"%PDF-1.4 fake signed form"


async def _cleanup(req_id: str, eq_ids: list[uuid.UUID], files: list[str]) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(AuditLog).where(AuditLog.target_id == uuid.UUID(req_id)))
        await db.execute(delete(Notification).where(Notification.borrow_request_id == req_id))
        await db.execute(delete(BorrowItem).where(BorrowItem.borrow_request_id == req_id))
        await db.execute(delete(BorrowRequest).where(BorrowRequest.id == req_id))
        for eq_id in eq_ids:
            eq = await db.get(Equipment, eq_id)
            if eq:
                eq.quantity_available = eq.quantity_total
                eq.status = "available"
        await db.commit()
    # ไฟล์ที่เทสอัปขึ้นไปต้องเก็บกวาดเอง ไม่งั้นโฟลเดอร์บวมทุกครั้งที่รันเทส
    for name in files:
        path = os.path.join(settings.PRIVATE_UPLOAD_DIR, os.path.basename(name))
        if os.path.exists(path):
            os.remove(path)


async def _approved_request(client: AsyncClient, student_token: str, admin_token: str,
                            equipment_id: uuid.UUID, purpose: str) -> dict:
    r = await client.post("/borrow-requests", headers=auth(student_token), json={
        "purpose": purpose, "requested_due_date": "2028-06-01",
        "items": [{"equipment_id": str(equipment_id), "quantity": 1}],
    })
    assert r.status_code == 201, r.text
    req = r.json()
    assert (await client.patch(f"/borrow-requests/{req['id']}/approve",
                               headers=auth(admin_token))).status_code == 200
    return req


async def test_upload_signed_form_stores_file_and_allows_reupload(
    client: AsyncClient, student_token: str, admin_token: str, test_equipment: Equipment,
):
    req = await _approved_request(client, student_token, admin_token, test_equipment.id, "ทดสอบอัปใบยืมที่เซ็นแล้ว")
    files_made: list[str] = []
    try:
        r = await client.post(f"/borrow-requests/{req['id']}/signed-form", headers=auth(student_token),
                              files={"file": ("signed.pdf", PDF_BYTES, "application/pdf")})
        assert r.status_code == 200, r.text
        name = r.json()["signed_form_file"]
        files_made.append(name)
        # ต้องเป็นชื่อไฟล์เปล่า ไม่ใช่ path/URL — ห้ามมีอะไรให้เอาไปแปะเป็นลิงก์ตรงได้
        assert "/" not in name and name.endswith(".pdf")
        assert os.path.exists(os.path.join(settings.PRIVATE_UPLOAD_DIR, name))
        # และต้องไม่ไปโผล่ในโฟลเดอร์ที่เสิร์ฟสาธารณะ
        assert not os.path.exists(os.path.join(settings.UPLOAD_DIR, name))

        body = (await client.get(f"/borrow-requests/{req['id']}", headers=auth(student_token))).json()
        assert body["signed_form_file"] == name
        assert body["signed_form_at"] is not None

        # อัปใหม่ = ทับของเดิม (เอกสารที่มีผลคือฉบับล่าสุดเสมอ)
        r2 = await client.post(f"/borrow-requests/{req['id']}/signed-form", headers=auth(student_token),
                               files={"file": ("signed2.jpg", b"\xff\xd8\xff fake photo", "image/jpeg")})
        assert r2.status_code == 200
        name2 = r2.json()["signed_form_file"]
        files_made.append(name2)
        assert name2 != name
        body2 = (await client.get(f"/borrow-requests/{req['id']}", headers=auth(student_token))).json()
        assert body2["signed_form_file"] == name2
    finally:
        await _cleanup(req["id"], [test_equipment.id], files_made)


async def test_upload_signed_form_rejects_bad_type_and_other_students(
    client: AsyncClient, student_token: str, admin_token: str, test_equipment: Equipment,
):
    req = await _approved_request(client, student_token, admin_token, test_equipment.id, "ทดสอบกันไฟล์แปลก")
    other_id = uuid.uuid4()
    try:
        r = await client.post(f"/borrow-requests/{req['id']}/signed-form", headers=auth(student_token),
                              files={"file": ("virus.exe", b"MZ", "application/octet-stream")})
        assert r.status_code == 400

        # คำขอของคนอื่น: นักศึกษาอีกคนอัปทับไม่ได้ (เอกสารต้องเป็นของเจ้าของคำขอเท่านั้น)
        from app.core.security import create_access_token, hash_password
        async with AsyncSessionLocal() as db:
            db.add(User(id=other_id, email=f"other-{other_id.hex[:6]}@student.cdti.ac.th",
                        username=f"other{other_id.hex[:6]}", full_name="นักศึกษาอีกคน",
                        student_id=f"6{other_id.hex[:9]}"[:10], password_hash=hash_password("x"),
                        role="student", is_active=True, email_verified=True))
            await db.commit()
        other_token = create_access_token(str(other_id))
        r2 = await client.post(f"/borrow-requests/{req['id']}/signed-form", headers=auth(other_token),
                               files={"file": ("signed.pdf", PDF_BYTES, "application/pdf")})
        assert r2.status_code == 403
    finally:
        await _cleanup(req["id"], [test_equipment.id], [])
        async with AsyncSessionLocal() as db:
            await db.execute(delete(AuditLog).where(AuditLog.actor_id == other_id))
            await db.execute(delete(User).where(User.id == other_id))
            await db.commit()


async def test_signed_form_download_checks_permission(
    client: AsyncClient, student_token: str, admin_token: str, test_equipment: Equipment,
):
    """เฟส 7: เปิดดูได้เฉพาะเจ้าของคำขอกับเจ้าหน้าที่ — คนอื่นต้องโดน 403 ไม่ใช่ได้ไฟล์ไป"""
    req = await _approved_request(client, student_token, admin_token, test_equipment.id, "ทดสอบสิทธิ์เปิดใบเซ็น")
    files_made: list[str] = []
    other_id = uuid.uuid4()
    try:
        r = await client.post(f"/borrow-requests/{req['id']}/signed-form", headers=auth(student_token),
                              files={"file": ("signed.pdf", PDF_BYTES, "application/pdf")})
        assert r.status_code == 200, r.text
        files_made.append(r.json()["signed_form_file"])

        # เจ้าของคำขอเปิดได้ และได้เนื้อไฟล์เดิมกลับมาจริง
        own = await client.get(f"/borrow-requests/{req['id']}/signed-form", headers=auth(student_token))
        assert own.status_code == 200 and own.content == PDF_BYTES
        # เจ้าหน้าที่เปิดได้ (ต้องตรวจเอกสารก่อนจ่ายของ)
        assert (await client.get(f"/borrow-requests/{req['id']}/signed-form",
                                 headers=auth(admin_token))).status_code == 200

        from app.core.security import create_access_token, hash_password
        async with AsyncSessionLocal() as db:
            db.add(User(id=other_id, email=f"other-{other_id.hex[:6]}@student.cdti.ac.th",
                        username=f"other{other_id.hex[:6]}", full_name="นักศึกษาอีกคน",
                        student_id=f"6{other_id.hex[:9]}"[:10], password_hash=hash_password("x"),
                        role="student", is_active=True, email_verified=True))
            await db.commit()
        other = await client.get(f"/borrow-requests/{req['id']}/signed-form",
                                 headers=auth(create_access_token(str(other_id))))
        assert other.status_code == 403
        # ไม่ล็อกอินเลยก็ต้องไม่ได้ (ของเดิมเปิดได้ด้วย URL เปล่าเพราะอยู่ใน static)
        assert (await client.get(f"/borrow-requests/{req['id']}/signed-form")).status_code == 401
    finally:
        await _cleanup(req["id"], [test_equipment.id], files_made)
        async with AsyncSessionLocal() as db:
            await db.execute(delete(AuditLog).where(AuditLog.actor_id == other_id))
            await db.execute(delete(User).where(User.id == other_id))
            await db.commit()


async def test_signed_form_rejects_content_that_does_not_match_extension(
    client: AsyncClient, student_token: str, admin_token: str, test_equipment: Equipment,
):
    """เฟส 7: เปลี่ยนนามสกุลไฟล์สคริปต์เป็น .pdf/.png แล้วอัปไม่ได้ — ตรวจ magic bytes ไม่ใช่แค่ชื่อไฟล์"""
    req = await _approved_request(client, student_token, admin_token, test_equipment.id, "ทดสอบ magic bytes")
    try:
        for filename, content in [("evil.pdf", b"<script>alert(1)</script>"),
                                  ("evil.png", b"<?php system($_GET['c']); ?>")]:
            r = await client.post(f"/borrow-requests/{req['id']}/signed-form", headers=auth(student_token),
                                  files={"file": (filename, content, "application/octet-stream")})
            assert r.status_code == 400, f"{filename} ควรถูกปฏิเสธ: {r.text}"

        body = (await client.get(f"/borrow-requests/{req['id']}", headers=auth(student_token))).json()
        assert body["signed_form_file"] is None, "ไฟล์ที่ถูกปฏิเสธต้องไม่ถูกบันทึกลงคำขอ"
    finally:
        await _cleanup(req["id"], [test_equipment.id], [])
