import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import create_access_token, create_refresh_token, decode_token, hash_password, verify_password
from app.models.auth_token import AuthToken
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse
from app.utils.email import send_reset_password_email, send_verification_email


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
        email_verified=settings.DEV_AUTO_VERIFY_EMAIL,  # True ได้เฉพาะตั้ง DEV_AUTO_VERIFY_EMAIL=true ใน .env
    )
    db.add(user)
    await db.flush()  # ได้ user.id ก่อน commit

    token_str = secrets.token_urlsafe(32)
    auth_token = AuthToken(
        user_id=user.id,
        token=token_str,
        token_type="email_verify",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    db.add(auth_token)
    await db.commit()

    await send_verification_email(body.email, token_str)


async def verify_email(db: AsyncSession, token: str) -> None:
    """ยืนยัน email จาก token ที่ส่งไปทางอีเมล"""
    result = await db.execute(
        select(AuthToken).where(AuthToken.token == token, AuthToken.token_type == "email_verify")
    )
    auth_token = result.scalar_one_or_none()
    if not auth_token or auth_token.used_at or auth_token.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token.")

    user_result = await db.execute(select(User).where(User.id == auth_token.user_id))
    user = user_result.scalar_one()
    user.email_verified = True
    auth_token.used_at = datetime.now(timezone.utc)
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
    """แลก refresh token เป็น access token ใหม่"""
    try:
        payload = decode_token(token)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token.")
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type.")

    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or disabled.")

    access = create_access_token(str(user.id), extra={"role": user.role})
    return TokenResponse(access_token=access, refresh_token=token)  # refresh token เดิมยังใช้ได้จนหมดอายุ


async def forgot_password(db: AsyncSession, email: str) -> None:
    """ส่งลิงก์ reset password ทาง email — ถ้า email ไม่มีในระบบก็ไม่บอก (ป้องกัน user enumeration)"""
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        return  # ponytail: silent return ป้องกัน user enumeration

    token_str = secrets.token_urlsafe(32)
    auth_token = AuthToken(
        user_id=user.id,
        token=token_str,
        token_type="password_reset",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db.add(auth_token)
    await db.commit()
    await send_reset_password_email(email, token_str)


async def reset_password(db: AsyncSession, token: str, new_password: str) -> None:
    """ตั้งรหัสผ่านใหม่โดยใช้ token จากอีเมล"""
    result = await db.execute(
        select(AuthToken).where(AuthToken.token == token, AuthToken.token_type == "password_reset")
    )
    auth_token = result.scalar_one_or_none()
    if not auth_token or auth_token.used_at or auth_token.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token.")

    user_result = await db.execute(select(User).where(User.id == auth_token.user_id))
    user = user_result.scalar_one()
    user.password_hash = hash_password(new_password)
    auth_token.used_at = datetime.now(timezone.utc)
    await db.commit()
