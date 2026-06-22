import uuid
from datetime import date, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.borrow_item import BorrowItem
from app.models.borrow_request import BorrowRequest
from app.models.equipment import Equipment
from app.models.setting import Setting
from app.models.user import User
from app.schemas.borrow import (
    BorrowRequestCreate,
    BorrowRequestResponse,
    PaginatedBorrowRequests,
    ReturnItemRequest,
)


async def _get_setting_int(db: AsyncSession, key: str) -> int:
    """อ่านค่า int จาก settings — seed data ต้องมีครบ ดู alembic/versions/seed_settings"""
    result = await db.execute(select(Setting).where(Setting.key == key))
    return int(result.scalar_one().value)


async def _next_request_code(db: AsyncSession) -> str:
    """สร้างรหัสคำขอแบบ REQ-YYYY-XXXX"""
    year = date.today().year
    result = await db.execute(
        select(func.count(BorrowRequest.id)).where(
            BorrowRequest.request_code.like(f"REQ-{year}-%")
        )
    )
    count = result.scalar() or 0
    return f"REQ-{year}-{count + 1:04d}"


async def create_request(
    db: AsyncSession, current_user: User, body: BorrowRequestCreate
) -> BorrowRequestResponse:
    """
    สร้างคำขอยืมใหม่ ตรวจสอบโควต้าและสต็อกก่อนสร้าง
    - เช็ค max_active_requests_per_student
    - เช็ค max_items_per_request
    - เช็ค quantity_available ของแต่ละอุปกรณ์
    """
    max_active = await _get_setting_int(db, "max_active_requests_per_student")
    max_items = await _get_setting_int(db, "max_items_per_request")

    # เช็คจำนวนคำขอที่ active อยู่
    active_count_result = await db.execute(
        select(func.count(BorrowRequest.id)).where(
            BorrowRequest.student_id == current_user.id,
            BorrowRequest.status.in_(["pending", "approved"]),
        )
    )
    if (active_count_result.scalar() or 0) >= max_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"You already have {max_active} active requests.",
        )

    if len(body.items) > max_items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot request more than {max_items} items at once.",
        )

    # TODO: ตรวจสอบ quantity_available ของแต่ละ equipment
    # TODO: สร้าง BorrowRequest + BorrowItems
    # TODO: ส่งแจ้งเตือน admin (new_request_admin)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented yet.")


async def list_requests(
    db: AsyncSession,
    current_user: User,
    page: int,
    page_size: int,
    filter_status: str | None,
    overdue_only: bool,
) -> PaginatedBorrowRequests:
    """นักศึกษาเห็นแค่ของตัวเอง / admin เห็นทั้งหมด"""
    # TODO: query + pagination
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented yet.")


async def get_request(
    db: AsyncSession, current_user: User, request_id: uuid.UUID
) -> BorrowRequestResponse:
    """ดึงคำขอ + รายการอุปกรณ์ทั้งหมด ตรวจสอบว่าเป็นเจ้าของหรือ admin"""
    result = await db.execute(
        select(BorrowRequest)
        .options(selectinload(BorrowRequest.items))
        .where(BorrowRequest.id == request_id)
    )
    req = result.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found.")
    if current_user.role != "admin" and req.student_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    return req  # type: ignore[return-value]


async def cancel_request(db: AsyncSession, current_user: User, request_id: uuid.UUID) -> None:
    """ยกเลิกคำขอที่ status=pending เท่านั้น"""
    result = await db.execute(select(BorrowRequest).where(BorrowRequest.id == request_id))
    req = result.scalar_one_or_none()
    if not req or req.student_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found.")
    if req.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only pending requests can be cancelled.",
        )
    req.status = "cancelled"
    await db.commit()


async def approve_request(db: AsyncSession, admin: User, request_id: uuid.UUID) -> None:
    """
    อนุมัติคำขอ:
    - ลด quantity_available ของทุก equipment ใน request
    - คำนวณ due_date = today + max_loan_days_durable
    - consumable item: ตั้ง returned=True ทันที
    - ส่งแจ้งเตือนนักศึกษา
    """
    max_loan_days = await _get_setting_int(db, "max_loan_days_durable")
    # TODO: implement full approval logic
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented yet.")


async def reject_request(
    db: AsyncSession, admin: User, request_id: uuid.UUID, reason: str
) -> None:
    """ปฏิเสธคำขอ พร้อมบันทึกเหตุผล"""
    # TODO: implement
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented yet.")


async def renew_item(
    db: AsyncSession, current_user: User, request_id: uuid.UUID, item_id: uuid.UUID
) -> None:
    """ต่อเวลายืม เช็ค renewed_count < max_renew_count"""
    max_renew = await _get_setting_int(db, "max_renew_count")
    renew_days = await _get_setting_int(db, "max_renew_days")
    # TODO: implement
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented yet.")


async def return_item(
    db: AsyncSession, admin: User, request_id: uuid.UUID, item_id: uuid.UUID, body: ReturnItemRequest
) -> None:
    """
    ยืนยันรับคืนอุปกรณ์ (admin only):
    - บันทึก condition_on_return
    - ถ้า condition=ok → เพิ่ม quantity_available กลับ
    - ถ้าทุก item returned → อัปเดต request.status=completed
    """
    # TODO: implement
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented yet.")


async def generate_pdf(
    db: AsyncSession, current_user: User, request_id: uuid.UUID
) -> bytes:
    """สร้าง PDF ใบยืม ตรวจสอบว่าเป็นเจ้าของหรือ admin"""
    from app.utils.pdf import generate_borrow_pdf
    req = await get_request(db, current_user, request_id)
    return generate_borrow_pdf(req)


async def send_manual_reminder(db: AsyncSession, request_id: uuid.UUID) -> None:
    """ส่ง reminder แบบ manual โดย admin"""
    # TODO: implement
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented yet.")
