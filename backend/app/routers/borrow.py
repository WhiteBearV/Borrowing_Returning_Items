import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.borrow import (
    BorrowRequestCreate,
    BorrowRequestResponse,
    PaginatedBorrowRequests,
    RejectRequest,
    RequestReturnRequest,
    ReturnItemRequest,
)
from app.services import borrow_service

router = APIRouter(prefix="/borrow-requests", tags=["borrow"])


@router.post("", response_model=BorrowRequestResponse, status_code=201)
async def create_borrow_request(
    body: BorrowRequestCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BorrowRequestResponse:
    return await borrow_service.create_request(db, current_user, body)


@router.get("", response_model=PaginatedBorrowRequests)
async def list_borrow_requests(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
    overdue_only: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedBorrowRequests:
    return await borrow_service.list_requests(db, current_user, page, page_size, status, overdue_only)


@router.get("/{request_id}", response_model=BorrowRequestResponse)
async def get_borrow_request(
    request_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BorrowRequestResponse:
    return await borrow_service.get_request(db, current_user, request_id)


@router.patch("/{request_id}/cancel")
async def cancel_borrow_request(
    request_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await borrow_service.cancel_request(db, current_user, request_id)
    return {"detail": "Request cancelled."}


@router.patch("/{request_id}/approve")
async def approve_borrow_request(
    request_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await borrow_service.approve_request(db, admin, request_id)
    return {"detail": "Request approved."}


@router.patch("/{request_id}/reject")
async def reject_borrow_request(
    request_id: uuid.UUID,
    body: RejectRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await borrow_service.reject_request(db, admin, request_id, body.rejection_reason)
    return {"detail": "Request rejected."}


@router.post("/{request_id}/items/{item_id}/renew")
async def renew_item(
    request_id: uuid.UUID,
    item_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await borrow_service.renew_item(db, current_user, request_id, item_id)
    return {"detail": "Renewal successful."}


@router.post("/{request_id}/request-return")
async def request_return(
    request_id: uuid.UUID,
    body: RequestReturnRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """นักศึกษาแจ้งขอคืน (ทีละชิ้น/หลายชิ้น/ทั้งหมด) — ยังไม่ใช่การคืนจริง แค่แจ้ง admin ให้มายืนยัน"""
    await borrow_service.request_return_items(db, current_user, request_id, body.item_ids)
    return {"detail": "Return request submitted."}


@router.post("/{request_id}/return-all")
async def return_all_items(
    request_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """รับคืนอุปกรณ์ทุกชิ้นพร้อมกัน (condition=ok) — admin เท่านั้น"""
    await borrow_service.return_all_items(db, admin, request_id)
    return {"detail": "All items returned."}


@router.post("/{request_id}/items/{item_id}/return")
async def return_item(
    request_id: uuid.UUID,
    item_id: uuid.UUID,
    body: ReturnItemRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """ยืนยันรับคืนอุปกรณ์ — admin เท่านั้น นักศึกษากดเองไม่ได้"""
    await borrow_service.return_item(db, admin, request_id, item_id, body)
    return {"detail": "Item returned."}


@router.get("/{request_id}/pdf")
async def download_pdf(
    request_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    pdf_bytes = await borrow_service.generate_pdf(db, current_user, request_id)
    return Response(content=pdf_bytes, media_type="application/pdf")


@router.get("/{request_id}/return-pdf")
async def download_return_pdf(
    request_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """ใบรับคืนอุปกรณ์ (สรุปสภาพเมื่อคืน)"""
    pdf_bytes = await borrow_service.generate_return_pdf(db, current_user, request_id)
    return Response(content=pdf_bytes, media_type="application/pdf")


@router.post("/preview-pdf")
async def preview_borrow_pdf(
    body: BorrowRequestCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """ร่างใบยืมจากตะกร้า ก่อนกดส่งคำขอจริง (ไม่บันทึกลง DB)"""
    pdf_bytes = await borrow_service.generate_preview_pdf(db, current_user, body)
    return Response(content=pdf_bytes, media_type="application/pdf")


@router.delete("/{request_id}", status_code=204)
async def delete_borrow_request(
    request_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """ลบประวัติการยืม — เฉพาะ completed / rejected / cancelled"""
    await borrow_service.delete_request(db, admin, request_id)
    return Response(status_code=204)


@router.post("/{request_id}/remind")
async def manual_remind(
    request_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await borrow_service.send_manual_reminder(db, request_id)
    return {"detail": "Reminder sent."}
