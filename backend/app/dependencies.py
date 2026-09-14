from typing import AsyncGenerator

from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.security import decode_token
from app.models.user import User
from app.utils.roles import ROLE_LABEL_TH, SUPERADMIN, is_staff

bearer_scheme = HTTPBearer()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


LAST_SEEN_THROTTLE = timedelta(minutes=5)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """ตรวจสอบ JWT และคืน User object; raise 401 ถ้า token ไม่ถูกต้องหรือหมดอายุ"""
    token = credentials.credentials
    try:
        payload = decode_token(token)
        user_id: str = payload["sub"]
        if payload.get("type") != "access":
            raise ValueError
    except (JWTError, ValueError, KeyError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")
    if not user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email not verified. Please check your inbox.",
        )
    # บันทึกเวลาใช้งานล่าสุด — หน้าตรวจสอบระบบใช้ตอบว่า "ตอนนี้มีคนใช้อยู่กี่คน" (ระบบเป็น JWT ล้วน
    # ไม่มี session ฝั่งเซิร์ฟเวอร์ให้นับ) เขียนทุก LAST_SEEN_THROTTLE นาทีพอ ไม่ใช่ทุก request
    # เพราะหน้าเว็บ poll ทุก 4 วิ = เขียน DB ถี่มากโดยไม่ได้ความละเอียดเพิ่ม
    now = datetime.now(timezone.utc)
    if user.last_seen_at is None or (now - user.last_seen_at) > LAST_SEEN_THROTTLE:
        user.last_seen_at = now
        await db.commit()
    return user


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """ตรวจสอบว่าเป็นเจ้าหน้าที่ (ผู้ดูแลคลัง หรือ ผู้ดูแลระบบสูงสุด); raise 403 ถ้าไม่ใช่

    superadmin ผ่านด่านนี้เสมอ — สิทธิ์ต้องครอบของ admin ทั้งหมด ไม่ใช่แยกขา
    (จุดนี้จุดเดียวคุม 48 endpoint ที่ประกาศ Depends(require_admin) ไว้)
    """
    if not is_staff(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user


async def require_superadmin(current_user: User = Depends(get_current_user)) -> User:
    """เฉพาะผู้ดูแลระบบสูงสุด — ใช้กับงานที่ย้อนกลับไม่ได้/กระทบทั้งระบบ
    (แก้ settings, ลบถาวร, เปลี่ยนสิทธิ์ผู้ใช้) ดู app/utils/roles.py
    """
    if current_user.role != SUPERADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"ต้องเป็น{ROLE_LABEL_TH[SUPERADMIN]}เท่านั้นจึงจะทำรายการนี้ได้",
        )
    return current_user
