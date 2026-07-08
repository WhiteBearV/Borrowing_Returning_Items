import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.user import User
from app.schemas.audit import AuditLogResponse, PaginatedAuditLogs


async def list_logs(db: AsyncSession, page: int, page_size: int, action: str | None) -> PaginatedAuditLogs:
    # actor_name/identifier เป็น snapshot column แล้ว ไม่ต้อง join user
    query = select(AuditLog).order_by(AuditLog.created_at.desc())
    if action:
        query = query.where(AuditLog.action == action)
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    rows = (await db.execute(query.offset((page - 1) * page_size).limit(page_size))).scalars().all()
    return PaginatedAuditLogs(
        items=[AuditLogResponse.model_validate(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


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
