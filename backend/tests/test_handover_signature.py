"""ลงนามรับของ/รับคืน (เฟส 11 → E-sign ด้วยรหัสผ่าน 16 พ.ย. 69) — POST /handover, /sign-return

แทนการปริ้นใบยืมไปเซ็นแล้วถ่ายรูปกลับมา: เจ้าหน้าที่กดที่เคาน์เตอร์แล้วยื่นจอให้ผู้ยืมพิมพ์รหัสผ่านตัวเอง
ไม่เก็บรูปลายเซ็นใหม่อีก (รูปหลุด = เอาไปปลอมเอกสารอื่นได้) — หลักฐานคือ signature_meta + ตราดิจิทัลบน PDF

สิ่งที่ต้องกันให้ได้:
- นักศึกษากดจ่ายของเองไม่ได้ (require_admin เหมือน endpoint รับคืน)
- คำขอที่ยังไม่อนุมัติจ่ายของไม่ได้ (ยังไม่มีของให้ส่งมอบ)
- รหัสผ่านผิด = 400 (ไม่ใช่ 401 ที่ทำให้จอเจ้าหน้าที่ถูกล็อกเอาต์) และไม่บันทึกอะไร
- ไม่มีไฟล์รูปลายเซ็นใหม่เกิดขึ้น
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
STUDENT_PW, ADMIN_PW = "Test1234!", "Admin1234!"  # ตรงกับ conftest


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
                              data={"borrower_password": STUDENT_PW})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["handover_at"] is not None
        assert body["handover_by_name"]
        assert body["signatures"] == []   # ไม่มีรูปลายเซ็นแล้ว
        assert [e["kind"] for e in body["esignatures"]] == ["handover_borrower"]
        assert body["esignatures"][0]["ref"] and body["esignatures"][0]["signer_name"]
        assert "signature_meta" not in body
        # หน้ารายการต้องไม่พังเมื่อมีคำขอที่จ่ายของแล้ว (handover_by_name เคย lazy-load → 500 ทั้งหน้า)
        r = await client.get("/borrow-requests", params={"search": test_equipment.code},
                             headers=auth(admin_token))
        assert r.status_code == 200, r.text
        assert any(x["id"] == req["id"] and x["handover_by_name"] for x in r.json()["items"])

        async with AsyncSessionLocal() as db:
            fresh = await db.get(BorrowRequest, uuid.UUID(req["id"]))
            meta = fresh.signature_meta["handover_borrower"]
            assert fresh.handover_sig_borrower is None   # ไม่มีไฟล์รูป
            assert meta["method"] == "password" and len(meta["doc_sha256"]) == 64
            assert STUDENT_PW not in str(fresh.signature_meta)   # ห้ามเก็บรหัสผ่าน
            # สต็อกต้องเท่าเดิมหลังจ่ายของ (ตัดไปแล้วตอนอนุมัติ)
            assert (await db.get(Equipment, test_equipment.id)).quantity_available == stock_after_approve

        # ใบยืมพิมพ์ผู้ลงนาม + เลขอ้างอิงแทนรูป
        import io
        from pypdf import PdfReader
        pdf = await client.get(f"/borrow-requests/{req['id']}/pdf", headers=auth(admin_token))
        assert pdf.status_code == 200, pdf.text
        text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf.content)).pages)
        assert body["esignatures"][0]["ref"] in text

        # เซ็นซ้ำไม่ได้ — ลายเซ็นคือหลักฐานการรับมอบ ทับได้เมื่อไหร่ก็อ้างได้ว่าไม่ใช่ฉบับที่ตัวเองเซ็น
        again = await client.post(f"/borrow-requests/{req['id']}/handover", headers=auth(admin_token),
                                  data={"borrower_password": STUDENT_PW})
        assert again.status_code == 400, again.text

        async with AsyncSessionLocal() as db:
            actions = (await db.execute(
                delete(AuditLog).where(AuditLog.target_id == uuid.UUID(req["id"]))
                .returning(AuditLog.action)
            )).scalars().all()
            await db.commit()
        assert "handover_request" in actions
    finally:
        await _cleanup(req["id"], test_equipment.id, files)


async def test_handover_requires_admin_and_approved_request(
    client: AsyncClient, student_token: str, admin_token: str, test_equipment: Equipment,
):
    req = await _pending_request(client, student_token, test_equipment.id)
    try:
        # ยังไม่อนุมัติ — เจ้าหน้าที่ก็จ่ายของไม่ได้ (ของยังไม่ออกจากคลัง)
        r = await client.post(f"/borrow-requests/{req['id']}/handover", headers=auth(admin_token),
                              data={"borrower_password": STUDENT_PW})
        assert r.status_code == 400, r.text

        assert (await client.patch(f"/borrow-requests/{req['id']}/approve",
                                   headers=auth(admin_token))).status_code == 200
        # นักศึกษากดจ่ายของให้ตัวเองไม่ได้
        r = await client.post(f"/borrow-requests/{req['id']}/handover", headers=auth(student_token),
                              data={"borrower_password": STUDENT_PW})
        assert r.status_code == 403, r.text
    finally:
        await _cleanup(req["id"], test_equipment.id, [])


async def test_handover_rejects_wrong_password(
    client: AsyncClient, student_token: str, admin_token: str, test_equipment: Equipment,
):
    """รหัสผ่านผิดทั้งฝั่งผู้ยืมและเจ้าหน้าที่ = 400 (ไม่ใช่ 401) และยังไม่จ่ายของ"""
    req = await _pending_request(client, student_token, test_equipment.id)
    assert (await client.patch(f"/borrow-requests/{req['id']}/approve",
                               headers=auth(admin_token))).status_code == 200
    try:
        url = f"/borrow-requests/{req['id']}/handover"
        r = await client.post(url, headers=auth(admin_token), data={"borrower_password": "wrong-pw"})
        assert r.status_code == 400, r.text
        r = await client.post(url, headers=auth(admin_token),
                              data={"borrower_password": STUDENT_PW, "staff_password": "wrong-pw"})
        assert r.status_code == 400, r.text
        async with AsyncSessionLocal() as db:
            fresh = await db.get(BorrowRequest, uuid.UUID(req["id"]))
            assert fresh.handover_at is None and not fresh.signature_meta
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
                              data={"borrower_password": STUDENT_PW})
        assert r.status_code == 400, r.text

        assert (await client.post(f"/borrow-requests/{req['id']}/return-all",
                                  headers=auth(admin_token))).status_code == 200
        r = await client.post(f"/borrow-requests/{req['id']}/sign-return", headers=auth(admin_token),
                              data={"borrower_password": STUDENT_PW, "staff_password": ADMIN_PW})
        assert r.status_code == 200, r.text
        assert {e["kind"] for e in r.json()["esignatures"]} == {"return_borrower", "return_staff"}

        # เซ็นรับคืนซ้ำก็ไม่ได้เช่นกัน
        again = await client.post(f"/borrow-requests/{req['id']}/sign-return", headers=auth(admin_token),
                                  data={"borrower_password": STUDENT_PW})
        assert again.status_code == 400, again.text

        async with AsyncSessionLocal() as db:
            fresh = await db.get(BorrowRequest, uuid.UUID(req["id"]))
            files.extend(_sig_files({"signature_meta": fresh.signature_meta}))

        # ใบคืนต้องมีผู้ลงนาม วันที่ที่ลงนามจริง และป้ายว่าเซ็นในระบบแล้ว
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


async def test_handover_without_signature_needs_uploaded_signed_form(
    client: AsyncClient, student_token: str, admin_token: str, test_equipment: Equipment,
):
    """ผู้ยืมอัปโหลดใบยืมที่เซ็นแล้ว → บันทึกจ่ายของได้โดยไม่เซ็นซ้ำบนจอ (10 พ.ย. 69 — Prod ยังขึ้นปุ่มให้เซ็นอีก)"""
    req = await _pending_request(client, student_token, test_equipment.id)
    assert (await client.patch(f"/borrow-requests/{req['id']}/approve",
                               headers=auth(admin_token))).status_code == 200
    files: list[str] = []
    try:
        url = f"/borrow-requests/{req['id']}/handover"
        # ยังไม่มีใบเซ็น + ไม่เซ็นบนจอ = ไม่มีหลักฐานการรับของเลย
        assert (await client.post(url, headers=auth(admin_token))).status_code == 400

        r = await client.post(f"/borrow-requests/{req['id']}/signed-form", headers=auth(student_token),
                              files={"file": ("signed.png", PNG_BYTES, "image/png")})
        assert r.status_code == 200, r.text
        files.append(r.json()["signed_form_file"])

        r = await client.post(url, headers=auth(admin_token))
        assert r.status_code == 200, r.text
        assert r.json()["handover_at"] and r.json()["esignatures"] == []
        # บันทึกจ่ายของซ้ำไม่ได้ ทั้งแบบไม่เซ็นและแบบเซ็น
        assert (await client.post(url, headers=auth(admin_token))).status_code == 400
        assert (await client.post(url, headers=auth(admin_token),
                                  data={"borrower_password": STUDENT_PW})).status_code == 400
    finally:
        await _cleanup(req["id"], test_equipment.id, files)


def _kinds(resp: dict) -> set[str]:
    return {e["kind"] for e in resp.get("esignatures") or []}


async def test_sign_at_request_and_approval_no_counter_queue(
    client: AsyncClient, student_token: str, admin_token: str, test_equipment
):
    """23 พ.ย. 69 — ผู้ยืมลงชื่อพร้อมยื่น · เจ้าหน้าที่ลงชื่อในโมดัลอนุมัติ · จ่ายของไม่ต้องใช้รหัสอีก ·
    ลงชื่อใบคืนเองจากเครื่องตัวเอง · รหัสผิดตอนยื่น = ไม่มีคำขอเกิดขึ้น"""
    S, H = auth(student_token), auth(admin_token)
    body = {"purpose": "ทดสอบลงชื่อตอนยื่น", "requested_due_date": "2028-06-01",
            "items": [{"equipment_id": str(test_equipment.id), "quantity": 1}]}
    before = (await client.get("/borrow-requests", headers=S)).json()["total"]
    r = await client.post("/borrow-requests", headers=S, json={**body, "sign_password": "wrong"})
    assert r.status_code == 400
    assert (await client.get("/borrow-requests", headers=S)).json()["total"] == before

    r = await client.post("/borrow-requests", headers=S, json={**body, "sign_password": STUDENT_PW})
    assert r.status_code == 201, r.text
    req = r.json()
    rid = req["id"]
    try:
        assert _kinds(req) == {"handover_borrower"}
        r = await client.patch(f"/borrow-requests/{rid}/approve", headers=H, json={"sign_password": "bad"})
        assert r.status_code == 400  # รหัสเจ้าหน้าที่ผิด = อนุมัติไม่ผ่าน ไม่ตัดสต็อก
        assert (await client.get(f"/borrow-requests/{rid}", headers=H)).json()["status"] == "pending"
        r = await client.patch(f"/borrow-requests/{rid}/approve", headers=H, json={"sign_password": ADMIN_PW})
        assert r.status_code == 200, r.text
        assert _kinds((await client.get(f"/borrow-requests/{rid}", headers=H)).json()) == {"handover_borrower", "handover_staff"}

        r = await client.post(f"/borrow-requests/{rid}/handover", headers=H)  # ลงชื่อครบแล้ว กดปุ่มเดียว
        assert r.status_code == 200, r.text

        item_id = r.json()["items"][0]["id"]
        assert (await client.post(f"/borrow-requests/{rid}/sign", headers=S,
                                  json={"phase": "return", "password": STUDENT_PW})).status_code == 400  # ยังไม่คืน
        assert (await client.post(f"/borrow-requests/{rid}/items/{item_id}/return", headers=H,
                                  json={"condition_on_return": "ok"})).status_code == 200
        assert (await client.post(f"/borrow-requests/{rid}/sign", headers=H,
                                  json={"phase": "return", "password": ADMIN_PW})).status_code == 403  # เจ้าหน้าที่แทนไม่ได้
        r = await client.post(f"/borrow-requests/{rid}/sign", headers=S, json={"phase": "return", "password": STUDENT_PW})
        assert r.status_code == 200 and "return_borrower" in _kinds(r.json()), r.text
        assert (await client.post(f"/borrow-requests/{rid}/sign", headers=S,
                                  json={"phase": "return", "password": STUDENT_PW})).status_code == 400  # ซ้ำ
        # เจ้าหน้าที่ลงชื่อฝั่งผู้รับคืนทีหลังได้ โดยไม่ต้องใช้รหัสผู้ยืม
        r = await client.post(f"/borrow-requests/{rid}/sign-return", headers=H, data={"staff_password": ADMIN_PW})
        assert r.status_code == 200 and "return_staff" in _kinds(r.json()), r.text
        for path in ("pdf", "return-pdf"):
            assert (await client.get(f"/borrow-requests/{rid}/{path}", headers=S)).content[:4] == b"%PDF"
    finally:
        await _cleanup(rid, test_equipment.id, [])


async def test_changed_due_date_at_approval_requires_borrower_to_resign(
    client: AsyncClient, student_token: str, admin_token: str, test_equipment
):
    """แก้วันคืนตอนอนุมัติ = ลายเซ็นผู้ยืมถูกพัก + แจ้งให้ลงชื่อใหม่ · อนุมัติตามที่ขอ = ลายเซ็นคงเดิม"""
    S, H = auth(student_token), auth(admin_token)
    r = await client.post("/borrow-requests", headers=S, json={
        "purpose": "ทดสอบแก้วันคืน", "requested_due_date": "2028-06-01", "sign_password": STUDENT_PW,
        "items": [{"equipment_id": str(test_equipment.id), "quantity": 1}]})
    assert r.status_code == 201, r.text
    req = r.json()
    rid = req["id"]
    try:
        r = await client.patch(f"/borrow-requests/{rid}/approve", headers=H, json={
            "items": [{"item_id": req["items"][0]["id"], "approved": True, "due_date": "2028-05-01"}]})
        assert r.status_code == 200, r.text
        assert "handover_borrower" not in _kinds((await client.get(f"/borrow-requests/{rid}", headers=S)).json())
        async with AsyncSessionLocal() as db:
            row = await db.get(BorrowRequest, uuid.UUID(rid))
            assert "handover_borrower_superseded" in row.signature_meta  # หลักฐานเดิมยังอยู่
        notes = (await client.get("/notifications/me", headers=S)).json()
        notes = notes.get("items", notes) if isinstance(notes, dict) else notes
        assert any("ลงชื่อใบยืมใหม่" in n["message"] for n in notes)
        r = await client.post(f"/borrow-requests/{rid}/sign", headers=S, json={"phase": "borrow", "password": STUDENT_PW})
        assert r.status_code == 200 and "handover_borrower" in _kinds(r.json()), r.text
    finally:
        await _cleanup(rid, test_equipment.id, [])
