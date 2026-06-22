from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, require_admin
from app.models.user import User
from app.schemas.setting import SettingResponse, SettingUpdate
from app.services import settings_service

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=list[SettingResponse])
async def list_settings(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[SettingResponse]:
    return await settings_service.list_settings(db)


@router.patch("/{key}", response_model=SettingResponse)
async def update_setting(
    key: str,
    body: SettingUpdate,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> SettingResponse:
    return await settings_service.update_setting(db, key, body.value)
