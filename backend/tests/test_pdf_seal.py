"""ตราดิจิทัลบน PDF (E-sign 16 พ.ย. 69) — ประทับแล้วตรวจได้ · แก้ไฟล์ทีหลังต้องจับได้ · ไม่มีใบรับรอง = PDF เดิม"""
import io
import subprocess

from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign.validation import validate_pdf_signature
from pyhanko_certvalidator import ValidationContext
from pyhanko.keys import load_cert_from_pemder

from app.core.config import settings
from app.utils.pdf import generate_room_qr_pdf
from app.utils.pdf_seal import _signer, seal_pdf


def _sample_pdf() -> bytes:
    return generate_room_qr_pdf([])


def _use_temp_cert(tmp_path, monkeypatch) -> str:
    key, cert = tmp_path / "key.pem", tmp_path / "cert.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2",
                    "-keyout", str(key), "-out", str(cert), "-subj", "/CN=test seal"],
                   check=True, capture_output=True)
    monkeypatch.setattr(settings, "SIGNING_KEY_PATH", str(key))
    monkeypatch.setattr(settings, "SIGNING_CERT_PATH", str(cert))
    _signer.cache_clear()
    return str(cert)


def test_seal_roundtrip_and_tamper_detection(tmp_path, monkeypatch):
    cert = _use_temp_cert(tmp_path, monkeypatch)

    sealed = seal_pdf(_sample_pdf(), "ทดสอบ")
    vc = ValidationContext(trust_roots=[load_cert_from_pemder(str(cert))])
    sig = PdfFileReader(io.BytesIO(sealed)).embedded_signatures[0]
    status = validate_pdf_signature(sig, vc)
    assert status.intact and status.valid

    # แก้ไบต์ในช่วงที่ถูกเซ็น (เนื้อหา PDF ต้นฉบับ) → ตรวจแล้วต้องไม่ intact
    tampered = bytearray(sealed)
    i = tampered.index(b"/Producer")
    tampered[i + 1] = ord("X")
    sig = PdfFileReader(io.BytesIO(bytes(tampered))).embedded_signatures[0]
    assert not validate_pdf_signature(sig, vc).intact
    _signer.cache_clear()


def test_no_cert_returns_original(monkeypatch):
    monkeypatch.setattr(settings, "SIGNING_KEY_PATH", "")
    pdf = _sample_pdf()
    assert seal_pdf(pdf, "x") == pdf


async def test_borrow_pdf_from_api_is_sealed(
    tmp_path, monkeypatch, client, student_token, admin_token, test_equipment,
):
    """ผ่าน API จริง (มี event loop) ต้องได้ตราด้วย — เดิมเรียก sign_pdf บน loop แล้วตกไปออกแบบไม่ประทับเงียบ ๆ"""
    import uuid
    from sqlalchemy import delete
    from app.core.database import AsyncSessionLocal
    from app.models.audit_log import AuditLog
    from app.models.borrow_item import BorrowItem
    from app.models.borrow_request import BorrowRequest
    from app.models.equipment import Equipment
    from app.models.notification import Notification
    from tests.conftest import auth

    _use_temp_cert(tmp_path, monkeypatch)
    r = await client.post("/borrow-requests", headers=auth(student_token), json={
        "purpose": "ทดสอบตรา", "requested_due_date": "2028-06-01",
        "items": [{"equipment_id": str(test_equipment.id), "quantity": 1}]})
    assert r.status_code == 201, r.text
    rid = uuid.UUID(r.json()["id"])
    try:
        assert (await client.patch(f"/borrow-requests/{rid}/approve", headers=auth(admin_token))).status_code == 200
        pdf = await client.get(f"/borrow-requests/{rid}/pdf", headers=auth(admin_token))
        assert pdf.status_code == 200
        assert PdfFileReader(io.BytesIO(pdf.content)).embedded_signatures
    finally:
        _signer.cache_clear()
        async with AsyncSessionLocal() as db:
            await db.execute(delete(AuditLog).where(AuditLog.target_id == rid))
            await db.execute(delete(Notification).where(Notification.borrow_request_id == rid))
            await db.execute(delete(BorrowItem).where(BorrowItem.borrow_request_id == rid))
            await db.execute(delete(BorrowRequest).where(BorrowRequest.id == rid))
            eq = await db.get(Equipment, test_equipment.id)
            eq.quantity_available = eq.quantity_total
            await db.commit()
