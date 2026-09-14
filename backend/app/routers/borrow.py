import uuid

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db, require_admin, require_superadmin
from app.models.user import User
from app.schemas.borrow import (
    ApproveRequest,
    BorrowRequestCreate,
    BorrowRequestResponse,
    CancelRequest,
    FineEditRequest,
    FineWaiveRequest,
    PaginatedBorrowRequests,
    RejectRequest,
    RenewRejectRequest,
    RenewRequestCreate,
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
    needs_attention: bool = Query(False),
    search: str | None = Query(None),
    own_only: bool = Query(False),
    item_type: str | None = Query(None),
    category_id: uuid.UUID | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedBorrowRequests:
    return await borrow_service.list_requests(
        db, current_user, page, page_size, status, overdue_only, needs_attention, search, own_only,
        item_type, category_id,
    )


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
    body: CancelRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """ยกเลิกคำขอของตัวเอง — บังคับเหตุผล (เก็บใน cancel_reason + audit)"""
    await borrow_service.cancel_request(db, current_user, request_id, body.reason)
    return {"detail": "Request cancelled."}


@router.patch("/{request_id}/approve")
async def approve_borrow_request(
    request_id: uuid.UUID,
    body: ApproveRequest | None = None,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """อนุมัติคำขอ — ไม่ส่ง body = อนุมัติทั้งใบ ส่ง body = ตัดสินรายชิ้น (อนุมัติ/ไม่อนุมัติ/แก้วันคืน)"""
    await borrow_service.approve_request(db, admin, request_id, body)
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


@router.post("/{request_id}/items/{item_id}/renew-request")
async def renew_request_item(
    request_id: uuid.UUID,
    item_id: uuid.UUID,
    body: RenewRequestCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """นักศึกษายื่นคำขอต่อเวลา (เลือกวันที่+เหตุผลเอง) — ยังไม่ใช่การต่อเวลาจริง แค่แจ้ง admin ให้มาอนุมัติ"""
    await borrow_service.request_renew_item(db, current_user, request_id, item_id, body.requested_date, body.reason)
    return {"detail": "Renewal request submitted."}


@router.post("/{request_id}/items/{item_id}/renew-approve")
async def renew_approve_item(
    request_id: uuid.UUID,
    item_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await borrow_service.approve_renew_item(db, admin, request_id, item_id)
    return {"detail": "Renewal approved."}


@router.post("/{request_id}/items/{item_id}/renew-reject")
async def renew_reject_item(
    request_id: uuid.UUID,
    item_id: uuid.UUID,
    body: RenewRejectRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await borrow_service.reject_renew_item(db, admin, request_id, item_id, body.rejection_reason)
    return {"detail": "Renewal rejected."}


@router.post("/{request_id}/request-return")
async def request_return(
    request_id: uuid.UUID,
    body: RequestReturnRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """นักศึกษาแจ้งขอคืนพร้อมนัดวัน-เวลา-สถานที่ — ยังไม่ใช่การคืนจริง แค่แจ้ง admin ให้มายืนยัน"""
    await borrow_service.request_return_items(
        db, current_user, request_id, body.item_ids, body.return_appoint_at, body.return_appoint_location)
    return {"detail": "Return request submitted."}


@router.post("/{request_id}/signed-form")
async def upload_signed_form(
    request_id: uuid.UUID,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """ผู้ยืมอัปโหลดใบยืมที่ปริ้นไปเซ็นแล้ว (PDF หรือรูปถ่าย) แทนการถือกระดาษมาแสดง

    ไฟล์เก็บในโฟลเดอร์ส่วนตัว ไม่มี URL สาธารณะ — คืนแค่ชื่อไฟล์ไว้ให้หน้าเว็บรู้ว่ามีไฟล์แล้ว
    """
    filename = await borrow_service.upload_signed_form(db, current_user, request_id, file)
    return {"signed_form_file": filename}


@router.get("/{request_id}/signed-form")
async def download_signed_form(
    request_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """เปิดดูใบยืมที่เซ็นแล้ว — เจ้าของคำขอหรือเจ้าหน้าที่เท่านั้น (ไฟล์มีลายเซ็น + ข้อมูลส่วนบุคคล)"""
    path, filename = await borrow_service.get_signed_form(db, current_user, request_id)
    return FileResponse(path, filename=filename)


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


@router.patch("/{request_id}/items/{item_id}/fine")
async def update_fine(
    request_id: uuid.UUID,
    item_id: uuid.UUID,
    body: FineEditRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """แก้ยอดค่าปรับที่ระบบคิดให้ (ต้องมีเหตุผล) — ได้เฉพาะรายการที่ยังค้างชำระ"""
    await borrow_service.update_fine(db, admin, request_id, item_id, body)
    return {"detail": "Fine updated."}


@router.patch("/{request_id}/items/{item_id}/fine/pay")
async def pay_fine(
    request_id: uuid.UUID,
    item_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """บันทึกว่าผู้ยืมชำระค่าปรับแล้ว"""
    await borrow_service.pay_fine(db, admin, request_id, item_id)
    return {"detail": "Fine marked as paid."}


@router.patch("/{request_id}/items/{item_id}/fine/waive")
async def waive_fine(
    request_id: uuid.UUID,
    item_id: uuid.UUID,
    body: FineWaiveRequest,
    superadmin: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """ยกเว้นค่าปรับ — superadmin เท่านั้น (เกี่ยวกับเงิน ย้อนกลับไม่ได้)"""
    await borrow_service.waive_fine(db, superadmin, request_id, item_id, body)
    return {"detail": "Fine waived."}


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
    admin: User = Depends(require_superadmin),
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
