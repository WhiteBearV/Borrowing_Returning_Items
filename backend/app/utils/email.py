from fastapi_mail import ConnectionConfig, FastMail, MessageSchema, MessageType

from app.core.config import settings

mail_config = ConnectionConfig(
    MAIL_USERNAME=settings.MAIL_USERNAME,
    MAIL_PASSWORD=settings.MAIL_PASSWORD,
    MAIL_FROM=settings.MAIL_FROM,
    MAIL_PORT=settings.MAIL_PORT,
    MAIL_SERVER=settings.MAIL_SERVER,
    MAIL_STARTTLS=settings.MAIL_STARTTLS,
    MAIL_SSL_TLS=settings.MAIL_SSL_TLS,
    USE_CREDENTIALS=True,
    VALIDATE_CERTS=True,
)

fm = FastMail(mail_config)


async def send_email(to: str, subject: str, body_html: str) -> None:
    """ส่งอีเมล HTML"""
    message = MessageSchema(
        subject=subject,
        recipients=[to],
        body=body_html,
        subtype=MessageType.html,
    )
    await fm.send_message(message)


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
