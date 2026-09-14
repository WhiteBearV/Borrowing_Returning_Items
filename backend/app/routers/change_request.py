import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, require_admin, require_superadmin
from app.models.user import User
from app.schemas.change_request import (
    ChangeRequestCreate,
    ChangeRequestDecision,
    ChangeRequestResponse,
    PaginatedChangeRequests,
)
from app.services import change_request_service, system_check_service

router = APIRouter(prefix="/change-requests", tags=["change-requests"])


@router.post("", response_model=ChangeRequestResponse, status_code=201)
async def create_change_request(
    body: ChangeRequestCreate,
    staff: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ChangeRequestResponse:
    """ผู้ดูแลคลังยื่นคำขอให้ผู้ดูแลระบบสูงสุดแก้ข้อมูลให้ (มีบันทึกเป็นหลักฐาน)"""
    return await change_request_service.create(db, staff, body)


@router.get("", response_model=PaginatedChangeRequests)
async def list_change_requests(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
    staff: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> PaginatedChangeRequests:
    """ผู้ดูแลระบบสูงสุดเห็นทุกคำขอ ผู้ดูแลคลังเห็นเฉพาะของตัวเอง"""
    return await change_request_service.list_requests(db, staff, page, page_size, status)


@router.patch("/{request_id}/approve", response_model=ChangeRequestResponse)
async def approve_change_request(
    request_id: uuid.UUID,
    body: ChangeRequestDecision,
    admin: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> ChangeRequestResponse:
    """ปิดงานว่า "ทำให้แล้ว" — การแก้ข้อมูลจริงทำผ่านหน้าจอปกติ ระบบไม่รันอะไรจากคำขอนี้เอง"""
    return await change_request_service.decide(db, admin, request_id, "approved", body.decision_note)


@router.patch("/{request_id}/reject", response_model=ChangeRequestResponse)
async def reject_change_request(
    request_id: uuid.UUID,
    body: ChangeRequestDecision,
    admin: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> ChangeRequestResponse:
    return await change_request_service.decide(db, admin, request_id, "rejected", body.decision_note)


# ── หน้าตรวจสุขภาพข้อมูล (อ่านอย่างเดียว) ───────────────────────────────────────
# อยู่ไฟล์เดียวกับคิวคำขอแก้ไขเพราะเป็นเครื่องมือของผู้ดูแลระบบสูงสุดชุดเดียวกัน
# (ponytail: ยังไม่ต้องแตก router ใหม่สำหรับ endpoint เดียว)

@router.get("/system-check", include_in_schema=True)
async def system_check(
    _admin: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """นับแถวทุกตาราง + รายการข้อมูลที่ผิดปกติ — query ตายตัวทั้งหมด ไม่รับ SQL จากผู้ใช้"""
    return await system_check_service.run_checks(db)
