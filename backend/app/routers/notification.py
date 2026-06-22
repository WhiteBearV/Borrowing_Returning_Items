import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.notification import PaginatedNotifications
from app.services import notification_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("/me", response_model=PaginatedNotifications)
async def list_my_notifications(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedNotifications:
    return await notification_service.list_for_user(db, current_user.id, page, page_size)


@router.patch("/{notification_id}/read")
async def mark_read(
    notification_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await notification_service.mark_read(db, current_user.id, notification_id)
    return {"detail": "Marked as read."}
