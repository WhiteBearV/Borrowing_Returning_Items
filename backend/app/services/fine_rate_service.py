"""ป้ายอัตราค่าปรับคืนเกินกำหนด (23 พ.ย. 69) — สร้าง/แก้/ลบเฉพาะผู้ดูแลสูงสุด (ตรวจที่ router ด้วย require_superadmin)

แก้ราคาป้ายมีผลกับการอนุมัติครั้งถัดไปเท่านั้น — ของที่ยืมอยู่ล็อกอัตราไว้ใน borrow_items.fine_rate_snapshot แล้ว
"""
import uuid

from fastapi import HTTPException, status
from sqlalchemy import distinct, func, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.equipment import Equipment
from app.models.fine_rate import FineRate
from app.models.user import User
from app.schemas.fine_rate import FineRateCreate, FineRateResponse, FineRateUpdate
from app.services import audit_service


async def list_rates(db: AsyncSession) -> list[FineRateResponse]:
    """ป้ายทั้งหมดเรียงตามราคา + จำนวนรุ่นที่ใช้อยู่ (ให้ผู้ดูแลสูงสุดเห็นก่อนแก้ว่ากระทบกี่รุ่น)"""
    counts = dict((await db.execute(
        select(Equipment.fine_rate_id, func.count(distinct(tuple_(Equipment.name, Equipment.item_type))))
        .where(Equipment.fine_rate_id.is_not(None)).group_by(Equipment.fine_rate_id)
    )).all())
    rates = (await db.execute(select(FineRate).order_by(FineRate.amount_per_day, FineRate.name))).scalars().all()
    return [FineRateResponse(id=r.id, name=r.name, amount_per_day=float(r.amount_per_day), is_default=r.is_default,
                             model_count=counts.get(r.id, 0)) for r in rates]


async def default_rate_id(db: AsyncSession) -> uuid.UUID | None:
    """ป้ายค่าเริ่มต้น — อุปกรณ์รุ่นใหม่ที่ยังไม่มีหน่วยอื่นในรุ่นได้ป้ายนี้"""
    return (await db.execute(select(FineRate.id).where(FineRate.is_default))).scalar_one_or_none()


async def _get(db: AsyncSession, rate_id: uuid.UUID) -> FineRate:
    rate = (await db.execute(select(FineRate).where(FineRate.id == rate_id).with_for_update())).scalar_one_or_none()
    if not rate:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fine rate not found.")
    return rate


async def _assert_name_free(db: AsyncSession, name: str, exclude_id: uuid.UUID | None = None) -> None:
    q = select(FineRate.id).where(func.lower(FineRate.name) == name.lower())
    if exclude_id:
        q = q.where(FineRate.id != exclude_id)
    if (await db.execute(q)).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A fine rate with this name already exists.")


async def _make_default(db: AsyncSession, rate: FineRate) -> None:
    await db.execute(update(FineRate).where(FineRate.id != rate.id, FineRate.is_default).values(is_default=False))
    await db.flush()
    rate.is_default = True


async def create_rate(db: AsyncSession, actor: User, body: FineRateCreate) -> FineRateResponse:
    """สร้างป้ายใหม่ — ชื่อห้ามซ้ำ (ไม่สนตัวพิมพ์) · ตั้งเป็นค่าเริ่มต้นพร้อมกันได้"""
    await _assert_name_free(db, body.name)
    rate = FineRate(name=body.name, amount_per_day=body.amount_per_day, is_default=False)
    db.add(rate)
    await db.flush()
    if body.is_default:
        await _make_default(db, rate)
    await audit_service.log_action(db, actor, "create_fine_rate", "fine_rates", rate.id, {
        "name": rate.name, "amount_per_day": float(body.amount_per_day), "is_default": body.is_default})
    await db.commit()
    return next(r for r in await list_rates(db) if r.id == rate.id)


async def update_rate(db: AsyncSession, actor: User, rate_id: uuid.UUID, body: FineRateUpdate) -> FineRateResponse:
    """แก้ชื่อ/ราคา/ตั้งเป็นค่าเริ่มต้น — ของที่ยืมอยู่ไม่กระทบเพราะล็อกอัตราตอนอนุมัติแล้ว"""
    rate = await _get(db, rate_id)
    changes: dict = {}
    if body.name is not None and body.name != rate.name:
        await _assert_name_free(db, body.name, exclude_id=rate.id)
        changes["name"] = [rate.name, body.name]
        rate.name = body.name
    if body.amount_per_day is not None and float(body.amount_per_day) != float(rate.amount_per_day):
        changes["amount_per_day"] = [float(rate.amount_per_day), float(body.amount_per_day)]
        rate.amount_per_day = body.amount_per_day
    if body.is_default is False and rate.is_default:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Set another fine rate as default instead of unsetting this one.")
    if body.is_default and not rate.is_default:
        changes["is_default"] = [False, True]
        await _make_default(db, rate)
    if changes:
        await audit_service.log_action(db, actor, "update_fine_rate", "fine_rates", rate.id,
                                       {"name": rate.name, "changes": changes})
    await db.commit()
    return next(r for r in await list_rates(db) if r.id == rate.id)


async def delete_rate(db: AsyncSession, actor: User, rate_id: uuid.UUID) -> None:
    """ลบป้าย — ห้ามลบป้ายค่าเริ่มต้นและป้ายที่ยังมีอุปกรณ์ใช้อยู่ (ต้องย้ายรุ่นไปป้ายอื่นก่อน ไม่งั้นของหลุดไปใช้อัตรากลางเงียบ ๆ)"""
    rate = await _get(db, rate_id)
    if rate.is_default:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cannot delete the default fine rate.")
    used = next((r.model_count for r in await list_rates(db) if r.id == rate.id), 0)
    if used:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=f"This fine rate is used by {used} equipment model(s). Move them to another rate first.")
    await audit_service.log_action(db, actor, "delete_fine_rate", "fine_rates", rate.id,
                                   {"name": rate.name, "amount_per_day": float(rate.amount_per_day)})
    await db.delete(rate)
    await db.commit()
