import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.equipment import (
    AdjustStockRequest,
    BulkDeleteRequest,
    BulkDeleteResult,
    BulkRetireRequest,
    BulkRetireResult,
    BulkUpdateRequest,
    BulkUpdateResult,
    CategoryCreate,
    CategoryResponse,
    EquipmentCreate,
    EquipmentDetailResponse,
    EquipmentGroupDetailResponse,
    EquipmentResponse,
    EquipmentUpdate,
    ImportCommitRequest,
    PaginatedEquipment,
    PaginatedEquipmentGroup,
    PhysicalAuditRequest,
    RestockRequest,
)
from app.services import equipment_service, import_service

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


@router.get("/equipment/grouped", response_model=PaginatedEquipmentGroup)
async def list_equipment_grouped(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category_id: uuid.UUID | None = Query(None),
    item_type: str | None = Query(None),
    status: str | None = Query(None),
    search: str | None = Query(None),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedEquipmentGroup:
    """เหมือน /equipment แต่ยุบอุปกรณ์รุ่นเดียวกันหลายหน่วยเป็นการ์ดเดียว — หน้ายืมของนักศึกษาใช้ตัวนี้"""
    return await equipment_service.list_equipment_grouped(db, page, page_size, category_id, item_type, status, search)


@router.get("/equipment/grouped/{equipment_id}", response_model=EquipmentGroupDetailResponse)
async def get_equipment_group_detail(
    equipment_id: uuid.UUID,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EquipmentGroupDetailResponse:
    return await equipment_service.get_equipment_group_detail(db, equipment_id)


@router.get("/equipment/repair-document")
async def repair_document(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """ดาวน์โหลด PDF บันทึกขออนุมัติซ่อมแซมครุภัณฑ์ (ครุภัณฑ์ที่ชำรุด/กำลังซ่อมทั้งหมด)"""
    pdf_bytes = await equipment_service.build_repair_document(db, admin)
    return Response(content=pdf_bytes, media_type="application/pdf")


@router.get("/equipment/stock-document")
async def stock_document(
    kind: str = Query(..., pattern="^(receipt|disposal)$"),
    date_from: date = Query(...),
    date_to: date = Query(...),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """ดาวน์โหลด PDF ใบรับเข้าคลัง (receipt) / ใบปลดระวาง (disposal) ตามช่วงวันที่"""
    pdf_bytes = await equipment_service.build_stock_document(db, admin, kind, date_from, date_to)
    return Response(content=pdf_bytes, media_type="application/pdf")


@router.post("/equipment/import/preview")
async def import_preview(
    file: UploadFile,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """อัปโหลดไฟล์ทะเบียน (Excel) → คืนร่างว่าจะเพิ่ม/แก้/ปลดระวางอะไรบ้าง (ยังไม่บันทึก)"""
    return await import_service.preview_import(db, file)


@router.post("/equipment/import/{import_id}/commit")
async def import_commit(
    import_id: str,
    body: ImportCommitRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """บันทึกร่างที่แอดมินตรวจ/แก้แล้วเข้าระบบจริง (เฉพาะบรรทัดที่ส่งมา)"""
    return await import_service.commit_import(db, admin, import_id, body)


@router.post("/equipment/bulk-delete", response_model=BulkDeleteResult)
async def bulk_delete_equipment(
    body: BulkDeleteRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> BulkDeleteResult:
    """ลบถาวรหลายรายการพร้อมกันแบบ best-effort — ชิ้นที่ลบไม่ได้ (เช่นยังไม่ปลดระวาง) ไม่บล็อกชิ้นอื่น"""
    return await equipment_service.bulk_delete_equipment(db, admin, body.equipment_ids)


@router.post("/equipment/bulk-retire", response_model=BulkRetireResult)
async def bulk_retire_equipment(
    body: BulkRetireRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> BulkRetireResult:
    """ปลดระวางหลายรายการพร้อมกันแบบ best-effort — เหตุผลเดียวกันใช้กับทุกชิ้นที่เลือก"""
    return await equipment_service.bulk_retire_equipment(db, admin, body.equipment_ids, body.reason)


@router.patch("/equipment/bulk-update", response_model=BulkUpdateResult)
async def bulk_update_equipment(
    body: BulkUpdateRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> BulkUpdateResult:
    """แก้ไขฟิลด์ปลอดภัย (location/description/status ฯลฯ) ของหลายหน่วยพร้อมกัน — all-or-nothing"""
    return await equipment_service.bulk_update_equipment(db, admin, body.equipment_ids, body.update)


@router.get("/equipment/{equipment_id}", response_model=EquipmentDetailResponse)
async def get_equipment(
    equipment_id: uuid.UUID,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EquipmentDetailResponse:
    eq = await equipment_service.get_equipment(db, equipment_id)
    holders = list((await equipment_service.get_holders_map(db, [equipment_id])).values())
    base = EquipmentResponse.model_validate(eq, from_attributes=True)
    return EquipmentDetailResponse(**base.model_dump(), holders=holders)


@router.post("/equipment/upload-image")
async def upload_equipment_image(
    file: UploadFile,
    _admin: User = Depends(require_admin),
) -> dict[str, str]:
    """อัปโหลดรูปอุปกรณ์ คืน image_url สำหรับใส่ตอนสร้าง/แก้ไขอุปกรณ์"""
    return {"image_url": await equipment_service.save_image(file)}


@router.post("/equipment", response_model=EquipmentResponse, status_code=201)
async def create_equipment(
    body: EquipmentCreate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> EquipmentResponse:
    return await equipment_service.create_equipment(db, admin, body)


@router.patch("/equipment/{equipment_id}", response_model=EquipmentResponse)
async def update_equipment(
    equipment_id: uuid.UUID,
    body: EquipmentUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> EquipmentResponse:
    return await equipment_service.update_equipment(db, admin, equipment_id, body)


@router.delete("/equipment/{equipment_id}", status_code=204)
async def retire_equipment(
    equipment_id: uuid.UUID,
    reason: str | None = Query(None),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await equipment_service.retire_equipment(db, admin, equipment_id, reason)
    return Response(status_code=204)


@router.post("/equipment/{equipment_id}/split", response_model=list[EquipmentResponse])
async def split_equipment(
    equipment_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[EquipmentResponse]:
    """แยกวัสดุ (material) ก้อนเดียวที่ quantity_total > 1 เป็นรายชิ้นคนละรหัส — เฉพาะที่ไม่มีของยืมอยู่"""
    return await equipment_service.split_equipment_into_units(db, admin, equipment_id)


@router.post("/equipment/{equipment_id}/restock", response_model=list[EquipmentResponse])
async def restock_equipment(
    equipment_id: uuid.UUID,
    body: RestockRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[EquipmentResponse]:
    """เติมของเข้าคลัง (ซื้อเพิ่ม) — บวกจำนวนที่ซื้อเพิ่มเข้าไปตรง ๆ ไม่ต้องคำนวณยอดรวมใหม่เอง"""
    return await equipment_service.restock_equipment(db, admin, equipment_id, body.count)


@router.post("/equipment/{equipment_id}/audit", response_model=EquipmentResponse)
async def audit_equipment(
    equipment_id: uuid.UUID,
    body: PhysicalAuditRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> EquipmentResponse:
    """บันทึกว่าตรวจนับอุปกรณ์ชิ้นนี้ทางกายภาพแล้ว (เจอของจริงตรงตำแหน่งที่บันทึกไว้)"""
    return await equipment_service.physical_audit_equipment(db, admin, equipment_id, body.note, body.photo_urls)


@router.post("/equipment/{equipment_id}/adjust-stock", response_model=EquipmentResponse)
async def adjust_stock_equipment(
    equipment_id: uuid.UUID,
    body: AdjustStockRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> EquipmentResponse:
    """ปรับยอดคงเหลือให้ตรงกับการนับจริง — ต่างจาก restock ตรงที่ไม่บวกเพิ่ม แต่ SET ค่าตรง ๆ"""
    return await equipment_service.adjust_stock(db, admin, equipment_id, body.new_available, body.reason, body.photo_urls)


@router.delete("/equipment/{equipment_id}/permanent", status_code=204)
async def delete_equipment_permanent(
    equipment_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await equipment_service.delete_equipment(db, admin, equipment_id)
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


@router.patch("/equipment-categories/{category_id}", response_model=CategoryResponse)
async def update_category(
    category_id: uuid.UUID,
    body: CategoryCreate,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> CategoryResponse:
    return await equipment_service.update_category(db, category_id, body)


@router.delete("/equipment-categories/{category_id}", status_code=204)
async def delete_category(
    category_id: uuid.UUID,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await equipment_service.delete_category(db, category_id)
    return Response(status_code=204)
