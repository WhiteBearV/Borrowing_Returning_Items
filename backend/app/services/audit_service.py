import uuid
from datetime import date, datetime, time

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import TZ
from app.models.audit_log import AuditLog
from app.models.user import User
from app.schemas.audit import AuditLogResponse, PaginatedAuditLogs


async def list_logs(
    db: AsyncSession, page: int, page_size: int, action: str | None,
    date_from: date | None = None, date_to: date | None = None,
) -> PaginatedAuditLogs:
    # actor_name/identifier เป็น snapshot column แล้ว ไม่ต้อง join user
    query = select(AuditLog).order_by(AuditLog.created_at.desc())
    if action:
        query = query.where(AuditLog.action == action)
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="date_from must be <= date_to.")
    if date_from:
        query = query.where(AuditLog.created_at >= datetime.combine(date_from, time.min, tzinfo=TZ))
    if date_to:
        query = query.where(AuditLog.created_at <= datetime.combine(date_to, time.max, tzinfo=TZ))
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    rows = (await db.execute(query.offset((page - 1) * page_size).limit(page_size))).scalars().all()
    return PaginatedAuditLogs(
        items=[AuditLogResponse.model_validate(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


def diff_fields(entity, changed: dict) -> dict[str, list]:
    """เทียบค่าฟิลด์เดิม (ก่อน setattr) กับค่าใหม่ใน `changed` คืนเฉพาะฟิลด์ที่ค่าเปลี่ยนจริง รูปแบบ
    {field: [old, new]} — เดินตาม pattern เดียวกับ import_service.diff_rows ที่ทำ diff แบบนี้อยู่แล้ว
    เรียกก่อน setattr loop เสมอ — อ่านค่าเดิมจาก entity ก่อนถูกเขียนทับ
    """
    diffs: dict[str, list] = {}
    for field, new_value in changed.items():
        old_value = getattr(entity, field, None)
        if old_value != new_value:
            diffs[field] = [old_value, new_value]
    return diffs


async def log_action(
    db: AsyncSession,
    actor: User,
    action: str,
    target_table: str,
    target_id: uuid.UUID,
    detail: dict | None = None,
) -> None:
    """บันทึกการกระทำของ admin ลง audit_logs

    snapshot ชื่อ/รหัสผู้ทำไว้ในตัว log เลย เพื่อให้รู้ว่าใครทำแม้ user จะถูกลบภายหลัง
    (audit trail ต้องลบไม่ได้ด้วยการลบบัญชี)
    """
    db.add(AuditLog(
        actor_id=actor.id,
        actor_name=actor.full_name,
        actor_identifier=actor.student_id or actor.username or actor.email,
        action=action, target_table=target_table, target_id=target_id, detail=detail,
    ))
