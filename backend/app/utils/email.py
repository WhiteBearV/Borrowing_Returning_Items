import asyncio

from fastapi_mail import ConnectionConfig, FastMail, MessageSchema, MessageType, MultipartSubtypeEnum

from app.core.config import settings

# ปิดด้วย ENABLE_EMAIL=false หรือ MAIL_USERNAME ยังเป็น placeholder → print แทนส่งจริง
# main.py อ่านค่านี้ไปเตือนตอน startup ด้วย จะได้ไม่เผลอ deploy ทั้งที่อีเมลไม่ออก
_email_configured = settings.ENABLE_EMAIL and settings.MAIL_USERNAME not in ("", "your-email@example.com")
email_configured = _email_configured

mail_config = ConnectionConfig(
    MAIL_USERNAME=settings.MAIL_USERNAME or "dev",
    MAIL_PASSWORD=settings.MAIL_PASSWORD or "dev",
    # ต้องเป็นอีเมลที่ผ่าน validator ของ pydantic แม้ตอนไม่ได้ตั้งค่าจริง
    # ("dev@localhost" ไม่ผ่านเพราะไม่มีจุด ทำให้แอปบูตไม่ขึ้นเลยตอน deploy ที่ยังไม่ตั้ง SMTP)
    MAIL_FROM=settings.MAIL_FROM or "noreply@example.com",
    MAIL_PORT=settings.MAIL_PORT,
    MAIL_SERVER=settings.MAIL_SERVER,
    MAIL_STARTTLS=settings.MAIL_STARTTLS,
    MAIL_SSL_TLS=settings.MAIL_SSL_TLS,
    USE_CREDENTIALS=_email_configured,
    VALIDATE_CERTS=_email_configured,
    SUPPRESS_SEND=not _email_configured,
)
fm = FastMail(mail_config)


SUBJECT_PREFIX = "[ระบบอัตโนมัติ] "
AUTO_FOOTER = (
    '<hr style="border:none;border-top:1px solid #e5e7eb;margin-top:24px;"/>'
    '<p style="font-size:12px;color:#9ca3af;">อีเมลนี้ส่งจากระบบยืม-คืนอุปกรณ์โดยอัตโนมัติ กรุณาอย่าตอบกลับอีเมลนี้</p>'
)


_pending: set[asyncio.Task] = set()  # เก็บ reference ไว้ ไม่งั้น task ถูก GC ทิ้งกลางทาง


async def _deliver(message: MessageSchema, to: str) -> None:
    try:
        await fm.send_message(message)
    except Exception as e:  # ponytail: ส่งเบื้องหลังแล้ว ไม่มีใครรอผล — log ไว้ดูย้อนหลังพอ
        print(f"[email] ส่งถึง {to} ไม่สำเร็จ: {e}")


async def send_email(
    to: str, subject: str, body_html: str, attachments: list[dict] | None = None, reply_to: str | None = None,
    wait: bool = False,
) -> None:
    """ส่งอีเมล HTML — จุดเดียวที่เติมป้าย "[ระบบอัตโนมัติ]" หน้าหัวเรื่อง + ท้ายอีเมลว่าห้ามตอบกลับ (3 พ.ย. 69)

    ค่าเริ่มต้นส่งเบื้องหลังแล้วคืนทันที · wait=True = รอจนส่งเสร็จ (โยน error ให้ผู้เรียก — ใช้กับปุ่มแจ้งปัญหา)
    attachments = dict แบบ fastapi-mail ({"file": path|UploadFile, "headers": {...}}) — รูปที่อ้างด้วย
    `cid:` ใน body ต้องใส่ header Content-ID + Content-Disposition: inline (ส่งเป็น multipart/related)
    เพราะ <img src="http://IP-ภายใน/uploads/..."> Gmail ดึงจากนอกเครือข่ายคณะไม่ได้ รูปไม่ขึ้น
    """
    subject = SUBJECT_PREFIX + subject
    body_html += AUTO_FOOTER
    if not _email_configured:
        print(f"\n[DEV EMAIL] To: {to}\nSubject: {subject}\nAttachments: {len(attachments or [])}\n{body_html}\n")
        return
    message = MessageSchema(
        subject=subject,
        recipients=[to],
        body=body_html,
        subtype=MessageType.html,
        attachments=attachments or [],
        multipart_subtype=MultipartSubtypeEnum.related if attachments else MultipartSubtypeEnum.mixed,
        reply_to=[reply_to] if reply_to else [],
    )
    if wait:
        await fm.send_message(message)
        return
    # ส่งเบื้องหลัง (3 พ.ย. 69): SMTP Gmail ใช้ ~3 วิ/ฉบับ (ต่อ+TLS+login ทุกครั้ง) เดิม await ในคำขอเลย
    # กดยืม = รออีเมลถึงเจ้าหน้าที่ทุกคน+ผู้ยืมทีละฉบับ (~10 วิ) กดอนุมัติ ~3 วิ — Prod หน่วงเพราะตรงนี้ (dev ปิดอีเมลจึงไม่เห็น)
    # MessageSchema สร้างก่อน (อ่านไฟล์แนบตอนนี้) งานที่เหลือไม่แตะ DB session ของคำขอ
    task = asyncio.create_task(_deliver(message, to))
    _pending.add(task)
    task.add_done_callback(_pending.discard)


async def send_verification_email(to: str, token: str) -> None:
    verify_url = f"{settings.FRONTEND_URL}/verify-email?token={token}"
    html = f"""
    <h2>ยืนยันอีเมลของคุณ</h2>
    <p>คลิกลิงก์ด้านล่างเพื่อยืนยันอีเมล:</p>
    <a href="{verify_url}">{verify_url}</a>
    <p>ลิงก์นี้มีอายุ 24 ชั่วโมง</p>
    """
    await send_email(to, "ยืนยันอีเมล — ระบบยืม-คืนอุปกรณ์", html)


async def send_reset_password_email(to: str, token: str) -> None:
    reset_url = f"{settings.FRONTEND_URL}/reset-password?token={token}"
    html = f"""
    <h2>ตั้งรหัสผ่านใหม่</h2>
    <p>คลิกลิงก์ด้านล่างเพื่อตั้งรหัสผ่านใหม่:</p>
    <a href="{reset_url}">{reset_url}</a>
    <p>ลิงก์นี้มีอายุ 1 ชั่วโมง</p>
    """
    await send_email(to, "ตั้งรหัสผ่านใหม่ — ระบบยืม-คืนอุปกรณ์", html)
