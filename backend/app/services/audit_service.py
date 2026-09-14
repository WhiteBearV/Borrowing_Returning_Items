import decimal
import uuid
from datetime import date, datetime, time

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import TZ
from app.models.audit_log import AuditLog
from app.models.user import User
from app.schemas.audit import AuditLogResponse, PaginatedAuditLogs
from app.utils.identity import user_identifier


def _filtered_query(
    action: str | None, date_from: date | None, date_to: date | None,
    target_id: uuid.UUID | None, target_table: str | None,
    actor: str | None, actor_role: str | None,
):
    """สร้าง query ที่ใส่ตัวกรองครบแล้ว — ใช้ร่วมกันระหว่างการแสดงผลแบบแบ่งหน้าและการ export CSV
    เพื่อให้ไฟล์ที่ export ได้ตรงกับสิ่งที่เห็นบนหน้าจอเสมอ (ไม่ใช่กรองคนละชุด)"""
    # actor_name/identifier เป็น snapshot column แล้ว ไม่ต้อง join user
    query = select(AuditLog).order_by(AuditLog.created_at.desc())
    if action:
        query = query.where(AuditLog.action == action)
    if target_table:
        query = query.where(AuditLog.target_table == target_table)
    if actor:
        pattern = f"%{actor}%"
        query = query.where(or_(AuditLog.actor_name.ilike(pattern),
                                AuditLog.actor_identifier.ilike(pattern)))
    if actor_role:
        query = query.where(AuditLog.actor_role == actor_role)
    if target_id:
        # bulk_update_equipment เขียน log เดียวต่อ batch (target_id = แถวแรก) แล้วเก็บ id ที่เหลือไว้ใน
        # detail["equipment_ids"] — ถ้ากรองแค่ target_id ประวัติของหน่วยที่ 2 เป็นต้นไปจะหายเงียบ ๆ
        # ทั้งที่ถูกแก้จริง (เช่น "ย้ายทั้ง 12 หน่วยไปห้อง 15399" จะเห็นแค่หน่วยแรก)
        query = query.where(or_(
            AuditLog.target_id == target_id,
            AuditLog.detail["equipment_ids"].contains([str(target_id)]),
        ))
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="date_from must be <= date_to.")
    if date_from:
        query = query.where(AuditLog.created_at >= datetime.combine(date_from, time.min, tzinfo=TZ))
    if date_to:
        query = query.where(AuditLog.created_at <= datetime.combine(date_to, time.max, tzinfo=TZ))
    return query


async def list_logs(
    db: AsyncSession, page: int, page_size: int, action: str | None,
    date_from: date | None = None, date_to: date | None = None,
    target_id: uuid.UUID | None = None, target_table: str | None = None,
    actor: str | None = None, actor_role: str | None = None,
) -> PaginatedAuditLogs:
    """รายการ audit log — กรองด้วย target_id เพื่อดู "ประวัติของอุปกรณ์ชิ้นนี้" ได้โดยตรง

    ขอบเขตที่ตั้งใจไม่ครอบ: การอนุมัติ/รับคืนถูกบันทึกด้วย target_table = borrow_requests/borrow_items
    จึงไม่โผล่ในประวัติของอุปกรณ์ — ข้อมูลนั้นดูได้จากผู้ครอบครองในหน้าอุปกรณ์อยู่แล้ว
    """
    query = _filtered_query(action, date_from, date_to, target_id, target_table, actor, actor_role)
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    rows = (await db.execute(query.offset((page - 1) * page_size).limit(page_size))).scalars().all()
    return PaginatedAuditLogs(
        items=[AuditLogResponse.model_validate(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


def _jsonable(v):
    """ทำให้ค่าลงคอลัมน์ JSONB ได้ — ค่าที่อ่านจาก ORM ไม่ใช่ชนิดพื้นฐานเสมอไป

    Numeric -> Decimal, Date/DateTime -> date/datetime, UUID -> UUID ซึ่ง json.dumps พ่น TypeError
    ทั้งหมด ทำให้ commit ล้มกลายเป็น 500 (เจอจริงตอนแก้ราคาอุปกรณ์ที่มีราคาอยู่แล้ว —
    unit_value เป็น Numeric(12,2) จึงคืน Decimal ออกมาเสมอ)
    """
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    return v


def diff_fields(entity, changed: dict) -> dict[str, list]:
    """เทียบค่าฟิลด์เดิม (ก่อน setattr) กับค่าใหม่ใน `changed` คืนเฉพาะฟิลด์ที่ค่าเปลี่ยนจริง รูปแบบ
    {field: [old, new]} — เดินตาม pattern เดียวกับ import_service.diff_rows ที่ทำ diff แบบนี้อยู่แล้ว
    เรียกก่อน setattr loop เสมอ — อ่านค่าเดิมจาก entity ก่อนถูกเขียนทับ

    ค่าที่คืนถูกแปลงเป็นชนิดที่ JSONB รับได้แล้ว (ดู _jsonable) เพราะ detail ทั้งก้อนนี้ถูกเขียนลง
    audit_logs.detail ตรง ๆ — เทียบค่าใช้ของที่แปลงแล้วทั้งคู่
    """
    diffs: dict[str, list] = {}
    for field, new_value in changed.items():
        old_value = getattr(entity, field, None)
        # Decimal('1000.00') != 1000.0 ในสายตา Python จึงต้องเทียบหลังแปลงชนิด ไม่งั้นจะขึ้นเป็น
        # "เปลี่ยนแปลง" ทั้งที่ค่าเท่ากัน (แอดมินกดบันทึกโดยไม่แก้ราคาก็จะมี log ขยะทุกครั้ง)
        old_json, new_json = _jsonable(old_value), _jsonable(new_value)
        if old_json != new_json:
            diffs[field] = [old_json, new_json]
    return diffs


async def log_action(
    db: AsyncSession,
    actor: User,
    action: str,
    target_table: str,
    target_id: uuid.UUID,
    detail: dict | None = None,
) -> None:
    """บันทึกการกระทำลง audit_logs — ใช้กับทุก role ไม่ใช่เฉพาะ admin

    ตั้งแต่ 5 ก.ย. 69 (feedback อาจารย์) การกระทำฝั่งนักศึกษาถูกบันทึกด้วย (ยื่นคำขอ/ยกเลิก/
    ขอคืน/ขอต่อเวลา) เพราะ log ที่มีแค่ฝั่งแอดมินตอบไม่ได้ว่าเรื่องเริ่มต้นจากใคร

    snapshot ชื่อ/รหัส/สิทธิ์ของผู้ทำไว้ในตัว log เลย เพื่อให้รู้ว่าใครทำแม้ user จะถูกลบภายหลัง
    (audit trail ต้องลบไม่ได้ด้วยการลบบัญชี)
    """
    db.add(AuditLog(
        actor_id=actor.id,
        actor_name=actor.full_name,
        actor_identifier=user_identifier(actor),
        actor_role=actor.role,
        action=action, target_table=target_table, target_id=target_id, detail=detail,
    ))
