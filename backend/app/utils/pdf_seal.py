"""ประทับตราดิจิทัล (PAdES) บนใบยืม/ใบคืน — E-sign แทนรูปลายเซ็น (16 พ.ย. 69)

ลายเซ็นของคนคือการยืนยันตัวตนด้วยรหัสผ่าน (borrow_service._esign) ส่วนตรานี้ผูกเนื้อหาทั้งไฟล์กับระบบ:
ใครแก้ PDF ทีหลัง โปรแกรมอ่าน PDF จะขึ้นว่าเอกสารถูกแก้ไขหลังลงนาม · ใบรับรองออกเอง (gen-signing-cert.sh)
จึงขึ้น "ไม่รู้จักผู้ออก" — เปลี่ยนเป็นใบรับรองขององค์กรได้โดยแค่เปลี่ยนไฟล์
"""
import io
import logging
import os
from functools import lru_cache

from app.core.config import settings

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _signer(key_path: str, cert_path: str):  # noqa: ANN202 — pyhanko SimpleSigner
    from pyhanko.sign import signers
    return signers.SimpleSigner.load(key_path, cert_path)


def seal_pdf(pdf: bytes, reason: str) -> bytes:
    """คืน PDF ที่ประทับตราแล้ว — ไม่มีใบรับรอง/ประทับไม่สำเร็จ = คืนไฟล์เดิม (ห้ามทำเอกสารออกไม่ได้เพราะตรา)

    **ต้องเรียกนอก event loop** (asyncio.to_thread) — sign_pdf ของ pyHanko ใช้ asyncio.run ภายใน
    """
    key, cert = settings.SIGNING_KEY_PATH, settings.SIGNING_CERT_PATH
    if not key or not cert or not (os.path.isfile(key) and os.path.isfile(cert)):
        return pdf
    try:
        from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
        from pyhanko.sign import signers
        signer = _signer(key, cert)
        out = signers.sign_pdf(
            IncrementalPdfFileWriter(io.BytesIO(pdf)),
            signers.PdfSignatureMetadata(field_name="SystemSeal", reason=reason,
                                         location="ระบบยืม-คืนอุปกรณ์ คณะเทคโนโลยีดิจิทัล"),
            signer=signer,
        )
        return out.getvalue()
    except Exception:
        log.exception("seal_pdf failed — returning unsealed PDF")
        return pdf
