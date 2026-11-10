"""3 พ.ย. 69 — สวิตช์ซ่อนชื่อผู้ยืม · ปุ่มแจ้งปัญหา · รูปในอีเมลแนบแบบ inline (เทียบโอนอยู่ใน test_student_year.py)

PYTEST_ALLOW_DB=1 รันใส่ DB dev จริง — cleanup ใน finally เสมอ
"""
import io

from httpx import AsyncClient
from PIL import Image

from app.models.user import User
from app.services import feedback_service
from tests.conftest import auth
from tests.test_equipment_multiple_holders import _cleanup, _make_equipment

KEY = "show_borrower_names_to_users"


async def test_hide_borrower_names_for_students_only(
    client: AsyncClient, admin_token: str, student_token: str, test_student: User,
):
    h_admin, h_student = auth(admin_token), auth(student_token)
    eq_id = await _make_equipment(client, h_admin)
    req_ids: list[str] = []
    try:
        r = await client.post("/borrow-requests", headers=h_student, json={
            "purpose": "ทดสอบซ่อนชื่อ", "requested_due_date": "2028-06-01",
            "items": [{"equipment_id": eq_id, "quantity": 2}],
        })
        assert r.status_code == 201, r.text
        req_ids.append(r.json()["id"])
        assert (await client.patch(f"/borrow-requests/{req_ids[0]}/approve", headers=h_admin)).status_code == 200

        assert (await client.patch(f"/settings/{KEY}", headers=h_admin, json={"value": "maybe"})).status_code == 400
        assert (await client.patch(f"/settings/{KEY}", headers=h_admin, json={"value": "false"})).status_code == 200
        hidden = (await client.get(f"/equipment/{eq_id}", headers=h_student)).json()["holders"]
        assert hidden and hidden[0]["holder_name"] is None and hidden[0]["student_number"] is None
        assert hidden[0]["quantity"] == 2 and hidden[0]["due_date"]
        grouped = (await client.get(f"/equipment/grouped/{eq_id}", headers=h_student)).json()["holders"]
        assert grouped[0]["holder_name"] is None
        staff = (await client.get(f"/equipment/{eq_id}", headers=h_admin)).json()["holders"]
        assert staff[0]["holder_name"] == test_student.full_name

        assert (await client.patch(f"/settings/{KEY}", headers=h_admin, json={"value": "true"})).status_code == 200
        shown = (await client.get(f"/equipment/{eq_id}", headers=h_student)).json()["holders"]
        assert shown[0]["holder_name"] == test_student.full_name
    finally:
        await client.patch(f"/settings/{KEY}", headers=h_admin, json={"value": "true"})
        await _cleanup(eq_id, req_ids, [])


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "red").save(buf, "PNG")
    return buf.getvalue()


async def test_feedback_email(client: AsyncClient, student_token: str, monkeypatch):
    h = auth(student_token)
    data = {"kind": "bug", "detail": "ปุ่มกดไม่ได้\nรายละเอียด <b>x</b>"}
    # อีเมลปิด (ค่าใน .env เทส) → 503 ให้ผู้ใช้รู้ว่าไม่ถึง
    assert (await client.post("/feedback", headers=h, data=data)).status_code == 503

    sent = []

    async def fake_send(to, subject, body, attachments=None, reply_to=None, wait=False):
        sent.append((to, subject, body, attachments, reply_to))
    monkeypatch.setattr(feedback_service.email_utils, "email_configured", True)
    monkeypatch.setattr(feedback_service.email_utils, "send_email", fake_send)

    fake = {"files": ("a.png", b"<html>not an image</html>", "image/png")}
    assert (await client.post("/feedback", headers=h, data=data, files=fake)).status_code == 400
    assert (await client.post("/feedback", headers=h, data={**data, "detail": "   "})).status_code == 400
    assert (await client.post("/feedback", data=data)).status_code == 401

    files = [("files", ("a.png", _png(), "image/png")), ("files", ("b.png", _png(), "image/png"))]
    r = await client.post("/feedback", headers=h, data=data, files=files)
    assert r.status_code == 204, r.text
    to, subject, body, attachments, reply_to = sent[-1]
    assert to == "verapat056@gmail.com" and subject == "แจ้งปัญหา: ปุ่มกดไม่ได้"
    assert "&lt;b&gt;" in body and len(attachments) == 2 and reply_to


async def test_send_email_does_not_block_request(monkeypatch):
    """อีเมลต้องส่งเบื้องหลัง — เดิม await SMTP ในคำขอ ทำให้กดยืม/อนุมัติบน Prod ค้าง ~5 วิต่อฉบับ"""
    import asyncio
    import time
    from app.utils import email as email_utils

    async def slow_send(message):
        await asyncio.sleep(0.5)
    monkeypatch.setattr(email_utils, "_email_configured", True)
    monkeypatch.setattr(email_utils.fm, "send_message", slow_send)
    t = time.monotonic()
    await email_utils.send_email("x@cdti.ac.th", "s", "<p>b</p>")
    assert time.monotonic() - t < 0.2
    await asyncio.gather(*email_utils._pending)


async def test_send_email_related_only_with_cid(monkeypatch):
    """รูปแนบธรรมดา (แจ้งปัญหา) ต้องเป็น mixed — related ที่ไม่มี cid โดน Gmail กรองเป็นสแปม (10 พ.ย. 69)"""
    import io
    from fastapi import UploadFile
    from app.utils import email as email_utils

    sent = []

    async def capture(message):
        sent.append(message.multipart_subtype.value)
    monkeypatch.setattr(email_utils, "_email_configured", True)
    monkeypatch.setattr(email_utils.fm, "send_message", capture)
    plain = {"file": UploadFile(filename="a.png", file=io.BytesIO(_png()))}
    inline = {"file": UploadFile(filename="b.png", file=io.BytesIO(_png())),
              "headers": {"Content-ID": "<x>", "Content-Disposition": 'inline; filename="b.png"'}}
    await email_utils.send_email("x@cdti.ac.th", "s", "<p>b</p>", attachments=[plain], wait=True)
    await email_utils.send_email("x@cdti.ac.th", "s", '<img src="cid:x">', attachments=[inline], wait=True)
    assert sent == ["mixed", "related"]
