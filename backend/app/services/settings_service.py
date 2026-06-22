from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.setting import Setting


async def list_settings(db: AsyncSession) -> list[Setting]:
    result = await db.execute(select(Setting).order_by(Setting.key))
    return list(result.scalars().all())


async def update_setting(db: AsyncSession, key: str, value: str) -> Setting:
    result = await db.execute(select(Setting).where(Setting.key == key))
    setting = result.scalar_one_or_none()
    if not setting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Setting '{key}' not found.")
    setting.value = value
    await db.commit()
    await db.refresh(setting)
    return setting
