"""ตรวจครุภัณฑ์รายห้องด้วย QR (16 พ.ย. 69 — feedback ผู้ดูแลคลัง)

ขั้นตอน: สแกน QR หน้าห้อง → เปิดรอบ (snapshot รายการที่ทะเบียนบอกว่าอยู่ห้องนั้น) → เดินสแกนของทีละชิ้น →
ปิดรอบ ที่ยังไม่เจอ = ไม่พบ (ทะเบียนย้ายไปห้องอื่นแล้ว = พบที่ห้องอื่น) · ของจากห้องอื่นที่สแกนเจอในห้องนี้ = ย้าย `equipment.location` มาห้องนี้ให้เลย
แล้วลง audit พร้อมห้องเดิม (หมายเหตุการย้ายห้อง)

ต่างจาก "ตรวจนับกายภาพ" แบบกดทีละชิ้นที่เคยมี (617d1fe ลบใน 695f9b7) — อันนี้ตรวจเป็นรอบรายห้อง ได้ใบสรุปทั้งห้อง
ห้องคือข้อความใน `equipment.location` ตรงตัว ("ห้อง 301" ≠ "301") ต้องรวมชื่อห้องให้ตรงกันก่อนใช้งาน
"""
import uuid
from collections import Counter
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.equipment import Equipment
from app.models.notification import Notification
from app.models.stocktake import StocktakeItem, StocktakeRound
from app.models.user import User
from app.schemas.stocktake import (
    RoomItem, StocktakeConditionRequest, StocktakeItemResponse, StocktakeLocation, StocktakeRoundResponse, StocktakeRoundSummary, StocktakeScanRequest,
    StocktakeScanResponse,
)
from app.services import audit_service
from app.services.equipment_service import _normalize_asset_number, get_holders_map, set_room
from app.utils.pdf import SheetRow, _fmt_date_th_full
from app.utils.roles import STAFF_ROLES

# ครุภัณฑ์เท่านั้น (23 พ.ย. 69 ผู้ใช้เลือก) — ตรงกับรายงานทะเบียนคุมทรัพย์สินที่มีแต่ครุภัณฑ์ · วัสดุไม่มีเลขครุภัณฑ์
# ไม่อยู่ในทะเบียนราชการ (ห้อง 15310 มีวัสดุ 460 ชิ้น ตรวจด้วยจะช้าลง 3 เท่าโดยไม่มีที่ใช้) — ตรวจวัสดุด้วยการปรับยอดคงเหลือแทน
TRACKED_TYPES = ("durable",)


def _counts(rnd: StocktakeRound) -> dict[str, int]:
    return dict(Counter(i.result for i in rnd.items))


def _summary(rnd: StocktakeRound) -> StocktakeRoundSummary:
    return StocktakeRoundSummary(
        id=rnd.id, location=rnd.location, started_at=rnd.started_at, finished_at=rnd.finished_at,
        started_by_name=rnd.starter.full_name if rnd.starter else None, counts=_counts(rnd),
    )


def _detail(rnd: StocktakeRound) -> StocktakeRoundResponse:
    return StocktakeRoundResponse(
        **_summary(rnd).model_dump(), note=rnd.note,
        items=[StocktakeItemResponse.model_validate(i) for i in rnd.items],
    )


async def list_locations(db: AsyncSession) -> list[StocktakeLocation]:
    """รายชื่อห้องจากทะเบียน + จำนวนของที่ควรอยู่ + รอบที่เปิดค้างอยู่ (ให้คนที่สองสแกนเข้ารอบเดียวกันได้)"""
    rows = (await db.execute(
        select(Equipment.location, func.count())
        .where(Equipment.location.is_not(None), Equipment.location != "",
               Equipment.item_type.in_(TRACKED_TYPES), Equipment.status != "retired")
        .group_by(Equipment.location).order_by(Equipment.location)
    )).all()
    open_rounds = dict((await db.execute(
        select(StocktakeRound.location, StocktakeRound.id).where(StocktakeRound.finished_at.is_(None))
    )).all())
    return [StocktakeLocation(location=loc, count=n, open_round_id=open_rounds.get(loc)) for loc, n in rows]


async def room_items(db: AsyncSession, viewer: User, location: str) -> list[RoomItem]:
    """ของในห้องตามทะเบียน (ชุดเดียวกับที่รอบตรวจจะ snapshot) + ใครยืมอยู่ — ดูอย่างเดียว ไม่เปิดรอบ

    ไว้เช็คคร่าว ๆ ก่อนตรวจจริง/หาของในห้อง · ต่างจาก start_round ที่เขียนรอบลง DB และลง audit
    """
    units = (await db.execute(
        select(Equipment).where(Equipment.location == location.strip(), Equipment.item_type.in_(TRACKED_TYPES),
                                Equipment.status != "retired")
        .order_by(Equipment.name, Equipment.code)
    )).scalars().all()
    holders = await get_holders_map(db, [u.id for u in units], viewer=viewer)
    return [
        RoomItem(id=u.id, code=u.code, name=u.name, asset_number=u.asset_number, serial_number=u.serial_number,
                 location_detail=u.location_detail, status=u.status, holder_name=(holders[u.id][0].holder_name or "มีผู้ยืมอยู่") if u.id in holders else None,
                 due_date=holders[u.id][0].due_date if u.id in holders else None)
        for u in units
    ]


async def list_rounds(db: AsyncSession, location: str | None = None) -> list[StocktakeRoundSummary]:
    q = select(StocktakeRound).order_by(StocktakeRound.started_at.desc(), StocktakeRound.id).limit(100)
    if location:
        q = q.where(StocktakeRound.location == location)
    return [_summary(r) for r in (await db.execute(q)).scalars().all()]


async def _load_round(db: AsyncSession, round_id: uuid.UUID, lock: bool = False) -> StocktakeRound:
    # populate_existing: หลัง commit ต้องอ่านค่าใหม่ (started_at จาก server_default, รายการที่เพิ่ง insert)
    q = select(StocktakeRound).where(StocktakeRound.id == round_id).execution_options(populate_existing=True)
    if lock:
        q = q.with_for_update()
    rnd = (await db.execute(q)).scalar_one_or_none()
    if not rnd:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stocktake round not found.")
    return rnd


async def get_round(db: AsyncSession, round_id: uuid.UUID) -> StocktakeRoundResponse:
    return _detail(await _load_round(db, round_id))


async def start_round(db: AsyncSession, actor: User, location: str) -> StocktakeRoundResponse:
    """เปิดรอบตรวจห้อง — ถ้าห้องนี้มีรอบค้างอยู่แล้วคืนรอบเดิม (สแกน QR ห้องซ้ำ/สองคนตรวจพร้อมกัน = รอบเดียวกัน)

    ของที่กำลังถูกยืมอยู่ติด `on_loan` ตั้งแต่แรก ไม่งั้นปิดรอบแล้วจะขึ้นว่า "ไม่พบ" ทั้งที่รู้อยู่ว่าใครถือ
    """
    location = location.strip()
    # advisory lock ต่อชื่อห้อง กันสองเครื่องสแกน QR ห้องพร้อมกันแล้วได้คนละรอบ
    await db.execute(select(func.pg_advisory_xact_lock(func.hashtext(f"stocktake:{location}"))))
    existing = (await db.execute(
        select(StocktakeRound).where(StocktakeRound.location == location, StocktakeRound.finished_at.is_(None))
    )).scalars().first()
    if existing:
        return _detail(existing)

    units = (await db.execute(
        select(Equipment).where(Equipment.location == location, Equipment.item_type.in_(TRACKED_TYPES),
                                Equipment.status != "retired")
    )).scalars().all()
    if not units:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No equipment registered in this location.")
    holders = await get_holders_map(db, [u.id for u in units], viewer=actor)

    rnd = StocktakeRound(location=location, started_by=actor.id)
    db.add(rnd)
    await db.flush()
    for u in units:
        db.add(StocktakeItem(
            round_id=rnd.id, equipment_id=u.id, equipment_code=u.code, equipment_name=u.name,
            asset_number=u.asset_number, result="on_loan" if u.id in holders else "pending",
        ))
    await audit_service.log_action(db, actor, "stocktake_start", "stocktake_rounds", rnd.id,
                                   {"location": location, "expected": len(units)})
    await db.commit()
    return _detail(await _load_round(db, rnd.id))


async def _find_equipment(db: AsyncSession, body: StocktakeScanRequest) -> Equipment:
    """จับคู่สิ่งที่สแกน: QR ระบบ (id) · รหัสอุปกรณ์ · เลขครุภัณฑ์ (พิมพ์ติดกัน 15 หลักก็เจอ)"""
    if body.equipment_id:
        eq = await db.get(Equipment, body.equipment_id)
    else:
        code = body.code.strip()
        # พิมพ์เองบนมือถือมักได้ตัวเล็ก (dt-d-00001) — รหัสในระบบเป็นตัวใหญ่ทั้งหมด
        eq = (await db.execute(select(Equipment).where(func.upper(Equipment.code) == code.upper()))).scalars().first()
        if not eq:
            eq = (await db.execute(
                select(Equipment).where(Equipment.asset_number == _normalize_asset_number(code))
            )).scalars().first()
    if not eq:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Equipment not found for this code.")
    if eq.item_type not in TRACKED_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Only durable equipment (ครุภัณฑ์) is part of the stocktake.")
    return eq


async def scan(db: AsyncSession, actor: User, round_id: uuid.UUID, body: StocktakeScanRequest) -> StocktakeScanResponse:
    """บันทึกการสแกนหนึ่งชิ้น — ของในรายการห้อง = พบ · ของห้องอื่น = ย้ายมาห้องนี้ (แก้ location ในทะเบียน)

    สแกนซ้ำไม่เปลี่ยนอะไร (`already`) เพราะเดินสแกนวนซ้ำเป็นเรื่องปกติ · ล็อกแถวรอบก่อนเสมอ กันสองเครื่อง
    สแกนของชิ้นเดียวกันพร้อมกันแล้วชน unique
    """
    rnd = await _load_round(db, round_id, lock=True)
    if rnd.finished_at:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This stocktake round is already finished.")
    eq = await _find_equipment(db, body)
    now = datetime.now(timezone.utc)
    item = next((i for i in rnd.items if i.equipment_id == eq.id), None)

    if item and item.result in ("found", "moved_here"):
        outcome = "already"
    elif item:
        # on_loan ที่เจอตัวจริงในห้องก็นับว่าพบ (คืนแล้วแต่ยังไม่ได้กดรับคืน/ยืมใช้ในห้อง)
        item.result, item.scanned_at, item.scanned_by = "found", now, actor.id
        if item.condition == "lost":
            item.condition = None  # เคยติ๊กสูญหายแล้วมาเจอ — ต้องเลือกสภาพใหม่ ไม่งั้นใบตรวจขึ้น "พบ" แต่ติ๊ก "สูญหาย"
        outcome = "found"
        if eq.location != rnd.location:
            # รอบห้องอื่นที่ตรวจพร้อมกันเผลอสแกนย้ายไปก่อน — ของอยู่ห้องนี้จริง ย้ายทะเบียนกลับ
            eq = (await db.execute(select(Equipment).where(Equipment.id == eq.id).with_for_update())).scalar_one()
            back_from = eq.location
            item.from_location, item.from_location_detail = back_from, eq.location_detail  # ไว้ยกเลิกการสแกน
            set_room(eq, rnd.location)
            await audit_service.log_action(db, actor, "stocktake_move", "equipment", eq.id, {
                "code": eq.code, "name": eq.name, "changes": {"location": [back_from, rnd.location]},
                "note": f"ย้ายกลับจาก {back_from or '(ไม่ระบุ)'} มา {rnd.location} (พบระหว่างตรวจครุภัณฑ์)",
            })
    else:
        eq = (await db.execute(select(Equipment).where(Equipment.id == eq.id).with_for_update())).scalar_one()
        from_location, from_detail = eq.location, eq.location_detail
        set_room(eq, rnd.location)
        item = StocktakeItem(
            round_id=rnd.id, equipment_id=eq.id, equipment_code=eq.code, equipment_name=eq.name,
            asset_number=eq.asset_number, result="moved_here", from_location=from_location,
            from_location_detail=from_detail,
            scanned_at=now, scanned_by=actor.id,
        )
        rnd.items.append(item)
        await audit_service.log_action(db, actor, "stocktake_move", "equipment", eq.id, {
            "code": eq.code, "name": eq.name, "changes": {"location": [from_location, rnd.location]},
            "note": f"ย้ายจาก {from_location or '(ไม่ระบุ)'} มา {rnd.location} (พบระหว่างตรวจครุภัณฑ์)",
        })
        outcome = "moved_here"

    await db.commit()
    rnd = await _load_round(db, round_id)
    item = next(i for i in rnd.items if i.equipment_id == eq.id)
    return StocktakeScanResponse(outcome=outcome, item=StocktakeItemResponse.model_validate(item), round=_detail(rnd))


async def set_condition(
    db: AsyncSession, actor: User, round_id: uuid.UUID, item_id: uuid.UUID, body: StocktakeConditionRequest,
) -> StocktakeRoundResponse:
    """ติ๊กสภาพ + หมายเหตุ 1 ชิ้น ตามแบบรายงานทะเบียนคุมทรัพย์สิน — หลังสแกน หรือกดจากรายการ (ป้าย QR หลุด/ของหาย)

    บันทึกบนใบตรวจเท่านั้น **ไม่แก้สถานะในทะเบียน** (ผู้ใช้เลือก 23 พ.ย. 69 — ชำรุด/จำหน่ายให้เจ้าหน้าที่ทำต่อผ่านทางเดิม)
    สูญหาย = ไม่พบ · สภาพอื่น = เจอตัวจริง (ยังไม่ได้สแกน → นับว่าพบ) · แก้ซ้ำได้จนกว่าจะปิดรอบ
    """
    rnd = await _load_round(db, round_id, lock=True)
    if rnd.finished_at:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This stocktake round is already finished.")
    item = next((i for i in rnd.items if i.id == item_id), None)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found in this round.")
    if body.condition == "lost":
        if item.result == "moved_here":
            # เพิ่งสแกนเจอของห้องอื่นในห้องนี้ จะหายได้ยังไง — สแกนผิดให้ใช้ "ยกเลิกการสแกน" (ย้ายทะเบียนกลับให้ด้วย)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail="This item was just scanned here — undo the scan instead of marking it lost.")
        item.result = "missing"
    elif item.result in ("pending", "missing", "on_loan"):
        item.result, item.scanned_at, item.scanned_by = "found", datetime.now(timezone.utc), actor.id
    item.condition, item.note = body.condition, body.note
    await audit_service.log_action(db, actor, "stocktake_condition", "stocktake_rounds", rnd.id, {
        "location": rnd.location, "code": item.equipment_code, "name": item.equipment_name,
        "condition": body.condition, "note": body.note,
    })
    await db.commit()
    return _detail(await _load_round(db, round_id))


async def undo_scan(db: AsyncSession, actor: User, round_id: uuid.UUID, item_id: uuid.UUID) -> StocktakeRoundResponse:
    """ยกเลิกการสแกน (สแกนผิดชิ้น/ผิดห้อง) — ของห้องอื่นที่ "ย้ายมา" = ย้ายทะเบียนกลับห้อง+ตู้เดิม แล้วเอาออกจากรอบ ·
    ของในรายการห้อง = กลับเป็นยังไม่ตรวจ ล้างสภาพ/หมายเหตุ (ถ้าการสแกนนั้นย้ายทะเบียนกลับมาจากห้องอื่น ก็ย้ายคืน)

    ย้ายคืนเฉพาะเมื่อทะเบียนยังอยู่ห้องนี้ — ถ้ามีคนย้ายต่อไปแล้วหลังสแกน ไม่ไปทับของเขา
    """
    rnd = await _load_round(db, round_id, lock=True)
    if rnd.finished_at:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This stocktake round is already finished.")
    item = next((i for i in rnd.items if i.id == item_id), None)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found in this round.")
    if item.result not in ("found", "moved_here", "missing") and not item.condition:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This item has not been scanned.")

    moved_back = None
    if item.from_location is not None and item.equipment_id:
        eq = (await db.execute(select(Equipment).where(Equipment.id == item.equipment_id).with_for_update())).scalar_one_or_none()
        if eq and eq.location == rnd.location:
            eq.location, eq.location_detail = item.from_location, item.from_location_detail
            moved_back = item.from_location
            await audit_service.log_action(db, actor, "stocktake_move", "equipment", eq.id, {
                "code": eq.code, "name": eq.name, "changes": {"location": [rnd.location, item.from_location]},
                "note": f"ยกเลิกการสแกน — ย้ายกลับ {item.from_location} (สแกนผิดระหว่างตรวจห้อง {rnd.location})",
            })
    if item.result == "moved_here":
        rnd.items.remove(item)
        await db.delete(item)
    else:
        holders = await get_holders_map(db, [item.equipment_id], viewer=actor) if item.equipment_id else {}
        item.result = "on_loan" if item.equipment_id in holders else "pending"
        item.condition = item.note = item.scanned_at = item.scanned_by = None
        item.from_location = item.from_location_detail = None
    await audit_service.log_action(db, actor, "stocktake_undo", "stocktake_rounds", rnd.id, {
        "location": rnd.location, "code": item.equipment_code, "name": item.equipment_name, "moved_back_to": moved_back,
    })
    await db.commit()
    return _detail(await _load_round(db, round_id))


async def summary_rows(db: AsyncSession) -> list[SheetRow]:
    """ใบรวมทุกห้อง — ครุภัณฑ์ทุกชิ้น (ไม่รวมปลดระวาง) เรียงตามห้อง + สภาพจากการตรวจล่าสุดของชิ้นนั้น (รอบไหนก็ได้)

    ยังไม่เคยตรวจ = ช่องสภาพว่าง · หมายเหตุบอกวันที่ตรวจล่าสุด (เอกสารทั้งคณะต้องตอบได้ว่าแต่ละชิ้นตรวจเมื่อไหร่)
    """
    units = (await db.execute(
        select(Equipment).where(Equipment.item_type.in_(TRACKED_TYPES), Equipment.status != "retired")
        .order_by(Equipment.location.nulls_last(), Equipment.asset_number.nulls_last(), Equipment.code)
    )).scalars().all()
    latest = {row.equipment_id: row for row in (await db.execute(
        select(StocktakeItem.equipment_id, StocktakeItem.condition, StocktakeItem.note, StocktakeRound.started_at)
        .join(StocktakeRound, StocktakeItem.round_id == StocktakeRound.id)
        .where(StocktakeItem.condition.is_not(None), StocktakeItem.equipment_id.is_not(None))
        .order_by(StocktakeItem.equipment_id, StocktakeRound.started_at.desc())
        .distinct(StocktakeItem.equipment_id)
    )).all()}
    rows = []
    for u in units:
        hit = latest.get(u.id)
        note = " · ".join(x for x in (hit and hit.note, hit and f"ตรวจล่าสุด {_fmt_date_th_full(hit.started_at)}") if x) \
            if hit else "ยังไม่เคยตรวจ"
        rows.append(SheetRow(u.location, u.code, u.asset_number, u.name, u.location_detail,
                             float(u.unit_value) if u.unit_value is not None else None, u.acquired_at,
                             hit.condition if hit else None, note))
    return rows


async def finish(db: AsyncSession, actor: User, round_id: uuid.UUID, note: str | None) -> StocktakeRoundResponse:
    """ปิดรอบ — ที่ยังไม่ได้สแกน = ไม่พบ · มีของไม่พบ = แจ้งเตือนเจ้าหน้าที่ทุกคน (ต้องตามหา/ตั้งเรื่องต่อ)"""
    rnd = await _load_round(db, round_id, lock=True)
    if rnd.finished_at:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This stocktake round is already finished.")
    # เจอของแล้วต้องติ๊กสภาพก่อนปิดรอบ — ไม่งั้นใบตรวจมีแถว "พบ" แต่ไม่มีติ๊กสักช่อง
    unmarked = [i.equipment_code for i in rnd.items if i.result in ("found", "moved_here") and not i.condition]
    if unmarked:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"ยังไม่ได้เลือกสภาพ {len(unmarked)} รายการที่พบแล้ว: {', '.join(unmarked[:5])}")
    pending = [i for i in rnd.items if i.result == "pending"]
    # ทะเบียนตอนนี้บอกว่าอยู่ห้องอื่นแล้ว (รอบห้องอื่นสแกนเจอ/มีคนแก้ระหว่างตรวจ) = ไม่ใช่ของหาย
    current = dict((await db.execute(
        select(Equipment.id, Equipment.location).where(Equipment.id.in_([i.equipment_id for i in pending]))
    )).all()) if pending else {}
    for i in pending:
        now_at = current.get(i.equipment_id)
        if now_at and now_at != rnd.location:
            i.result, i.from_location = "elsewhere", now_at
        else:
            i.result = "missing"
    rnd.finished_at = datetime.now(timezone.utc)
    rnd.note = note.strip() if note and note.strip() else None
    counts = _counts(rnd)

    missing = counts.get("missing", 0)
    if missing:
        staff = (await db.execute(
            select(User.id).where(User.role.in_(STAFF_ROLES), User.is_active == True)  # noqa: E712
        )).scalars().all()
        for uid in staff:
            db.add(Notification(
                user_id=uid, type="stocktake_missing", channel="in_app",
                message=f"ตรวจครุภัณฑ์ห้อง {rnd.location}: ไม่พบ {missing} รายการ",
            ))
    await audit_service.log_action(db, actor, "stocktake_finish", "stocktake_rounds", rnd.id,
                                   {"location": rnd.location, **counts})
    await db.commit()
    return _detail(await _load_round(db, round_id))
