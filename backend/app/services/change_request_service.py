"""คิวคำขอแก้ไขข้อมูล — ผู้ดูแลคลังยื่น ผู้ดูแลระบบสูงสุดตัดสิน (feedback อาจารย์ 5 ก.ย. 69)

ระบบ **ไม่รัน** อะไรจากคำขอเหล่านี้เอง — ผู้ดูแลระบบสูงสุดอ่านแล้วไปกดทำผ่านหน้าจอปกติ
(ซึ่งมี audit log ของมันเองอยู่แล้ว) จากนั้นกลับมาปิดงาน ตัวคิวนี้ทำหน้าที่เป็น "หลักฐานว่าใครขออะไร
เพราะอะไร และใครอนุมัติ" ซึ่งเดิมคุยกันทางไลน์แล้วไม่เหลือร่องรอย
"""
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.change_request import ChangeRequest
from app.models.user import User
from app.schemas.change_request import (
    ChangeRequestCreate,
    ChangeRequestResponse,
    PaginatedChangeRequests,
)
from app.services import audit_service
from app.utils.roles import SUPERADMIN, is_staff

OPEN_STATUS = "pending"
DECIDED_STATUSES = ("approved", "rejected")


async def create(db: AsyncSession, requester: User, body: ChangeRequestCreate) -> ChangeRequestResponse:
    """ยื่นคำขอแก้ไข — ผู้ดูแลคลังขึ้นไป (นักศึกษาไม่มีเรื่องต้องขอแก้ฐานข้อมูล)"""
    if not is_staff(requester):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    cr = ChangeRequest(
        requester_id=requester.id,
        requester_name=requester.full_name,
        target_table=body.target_table,
        target_id=body.target_id,
        target_label=body.target_label,
        reason=body.reason,
        detail=body.detail,
        status=OPEN_STATUS,
    )
    db.add(cr)
    await db.flush()
    await audit_service.log_action(db, requester, "create_change_request", "change_requests", cr.id, {
        "target_table": cr.target_table, "target_label": cr.target_label, "reason": cr.reason,
    })
    await db.commit()
    await db.refresh(cr)
    return ChangeRequestResponse.model_validate(cr)


async def list_requests(
    db: AsyncSession, current_user: User, page: int, page_size: int, filter_status: str | None
) -> PaginatedChangeRequests:
    """ผู้ดูแลระบบสูงสุดเห็นทุกคำขอ / ผู้ดูแลคลังเห็นเฉพาะที่ตัวเองยื่น"""
    query = select(ChangeRequest).order_by(ChangeRequest.created_at.desc())
    if current_user.role != SUPERADMIN:
        query = query.where(ChangeRequest.requester_id == current_user.id)
    if filter_status:
        query = query.where(ChangeRequest.status == filter_status)
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    rows = (await db.execute(query.offset((page - 1) * page_size).limit(page_size))).scalars().all()
    return PaginatedChangeRequests(
        items=[ChangeRequestResponse.model_validate(r) for r in rows],
        total=total, page=page, page_size=page_size,
    )


async def decide(
    db: AsyncSession, admin: User, request_id: uuid.UUID, new_status: str, note: str | None
) -> ChangeRequestResponse:
    """ปิดงานคำขอ — approved = ทำให้แล้ว, rejected = ไม่ทำให้ (ต้องมีเหตุผล)

    เรียกได้จาก endpoint ที่กัน require_superadmin ไว้แล้วเท่านั้น
    """
    if new_status not in DECIDED_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid decision.")
    cr = (await db.execute(select(ChangeRequest).where(ChangeRequest.id == request_id))).scalar_one_or_none()
    if not cr:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Change request not found.")
    if cr.status != OPEN_STATUS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="คำขอนี้ถูกตัดสินไปแล้ว")
    if new_status == "rejected" and not (note or "").strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="กรุณาระบุเหตุผลที่ไม่ดำเนินการ")

    cr.status = new_status
    cr.decided_by = admin.id
    cr.decided_by_name = admin.full_name
    cr.decided_at = datetime.now(timezone.utc)
    cr.decision_note = note
    await audit_service.log_action(db, admin, "decide_change_request", "change_requests", cr.id, {
        "target_label": cr.target_label, "changes": {"status": [OPEN_STATUS, new_status]},
        "reason": note,
    })
    await db.commit()
    await db.refresh(cr)
    return ChangeRequestResponse.model_validate(cr)
