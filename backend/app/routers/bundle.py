import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.bundle import BundleCreate, BundleResponse, BundleUpdate
from app.services import bundle_service

router = APIRouter(prefix="/bundles", tags=["bundles"])


@router.get("", response_model=list[BundleResponse])
async def list_bundles(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[BundleResponse]:
    """รายชุดอุปกรณ์ — นักศึกษาเห็นเฉพาะชุดที่เปิดใช้งาน แอดมินเห็นทั้งหมด"""
    return await bundle_service.list_bundles(db, active_only=current_user.role != "admin")


@router.post("", response_model=BundleResponse, status_code=201)
async def create_bundle(
    body: BundleCreate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> BundleResponse:
    return await bundle_service.create_bundle(db, admin, body)


@router.patch("/{bundle_id}", response_model=BundleResponse)
async def update_bundle(
    bundle_id: uuid.UUID,
    body: BundleUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> BundleResponse:
    return await bundle_service.update_bundle(db, admin, bundle_id, body)


@router.delete("/{bundle_id}", status_code=204)
async def delete_bundle(
    bundle_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    await bundle_service.delete_bundle(db, admin, bundle_id)
