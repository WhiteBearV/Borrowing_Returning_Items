import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification
from app.schemas.notification import PaginatedNotifications


async def list_for_user(
    db: AsyncSession, user_id: uuid.UUID, page: int, page_size: int
) -> PaginatedNotifications:
    query = (
        select(Notification)
        .where(Notification.user_id == user_id, Notification.channel == "in_app")
        .order_by(Notification.sent_at.desc())
    )
    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar() or 0
    result = await db.execute(query.offset((page - 1) * page_size).limit(page_size))
    items = list(result.scalars().all())
    return PaginatedNotifications(items=items, total=total, page=page, page_size=page_size)  # type: ignore


async def mark_read(db: AsyncSession, user_id: uuid.UUID, notification_id: uuid.UUID) -> None:
    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == user_id,
        )
    )
    n = result.scalar_one_or_none()
    if not n:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found.")
    n.is_read = True
    await db.commit()


async def mark_all_read(db: AsyncSession, user_id: uuid.UUID) -> None:
    """ทำเครื่องหมายว่าอ่านแล้วทั้งหมดในคราวเดียว — เฉพาะของ user นี้ ไม่แตะของคนอื่น"""
    await db.execute(
        update(Notification)
        .where(Notification.user_id == user_id, Notification.is_read == False)  # noqa: E712
        .values(is_read=True)
    )
    await db.commit()


async def send_notification(
    db: AsyncSession,
    user_id: uuid.UUID,
    notif_type: str,
    channel: str,
    message: str,
    borrow_request_id: uuid.UUID | None = None,
) -> None:
    """สร้าง Notification record และส่งตาม channel"""
    n = Notification(
        user_id=user_id,
        borrow_request_id=borrow_request_id,
        type=notif_type,
        channel=channel,
        message=message,
    )
    db.add(n)
    # TODO: ถ้า channel == "email" ให้เรียก utils.email
    # TODO: ถ้า channel == "line" ให้เรียก LINE API
