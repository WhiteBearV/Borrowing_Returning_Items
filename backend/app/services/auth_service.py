from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import create_access_token, create_refresh_token, hash_password, verify_password
from app.models.auth_token import AuthToken
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse


async def register(db: AsyncSession, body: RegisterRequest) -> None:
    """ลงทะเบียนผู้ใช้ใหม่ ตรวจสอบ email domain และส่งลิงก์ยืนยัน email"""
    domain = body.email.split("@")[-1]
    if domain not in settings.allowed_email_domains_list:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Email domain '{domain}' is not allowed.",
        )
    result = await db.execute(select(User).where(User.email == body.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered.")

    user = User(
        full_name=body.full_name,
        student_id=body.student_id,
        email=body.email,
        password_hash=hash_password(body.password),
        role="student",
        major=body.major,
    )
    db.add(user)
    await db.flush()
    # TODO: สร้าง AuthToken + ส่งอีเมลยืนยัน
    await db.commit()


async def verify_email(db: AsyncSession, token: str) -> None:
    """ยืนยัน email จาก token ที่ส่งไปทางอีเมล"""
    result = await db.execute(
        select(AuthToken).where(AuthToken.token == token, AuthToken.token_type == "email_verify")
    )
    auth_token = result.scalar_one_or_none()
    if not auth_token or auth_token.used_at:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token.")
    # TODO: ตรวจสอบ expires_at, ตั้ง user.email_verified = True, บันทึก used_at
    await db.commit()


async def login(db: AsyncSession, body: LoginRequest) -> TokenResponse:
    """ตรวจสอบ credentials และคืน JWT access + refresh token"""
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials.")
    if not user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email not verified. Please check your inbox.",
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled.")

    access = create_access_token(str(user.id), extra={"role": user.role})
    refresh = create_refresh_token(str(user.id))
    return TokenResponse(access_token=access, refresh_token=refresh)


async def refresh_token(db: AsyncSession, token: str) -> TokenResponse:
    """แลก refresh token ใหม่เป็น access token"""
    # TODO: decode refresh token, ตรวจสอบ type == "refresh", คืน access token ใหม่
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented yet.")


async def forgot_password(db: AsyncSession, email: str) -> None:
    """ส่งลิงก์ reset password ทาง email (ถ้า email มีในระบบ)"""
    # TODO: หา user โดย email, สร้าง AuthToken type=password_reset, ส่งอีเมล
    pass


async def reset_password(db: AsyncSession, token: str, new_password: str) -> None:
    """ตั้งรหัสผ่านใหม่โดยใช้ token จากอีเมล"""
    # TODO: ตรวจสอบ token, hash new_password, อัปเดต user.password_hash
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented yet.")
