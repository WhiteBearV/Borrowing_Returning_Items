"""แจ้งปัญหา / ข้อเสนอแนะจากผู้ใช้ (3 พ.ย. 69) — ส่งเป็นอีเมลถึงผู้พัฒนาตรง ๆ ไม่เก็บลง DB"""
import io
from datetime import datetime
from html import escape

from fastapi import HTTPException, UploadFile, status
from starlette.datastructures import Headers

from app.core.config import settings
from app.models.user import User
from app.services import equipment_service
from app.utils import email as email_utils

ROLE_LABEL = {"student": "ผู้ยืม", "admin": "ผู้ดูแลคลัง", "superadmin": "ผู้ดูแลระบบสูงสุด"}
KIND_LABEL = {"bug": "แจ้งปัญหา", "suggestion": "ข้อเสนอแนะ"}
MAX_FILES = 3
_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}


async def send_feedback(
    user: User, kind: str, detail: str, page_url: str | None, user_agent: str | None, files: list[UploadFile],
) -> None:
    """ส่งรายงานปัญหา/ข้อเสนอแนะพร้อมรูปหลักฐานไปที่ FEEDBACK_EMAIL

    ตรวจรูปผ่าน `_read_validated()` จุดเดิม (นามสกุล + magic bytes + ขนาดก่อนอ่าน) · ข้อความผู้ใช้ escape ทุกช่อง
    อีเมลปิดอยู่ = 503 ให้ผู้ใช้รู้ว่ารายงานไปไม่ถึง (ไม่มีที่เก็บสำรอง) · reply-to = อีเมลผู้แจ้ง ตอบกลับได้ทันที
    """
    detail = detail.strip()  # Form(...) ไม่บังคับ StringConstraints ของ NonBlank — ตรวจเองที่นี่
    if not detail:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="กรุณากรอกรายละเอียด")
    if not email_utils.email_configured:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="ระบบอีเมลยังไม่เปิดใช้งาน ส่งรายงานไม่ได้ในขณะนี้ กรุณาแจ้งเจ้าหน้าที่โดยตรง")
    if len(files) > MAX_FILES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"แนบรูปได้ไม่เกิน {MAX_FILES} รูป")
    attachments = []
    for i, f in enumerate(files, 1):
        contents, ext = await equipment_service._read_validated(
            f, equipment_service.ALLOWED_IMAGE_EXT, equipment_service.MAX_IMAGE_BYTES)
        attachments.append({"file": UploadFile(
            filename=f"screenshot{i}{ext}", file=io.BytesIO(contents),
            headers=Headers({"content-type": _MIME[ext]}))})

    ident = user.student_id or user.username or "-"
    rows = [
        ("ประเภท", KIND_LABEL[kind]), ("ผู้แจ้ง", f"{user.full_name} ({ident})"),
        ("สิทธิ์", ROLE_LABEL.get(user.role, user.role)), ("อีเมล", user.email), ("เบอร์โทร", user.phone or "-"),
        ("หน้าที่เปิดอยู่", page_url or "-"), ("เบราว์เซอร์", user_agent or "-"),
        ("เวลา", datetime.now().strftime("%d/%m/%Y %H:%M")), ("รูปแนบ", f"{len(attachments)} รูป"),
    ]
    table = "".join(
        f'<tr><td style="color:#6b7280;padding:2px 12px 2px 0;vertical-align:top;">{k}</td><td>{escape(str(v))}</td></tr>'
        for k, v in rows)
    body = (f"<h2>{KIND_LABEL[kind]}จากผู้ใช้ระบบ</h2><table style=\"font-size:13px;\">{table}</table>"
            f'<p style="white-space:pre-wrap;padding:12px;background:#f9fafb;border-radius:8px;">{escape(detail)}</p>')
    summary = detail.splitlines()[0][:60]
    await email_utils.send_email(settings.FEEDBACK_EMAIL, f"{KIND_LABEL[kind]}: {summary}", body,
                                 attachments=attachments, reply_to=user.email, wait=True)
