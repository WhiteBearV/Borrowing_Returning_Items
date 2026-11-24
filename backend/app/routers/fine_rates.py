"""ป้ายอัตราค่าปรับคืนเกินกำหนด — ดู: เจ้าหน้าที่ (ใช้เลือกในฟอร์มอุปกรณ์) · สร้าง/แก้/ลบ: ผู้ดูแลสูงสุด"""
import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, require_admin, require_superadmin
from app.models.user import User
from app.schemas.fine_rate import FineRateCreate, FineRateResponse, FineRateUpdate
from app.services import fine_rate_service

router = APIRouter(prefix="/fine-rates", tags=["fine-rates"])


@router.get("", response_model=list[FineRateResponse])
async def list_rates(_admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> list[FineRateResponse]:
    return await fine_rate_service.list_rates(db)


@router.post("", response_model=FineRateResponse, status_code=201)
async def create_rate(
    body: FineRateCreate, actor: User = Depends(require_superadmin), db: AsyncSession = Depends(get_db),
) -> FineRateResponse:
    return await fine_rate_service.create_rate(db, actor, body)


@router.patch("/{rate_id}", response_model=FineRateResponse)
async def update_rate(
    rate_id: uuid.UUID, body: FineRateUpdate,
    actor: User = Depends(require_superadmin), db: AsyncSession = Depends(get_db),
) -> FineRateResponse:
    return await fine_rate_service.update_rate(db, actor, rate_id, body)


@router.delete("/{rate_id}", status_code=204)
async def delete_rate(
    rate_id: uuid.UUID, actor: User = Depends(require_superadmin), db: AsyncSession = Depends(get_db),
) -> Response:
    await fine_rate_service.delete_rate(db, actor, rate_id)
    return Response(status_code=204)
