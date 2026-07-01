import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.equipment import (
    CategoryCreate,
    CategoryResponse,
    EquipmentCreate,
    EquipmentResponse,
    EquipmentUpdate,
    PaginatedEquipment,
)
from app.services import equipment_service

router = APIRouter(tags=["equipment"])


@router.get("/equipment", response_model=PaginatedEquipment)
async def list_equipment(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category_id: uuid.UUID | None = Query(None),
    item_type: str | None = Query(None),
    status: str | None = Query(None),
    search: str | None = Query(None),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedEquipment:
    return await equipment_service.list_equipment(db, page, page_size, category_id, item_type, status, search)


@router.get("/equipment/{equipment_id}", response_model=EquipmentResponse)
async def get_equipment(
    equipment_id: uuid.UUID,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EquipmentResponse:
    return await equipment_service.get_equipment(db, equipment_id)


@router.post("/equipment", response_model=EquipmentResponse, status_code=201)
async def create_equipment(
    body: EquipmentCreate,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> EquipmentResponse:
    return await equipment_service.create_equipment(db, body)


@router.patch("/equipment/{equipment_id}", response_model=EquipmentResponse)
async def update_equipment(
    equipment_id: uuid.UUID,
    body: EquipmentUpdate,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> EquipmentResponse:
    return await equipment_service.update_equipment(db, equipment_id, body)


@router.delete("/equipment/{equipment_id}", status_code=204)
async def retire_equipment(
    equipment_id: uuid.UUID,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await equipment_service.retire_equipment(db, equipment_id)
    return Response(status_code=204)


@router.delete("/equipment/{equipment_id}/permanent", status_code=204)
async def delete_equipment_permanent(
    equipment_id: uuid.UUID,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await equipment_service.delete_equipment(db, equipment_id)
    return Response(status_code=204)


@router.get("/equipment/{equipment_id}/qrcode")
async def get_qrcode(
    equipment_id: uuid.UUID,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    png_bytes = await equipment_service.generate_qr(db, equipment_id)
    return Response(content=png_bytes, media_type="image/png")


@router.get("/equipment-categories", response_model=list[CategoryResponse])
async def list_categories(
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CategoryResponse]:
    return await equipment_service.list_categories(db)


@router.post("/equipment-categories", response_model=CategoryResponse, status_code=201)
async def create_category(
    body: CategoryCreate,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> CategoryResponse:
    return await equipment_service.create_category(db, body)
