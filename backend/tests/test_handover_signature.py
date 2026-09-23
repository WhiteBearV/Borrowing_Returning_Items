"""เซ็นรับของ/รับคืนบนหน้าจอ (เฟส 11) — POST /handover, /sign-return และ GET /signature/{kind}

แทนการปริ้นใบยืมไปเซ็นแล้วถ่ายรูปกลับมา: เจ้าหน้าที่กดที่เคาน์เตอร์แล้วยื่นจอให้ผู้ยืมเซ็น

สิ่งที่ต้องกันให้ได้:
- นักศึกษากดจ่ายของเองไม่ได้ (require_admin เหมือน endpoint รับคืน)
- คำขอที่ยังไม่อนุมัติจ่ายของไม่ได้ (ยังไม่มีของให้ส่งมอบ)
- ไฟล์ที่ไม่ใช่ PNG จริง (เปลี่ยนแค่นามสกุล) ต้องถูกปฏิเสธตั้งแต่ตอนอัปโหลด
- ลายเซ็นต้องไม่มี URL สาธารณะ เปิดได้เฉพาะเจ้าของคำขอ/เจ้าหน้าที่ และลง audit ทุกครั้งที่เปิดดู
- **สต็อกต้องไม่เปลี่ยน** เพราะของออกจากคลังตั้งแต่ตอนอนุมัติแล้ว (กฎเดิมใน CLAUDE.md)

หมายเหตุ: conftest.py มี PYTEST_ALLOW_DB=1 รันใส่ DB dev จริง — ทุกเทสต้อง cleanup ใน finally เสมอ
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
from tests.conftest import auth

def _png(width: int = 60, height: int = 24) -> bytes:
    """PNG จริงที่เปิดได้ — ไม่ใช่แค่ magic bytes เพราะ ReportLab ต้องอ่านรูปตอนสร้างใบยืมด้วย"""
    import io
    from PIL import Image as PILImage
    buf = io.BytesIO()
    PILImage.new("RGBA", (width, height), (0, 0, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()


PNG_BYTES = _png()


async def _cleanup(req_id: str, eq_id: uuid.UUID, files: list[str]) -> None:
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
    for name in files:
        path = os.path.join(settings.PRIVATE_UPLOAD_DIR, os.path.basename(name))
        if os.path.exists(path):
            os.remove(path)


async def _pending_request(client: AsyncClient, student_token: str, equipment_id: uuid.UUID) -> dict:
    r = await client.post("/borrow-requests", headers=auth(student_token), json={
        "purpose": "ทดสอบเซ็นรับของ", "requested_due_date": "2028-06-01",
        "items": [{"equipment_id": str(equipment_id), "quantity": 1}],
    })
    assert r.status_code == 201, r.text
    return r.json()


def _sig_files(client_response: dict) -> list[str]:
    """ชื่อไฟล์ลายเซ็นทั้งหมดใน signature_meta — ใช้เก็บกวาดไฟล์หลังเทส"""
    meta = client_response.get("signature_meta") or {}
    return [v["file"] for v in meta.values() if isinstance(v, dict) and v.get("file")]


async def test_handover_stores_signature_without_touching_stock(
    client: AsyncClient, student_token: str, admin_token: str, superadmin_token: str,
    test_equipment: Equipment,
):
    req = await _pending_request(client, student_token, test_equipment.id)
    assert (await client.patch(f"/borrow-requests/{req['id']}/approve",
                               headers=auth(admin_token))).status_code == 200
    async with AsyncSessionLocal() as db:
        stock_after_approve = (await db.get(Equipment, test_equipment.id)).quantity_available

    files: list[str] = []
    try:
        # ผู้จ่ายของ ≠ ผู้อนุมัติ (เหมือนหน้างานจริง) — ถ้าคนเดียวกัน User อยู่ใน identity map จาก approver แล้ว
        # จะไม่เกิด lazy-load และจับบั๊ก MissingGreenlet ของ handover_by_name ไม่ได้
        r = await client.post(f"/borrow-requests/{req['id']}/handover", headers=auth(superadmin_token),
                              files={"borrower_signature": ("sig.png", PNG_BYTES, "image/png")})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["handover_at"] is not None
        assert body["handover_by_name"]
        assert body["signatures"] == ["handover_borrower"]   # ไม่ได้เซ็นฝั่งเจ้าหน้าที่ = ต้องไม่โผล่
        # ชื่อไฟล์ลายเซ็นต้องไม่หลุดออก API — เปิดดูได้ทางเดียวคือ endpoint ที่ตรวจสิทธิ์
        assert "handover_sig_borrower" not in body and "signature_meta" not in body
        # หน้ารายการต้องไม่พังเมื่อมีคำขอที่จ่ายของแล้ว (handover_by_name เคย lazy-load → 500 ทั้งหน้า)
        r = await client.get("/borrow-requests", params={"search": test_equipment.code},
                             headers=auth(admin_token))
        assert r.status_code == 200, r.text
        assert any(x["id"] == req["id"] and x["handover_by_name"] for x in r.json()["items"])

        async with AsyncSessionLocal() as db:
            fresh = await db.get(BorrowRequest, uuid.UUID(req["id"]))
            files.extend(_sig_files({"signature_meta": fresh.signature_meta}))
            stored = fresh.handover_sig_borrower
            # ชื่อไฟล์เปล่า ไม่ใช่ path/URL — ห้ามมีอะไรเอาไปแปะเป็นลิงก์ตรงได้
            assert "/" not in stored and stored.endswith(".png")
            assert fresh.signature_meta["handover_borrower"]["sha256"]
            # สต็อกต้องเท่าเดิมหลังจ่ายของ (ตัดไปแล้วตอนอนุมัติ)
            assert (await db.get(Equipment, test_equipment.id)).quantity_available == stock_after_approve

        assert os.path.exists(os.path.join(settings.PRIVATE_UPLOAD_DIR, stored))
        assert not os.path.exists(os.path.join(settings.UPLOAD_DIR, stored))

        # เปิดดูได้ทั้งเจ้าของคำขอและเจ้าหน้าที่ · ชนิดที่ไม่มีไฟล์ = 404 · kind มั่ว = 400
        assert (await client.get(f"/borrow-requests/{req['id']}/signature/handover_borrower",
                                 headers=auth(student_token))).status_code == 200
        assert (await client.get(f"/borrow-requests/{req['id']}/signature/handover_staff",
                                 headers=auth(admin_token))).status_code == 404
        assert (await client.get(f"/borrow-requests/{req['id']}/signature/nonsense",
                                 headers=auth(admin_token))).status_code == 400

        # เซ็นซ้ำไม่ได้ — ลายเซ็นคือหลักฐานการรับมอบ ทับได้เมื่อไหร่ก็อ้างได้ว่าไม่ใช่ฉบับที่ตัวเองเซ็น
        again = await client.post(f"/borrow-requests/{req['id']}/handover", headers=auth(admin_token),
                                  files={"borrower_signature": ("sig.png", PNG_BYTES, "image/png")})
        assert again.status_code == 400, again.text

        async with AsyncSessionLocal() as db:
            actions = (await db.execute(
                delete(AuditLog).where(AuditLog.target_id == uuid.UUID(req["id"]))
                .returning(AuditLog.action)
            )).scalars().all()
            await db.commit()
        assert "handover_request" in actions
        assert "view_signature" in actions   # การเปิดดูลายเซ็นต้องถูกบันทึกเสมอ
    finally:
        await _cleanup(req["id"], test_equipment.id, files)


async def test_handover_requires_admin_and_approved_request(
    client: AsyncClient, student_token: str, admin_token: str, test_equipment: Equipment,
):
    req = await _pending_request(client, student_token, test_equipment.id)
    try:
        # ยังไม่อนุมัติ — เจ้าหน้าที่ก็จ่ายของไม่ได้ (ของยังไม่ออกจากคลัง)
        r = await client.post(f"/borrow-requests/{req['id']}/handover", headers=auth(admin_token),
                              files={"borrower_signature": ("sig.png", PNG_BYTES, "image/png")})
        assert r.status_code == 400, r.text

        assert (await client.patch(f"/borrow-requests/{req['id']}/approve",
                                   headers=auth(admin_token))).status_code == 200
        # นักศึกษากดจ่ายของให้ตัวเองไม่ได้
        r = await client.post(f"/borrow-requests/{req['id']}/handover", headers=auth(student_token),
                              files={"borrower_signature": ("sig.png", PNG_BYTES, "image/png")})
        assert r.status_code == 403, r.text
    finally:
        await _cleanup(req["id"], test_equipment.id, [])


async def test_handover_rejects_file_that_is_not_really_png(
    client: AsyncClient, student_token: str, admin_token: str, test_equipment: Equipment,
):
    """ไฟล์อื่นเปลี่ยนนามสกุลเป็น .png ต้องไม่ผ่าน — ด่านเดียวกับการอัปโหลดอื่นในระบบ"""
    req = await _pending_request(client, student_token, test_equipment.id)
    assert (await client.patch(f"/borrow-requests/{req['id']}/approve",
                               headers=auth(admin_token))).status_code == 200
    try:
        r = await client.post(f"/borrow-requests/{req['id']}/handover", headers=auth(admin_token),
                              files={"borrower_signature": ("fake.png", b"<html>hi</html>", "image/png")})
        assert r.status_code == 400, r.text
    finally:
        await _cleanup(req["id"], test_equipment.id, [])


async def test_sign_return_requires_a_returned_item_and_shows_on_pdf(
    client: AsyncClient, student_token: str, admin_token: str, test_equipment: Equipment,
):
    req = await _pending_request(client, student_token, test_equipment.id)
    assert (await client.patch(f"/borrow-requests/{req['id']}/approve",
                               headers=auth(admin_token))).status_code == 200
    files: list[str] = []
    try:
        # ยังไม่มีชิ้นไหนถูกรับคืน — เซ็นใบคืนไม่ได้
        r = await client.post(f"/borrow-requests/{req['id']}/sign-return", headers=auth(admin_token),
                              files={"borrower_signature": ("sig.png", PNG_BYTES, "image/png")})
        assert r.status_code == 400, r.text

        assert (await client.post(f"/borrow-requests/{req['id']}/return-all",
                                  headers=auth(admin_token))).status_code == 200
        r = await client.post(f"/borrow-requests/{req['id']}/sign-return", headers=auth(admin_token),
                              files={"borrower_signature": ("sig.png", PNG_BYTES, "image/png"),
                                     "staff_signature": ("sig2.png", PNG_BYTES, "image/png")})
        assert r.status_code == 200, r.text
        assert set(r.json()["signatures"]) == {"return_borrower", "return_staff"}

        # เซ็นรับคืนซ้ำก็ไม่ได้เช่นกัน
        again = await client.post(f"/borrow-requests/{req['id']}/sign-return", headers=auth(admin_token),
                                  files={"borrower_signature": ("sig.png", PNG_BYTES, "image/png")})
        assert again.status_code == 400, again.text

        async with AsyncSessionLocal() as db:
            fresh = await db.get(BorrowRequest, uuid.UUID(req["id"]))
            files.extend(_sig_files({"signature_meta": fresh.signature_meta}))

        # ใบคืนต้องมีทั้งรูปลายเซ็น วันที่ที่รับลายเซ็นจริง และป้ายว่าเซ็นในระบบแล้ว
        pdf = (await client.get(f"/borrow-requests/{req['id']}/return-pdf", headers=auth(admin_token)))
        assert pdf.status_code == 200
        assert pdf.content.startswith(b"%PDF")

        import io
        from pypdf import PdfReader
        text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf.content)).pages)
        assert "ลงลายมือชื่ออิเล็กทรอนิกส์ในระบบแล้ว" in text
        # วันที่ต้องถูกเติมให้แล้ว ไม่ใช่เส้นว่างให้เขียนมือ (ใบนี้เซ็นครบทั้งสองฝั่ง)
        assert "วันที่ .........." not in text
    finally:
        await _cleanup(req["id"], test_equipment.id, files)
