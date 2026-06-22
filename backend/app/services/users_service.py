import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

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


async def update_status(db: AsyncSession, user_id: uuid.UUID, is_active: bool) -> User:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    user.is_active = is_active
    await db.commit()
    await db.refresh(user)
    return user
