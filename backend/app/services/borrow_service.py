import uuid
from datetime import date, datetime, timezone, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.borrow_item import BorrowItem
from app.models.borrow_request import BorrowRequest
from app.models.equipment import Equipment
from app.models.notification import Notification
from app.models.setting import Setting
from app.models.user import User
from app.schemas.borrow import (
    BorrowRequestCreate,
    BorrowRequestResponse,
    PaginatedBorrowRequests,
    ReturnItemRequest,
)


async def _get_setting_int(db: AsyncSession, key: str) -> int:
    """อ่านค่า int จาก settings — seed data ต้องมีครบ ดู alembic/versions/0002_seed_settings"""
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


async def _notify(
    db: AsyncSession,
    user_id: uuid.UUID,
    notif_type: str,
    message: str,
    borrow_request_id: uuid.UUID | None = None,
) -> None:
    """เพิ่ม in_app notification (commit โดย caller)"""
    db.add(Notification(
        user_id=user_id,
        borrow_request_id=borrow_request_id,
        type=notif_type,
        channel="in_app",
        message=message,
    ))


async def _load_request(db: AsyncSession, request_id: uuid.UUID) -> BorrowRequest:
    result = await db.execute(
        select(BorrowRequest)
        .options(selectinload(BorrowRequest.items).selectinload(BorrowItem.equipment))
        .where(BorrowRequest.id == request_id)
    )
    req = result.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found.")
    return req


async def create_request(
    db: AsyncSession, current_user: User, body: BorrowRequestCreate
) -> BorrowRequestResponse:
    """
    สร้างคำขอยืมใหม่ ตรวจสอบโควต้าและสต็อกก่อนสร้าง
    - เช็ค max_active_requests_per_student
    - เช็ค max_items_per_request
    - เช็ค quantity_available และ status ของแต่ละอุปกรณ์
    """
    max_active = await _get_setting_int(db, "max_active_requests_per_student")
    max_items = await _get_setting_int(db, "max_items_per_request")

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

    if len(body.items) == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Request must have at least 1 item.")
    if len(body.items) > max_items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot request more than {max_items} items at once.",
        )

    # ตรวจสอบ equipment ทุกรายการก่อน insert
    equipment_map: dict[uuid.UUID, Equipment] = {}
    for item_req in body.items:
        eq_result = await db.execute(select(Equipment).where(Equipment.id == item_req.equipment_id))
        eq = eq_result.scalar_one_or_none()
        if not eq:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Equipment {item_req.equipment_id} not found.",
            )
        if eq.quantity_available < item_req.quantity:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Equipment '{eq.name}' has insufficient stock (available: {eq.quantity_available}).",
            )
        # durable ที่ status != available ยืมไม่ได้
        if eq.item_type == "durable" and eq.status != "available":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Equipment '{eq.name}' is not available (status: {eq.status}).",
            )
        equipment_map[eq.id] = eq

    req = BorrowRequest(
        request_code=await _next_request_code(db),
        student_id=current_user.id,
        purpose=body.purpose,
        status="pending",
    )
    db.add(req)
    await db.flush()  # ได้ req.id

    for item_req in body.items:
        eq = equipment_map[item_req.equipment_id]
        db.add(BorrowItem(
            borrow_request_id=req.id,
            equipment_id=eq.id,
            item_type_snapshot=eq.item_type,
            quantity=item_req.quantity,
        ))

    # แจ้งเตือน admin ทุกคน
    admins = await db.execute(select(User).where(User.role == "admin", User.is_active == True))
    for admin in admins.scalars().all():
        await _notify(db, admin.id, "new_request_admin",
                      f"คำขอยืมใหม่ {req.request_code} จาก {current_user.full_name}",
                      borrow_request_id=req.id)

    await db.commit()

    # โหลด items กลับมาเพื่อ return response
    return await get_request(db, current_user, req.id)


async def list_requests(
    db: AsyncSession,
    current_user: User,
    page: int,
    page_size: int,
    filter_status: str | None,
    overdue_only: bool,
) -> PaginatedBorrowRequests:
    """นักศึกษาเห็นแค่ของตัวเอง / admin เห็นทั้งหมด"""
    query = select(BorrowRequest).options(selectinload(BorrowRequest.items))

    if current_user.role != "admin":
        query = query.where(BorrowRequest.student_id == current_user.id)
    if filter_status:
        query = query.where(BorrowRequest.status == filter_status)
    if overdue_only:
        query = query.where(BorrowRequest.is_overdue == True)

    query = query.order_by(BorrowRequest.requested_at.desc())

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar() or 0

    result = await db.execute(query.offset((page - 1) * page_size).limit(page_size))
    items = list(result.scalars().all())
    return PaginatedBorrowRequests(items=items, total=total, page=page, page_size=page_size)  # type: ignore


async def get_request(
    db: AsyncSession, current_user: User, request_id: uuid.UUID
) -> BorrowRequestResponse:
    """ดึงคำขอ + รายการอุปกรณ์ทั้งหมด ตรวจสอบว่าเป็นเจ้าของหรือ admin"""
    req = await _load_request(db, request_id)
    if current_user.role != "admin" and req.student_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    return BorrowRequestResponse.model_validate(req)


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
    - consumable: ตั้ง returned=True ทันที (เบิกแล้วไม่ต้องคืน)
    - ส่งแจ้งเตือนนักศึกษา
    """
    max_loan_days = await _get_setting_int(db, "max_loan_days_durable")
    req = await _load_request(db, request_id)

    if req.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot approve request with status '{req.status}'.",
        )

    now = datetime.now(timezone.utc)
    for item in req.items:
        eq = item.equipment
        if eq.quantity_available < item.quantity:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Equipment '{eq.name}' no longer has sufficient stock.",
            )
        eq.quantity_available -= item.quantity
        if item.item_type_snapshot == "consumable":
            # เบิกแล้วหักสต็อก ไม่ต้องคืน
            item.returned = True
            item.returned_at = now
            item.condition_on_return = "ok"

    req.status = "approved"
    req.approved_by = admin.id
    req.approved_at = now
    req.due_date = (now + timedelta(days=max_loan_days)).date()

    await _notify(db, req.student_id, "approved",
                  f"คำขอ {req.request_code} ได้รับการอนุมัติแล้ว กรุณาคืนภายใน {req.due_date}",
                  borrow_request_id=req.id)
    await db.commit()


async def reject_request(
    db: AsyncSession, admin: User, request_id: uuid.UUID, reason: str
) -> None:
    """ปฏิเสธคำขอ พร้อมบันทึกเหตุผล"""
    result = await db.execute(select(BorrowRequest).where(BorrowRequest.id == request_id))
    req = result.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found.")
    if req.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot reject request with status '{req.status}'.",
        )
    req.status = "rejected"
    req.rejection_reason = reason

    await _notify(db, req.student_id, "rejected",
                  f"คำขอ {req.request_code} ถูกปฏิเสธ: {reason}",
                  borrow_request_id=req.id)
    await db.commit()


async def renew_item(
    db: AsyncSession, current_user: User, request_id: uuid.UUID, item_id: uuid.UUID
) -> None:
    """ต่อเวลายืมรายการอุปกรณ์ เช็ค renewed_count < max_renew_count"""
    max_renew = await _get_setting_int(db, "max_renew_count")
    renew_days = await _get_setting_int(db, "max_renew_days")

    req_result = await db.execute(select(BorrowRequest).where(BorrowRequest.id == request_id))
    req = req_result.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found.")
    if current_user.role != "admin" and req.student_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    if req.status != "approved":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Can only renew approved requests.")

    item_result = await db.execute(
        select(BorrowItem).where(BorrowItem.id == item_id, BorrowItem.borrow_request_id == request_id)
    )
    item = item_result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found.")
    if item.returned:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Item already returned.")
    if item.renewed_count >= max_renew:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot renew more than {max_renew} time(s).",
        )

    # ต่อเวลาจาก extended_due_date ถ้ามี ไม่งั้นจาก request.due_date
    base_date = item.extended_due_date or req.due_date or date.today()
    item.extended_due_date = base_date + timedelta(days=renew_days)
    item.renewed_count += 1
    await db.commit()


async def return_item(
    db: AsyncSession, admin: User, request_id: uuid.UUID, item_id: uuid.UUID, body: ReturnItemRequest
) -> None:
    """
    ยืนยันรับคืนอุปกรณ์ (admin only):
    - บันทึก condition_on_return + damage_note
    - condition=ok → เพิ่ม quantity_available กลับ
    - ทุก item returned → request.status = completed
    """
    if body.condition_on_return not in ("ok", "damaged", "lost"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid condition value.")

    req = await _load_request(db, request_id)
    if req.status != "approved":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Request is not in approved status.")

    item = next((i for i in req.items if i.id == item_id), None)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found.")
    if item.returned:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Item already returned.")

    now = datetime.now(timezone.utc)
    item.returned = True
    item.returned_at = now
    item.condition_on_return = body.condition_on_return
    item.damage_note = body.damage_note

    if body.condition_on_return == "ok":
        item.equipment.quantity_available += item.quantity

    # ถ้าทุก item returned แล้ว → complete request
    # consumable ถูก auto-return ตอน approve แล้ว ดังนั้น all() ครอบคลุมทั้งหมด
    if all(i.returned for i in req.items):
        req.status = "completed"
        req.returned_at = now

    await _notify(db, req.student_id, "returned_confirmed",
                  f"รับคืนอุปกรณ์จากคำขอ {req.request_code} แล้ว",
                  borrow_request_id=req.id)
    await db.commit()


async def generate_pdf(
    db: AsyncSession, current_user: User, request_id: uuid.UUID
) -> bytes:
    """สร้าง PDF ใบยืม ตรวจสอบว่าเป็นเจ้าของหรือ admin"""
    from app.utils.pdf import generate_borrow_pdf
    req = await get_request(db, current_user, request_id)
    return generate_borrow_pdf(req)


async def send_manual_reminder(db: AsyncSession, request_id: uuid.UUID) -> None:
    """ส่ง reminder แบบ manual โดย admin"""
    result = await db.execute(select(BorrowRequest).where(BorrowRequest.id == request_id))
    req = result.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found.")
    if req.status != "approved":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Request is not active.")

    await _notify(db, req.student_id, "due_soon",
                  f"แจ้งเตือน: คำขอ {req.request_code} ครบกำหนดคืนวันที่ {req.due_date}",
                  borrow_request_id=req.id)
    await db.commit()
