import uuid

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth_token import AuthToken
from app.models.borrow_item import BorrowItem
from app.models.borrow_request import BorrowRequest
from app.models.notification import Notification
from app.models.user import User
from app.schemas.user import PaginatedUsers, UserUpdateRequest


async def update_profile(db: AsyncSession, user: User, body: UserUpdateRequest) -> User:
    if body.full_name is not None:
        user.full_name = body.full_name
    if body.major is not None:
        user.major = body.major
    await db.commit()
    await db.refresh(user)
    return user


async def list_users(
    db: AsyncSession, page: int, page_size: int, role: str | None, major: str | None
) -> PaginatedUsers:
    query = select(User)
    if role:
        query = query.where(User.role == role)
    if major:
        query = query.where(User.major == major)
    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar() or 0
    result = await db.execute(query.offset((page - 1) * page_size).limit(page_size))
    items = list(result.scalars().all())
    return PaginatedUsers(items=items, total=total, page=page, page_size=page_size)  # type: ignore


async def delete_user(db: AsyncSession, user_id: uuid.UUID) -> None:
    """ลบ user ที่ปิดใช้งานแล้วออกจาก DB พร้อม cascade (notifications, borrow history)"""
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    if user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ปิดใช้งานบัญชีก่อนลบ")

    # ลบ child records ตาม FK ก่อน
    req_ids = (await db.execute(
        select(BorrowRequest.id).where(BorrowRequest.student_id == user_id)
    )).scalars().all()
    for req_id in req_ids:
        await db.execute(delete(Notification).where(Notification.borrow_request_id == req_id))
        await db.execute(delete(BorrowItem).where(BorrowItem.borrow_request_id == req_id))
    await db.execute(delete(BorrowRequest).where(BorrowRequest.student_id == user_id))
    await db.execute(delete(Notification).where(Notification.user_id == user_id))
    await db.execute(delete(AuthToken).where(AuthToken.user_id == user_id))
    await db.execute(delete(User).where(User.id == user_id))
    await db.commit()


async def update_status(db: AsyncSession, user_id: uuid.UUID, is_active: bool) -> User:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    user.is_active = is_active
    await db.commit()
    await db.refresh(user)
    return user
