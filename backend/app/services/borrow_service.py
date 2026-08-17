import uuid
from datetime import date, datetime, timezone, timedelta
from html import escape

from fastapi import HTTPException, status
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.borrow_item import BorrowItem
from app.models.borrow_request import BorrowRequest
from app.models.equipment import Equipment
from app.models.notification import Notification
from app.models.setting import Setting
from app.models.user import User
from app.schemas.borrow import (
    BorrowItemResponse,
    BorrowRequestCreate,
    BorrowRequestResponse,
    PaginatedBorrowRequests,
    ReturnItemRequest,
)
from app.services import audit_service, equipment_service
from app.utils.email import send_email

# สถานะตอนสรุปผลอุปกรณ์ แยกตามชนิด
DURABLE_CONDITIONS = {"ok", "damaged", "lost"}
CONSUMABLE_CONDITIONS = {"returned_full", "used_up", "discarded"}  # คืนครบ / ใช้หมด / เสียหายทิ้ง
STOCK_RETURN_CONDITIONS = {"ok", "returned_full"}   # สถานะที่คืนของเข้าสต็อก
PHOTO_REQUIRED_CONDITIONS = {"damaged", "lost", "discarded"}  # ต้องแนบรูปหลักฐาน


async def _get_setting_int(db: AsyncSession, key: str) -> int:
    """อ่านค่า int จาก settings — seed data ต้องมีครบ ดู alembic/versions/0002_seed_settings"""
    result = await db.execute(select(Setting).where(Setting.key == key))
    return int(result.scalar_one().value)


def _ident(user: User) -> str:
    return user.student_id or user.username or "USER"


async def _next_request_code(db: AsyncSession, user: User) -> str:
    """ออกเลขคำขอแบบนับต่อเนื่องต่อผู้ใช้ เช่น REQ-2026-6512345678-0001

    ใช้ UPDATE users SET borrow_seq = borrow_seq + 1 RETURNING (row lock) เพื่อ
    ให้เลขนับขึ้นแบบ atomic — สองคำขอของคนเดียวกันที่กดพร้อมกันจะได้คนละเลข ไม่ชนกัน
    ต่างจาก count+1 ที่ race ได้ (ห้ามใช้ตาม CLAUDE.md)
    """
    result = await db.execute(
        update(User).where(User.id == user.id)
        .values(borrow_seq=User.borrow_seq + 1)
        .returning(User.borrow_seq)
    )
    seq = result.scalar_one()
    return f"REQ-{date.today().year}-{_ident(user)}-{seq:04d}"


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
        .options(
            selectinload(BorrowRequest.items).selectinload(BorrowItem.equipment),
            selectinload(BorrowRequest.student),
            selectinload(BorrowRequest.approver),  # ใบยืมโชว์ชื่อผู้อนุมัติ — ต้อง eager-load กัน lazy-load async
            selectinload(BorrowRequest.receiver),  # ใบคืนโชว์ชื่อผู้รับคืน
        )
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

    # ponytail: admin/อาจารย์ ยืมเชิงจัดการ (ยืมเอง/ยืมแทน) ไม่ติดโควตานักศึกษา
    is_admin = current_user.role == "admin"

    if not is_admin:
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

    if body.requested_due_date <= date.today():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Requested return date must be in the future.",
        )

    if len(body.items) == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Request must have at least 1 item.")
    if not is_admin and len(body.items) > max_items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot request more than {max_items} items at once.",
        )

    # ตรวจสอบ equipment ทุกรายการก่อน insert — คำนวณด้วยว่าแต่ละบรรทัดจะได้หน่วยไหนบ้าง
    # (eq, quantity) ต่อ BorrowItem ที่จะสร้างจริง — รุ่นที่มีหลายหน่วย (ครุภัณฑ์/วัสดุ) 1 บรรทัดคำขอ
    # ขยายเป็นหลายแถว หน่วยละ 1 ชิ้น เลือกจากรหัสต่ำสุดที่ว่างก่อน — "จอง" แค่ตอนนี้ไม่ผูกมัด
    # ของจริงเลือกซ้ำอีกทีตอนอนุมัติภายใต้ lock กัน race (ดู approve_request)
    resolved: list[tuple[Equipment, int]] = []
    for item_req in body.items:
        eq_result = await db.execute(select(Equipment).where(Equipment.id == item_req.equipment_id))
        eq = eq_result.scalar_one_or_none()
        if not eq:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Equipment {item_req.equipment_id} not found.",
            )
        # ของประจำห้อง (โต๊ะ/ตู้/ทีวี) — อยู่ในทะเบียน สถานะปกติ แต่ไม่ให้ยืมออก
        if not eq.is_borrowable:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Equipment '{eq.name}' is not lendable.",
            )
        # status != available (unavailable/damaged/under_repair/retired) = ห้ามยืม ทุกชนิด ไม่ใช่แค่ครุภัณฑ์
        if eq.status != "available":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Equipment '{eq.name}' is not available (status: {eq.status}).",
            )

        group = (
            [eq] if eq.item_type == "consumable"
            else await equipment_service.find_group_members(db, eq.name, eq.item_type)
        )
        if len(group) <= 1:
            if eq.quantity_available < item_req.quantity:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Equipment '{eq.name}' has insufficient stock (available: {eq.quantity_available}).",
                )
            resolved.append((eq, item_req.quantity))
        else:
            eligible = [g for g in group if g.is_borrowable and g.status == "available" and g.quantity_available > 0]
            if len(eligible) < item_req.quantity:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Equipment '{eq.name}' has insufficient stock (available: {len(eligible)}).",
                )
            for unit in eligible[:item_req.quantity]:
                resolved.append((unit, 1))

    req = BorrowRequest(
        id=uuid.uuid4(),
        request_code=await _next_request_code(db, current_user),
        student_id=current_user.id,
        purpose=body.purpose,
        requested_due_date=body.requested_due_date,
        status="pending",
    )
    db.add(req)
    await db.flush()  # ได้ req.id

    for eq, quantity in resolved:
        db.add(BorrowItem(
            borrow_request_id=req.id,
            equipment_id=eq.id,
            item_type_snapshot=eq.item_type,
            quantity=quantity,
        ))

    # แจ้งเตือน admin ทุกคน (in-app) — ยกเว้นตัวเอง กัน admin ที่ยืมของตัวเอง
    # ได้แจ้งเตือน "มีคำขอใหม่" ซ้ำกับคำขอที่ตัวเองเพิ่งส่ง
    admins = (await db.execute(select(User).where(User.role == "admin", User.is_active == True))).scalars().all()
    for admin in admins:
        if admin.id == current_user.id:
            continue
        await _notify(db, admin.id, "new_request_admin",
                      f"คำขอยืมใหม่ {req.request_code} จาก {current_user.full_name}",
                      borrow_request_id=req.id)

    await db.commit()

    # แจ้งเตือน admin ทางอีเมลด้วย — ต้อง commit ก่อนเผื่อส่งช้า/พัง ไม่กระทบการสร้างคำขอ
    # escape ชื่อผู้ใช้/เลขคำขอก่อนฝัง HTML — full_name และ student_id/username มาจาก
    # ผู้ใช้กรอกตอนสมัคร ไม่ escape จะเปิดช่อง HTML injection ในอีเมล admin
    safe_name = escape(current_user.full_name)
    safe_code = escape(req.request_code)
    for admin in admins:
        if admin.id == current_user.id:
            continue
        try:
            await send_email(
                admin.email,
                f"คำขอยืมใหม่ {req.request_code}",
                f"<p>{safe_name} ส่งคำขอยืม <b>{safe_code}</b> เข้ามา "
                f"กรุณาเข้าระบบเพื่อตรวจสอบและอนุมัติ/ปฏิเสธ</p>",
            )
        except Exception as e:  # ponytail: อีเมลพังไม่ควรทำให้สร้างคำขอไม่สำเร็จ
            print(f"[email] แจ้ง admin {admin.email} ไม่สำเร็จ: {e}")

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
    query = select(BorrowRequest).options(
        selectinload(BorrowRequest.items).selectinload(BorrowItem.equipment),
        selectinload(BorrowRequest.student),
        # approver_name/receiver_name เป็น property ที่อ่าน relationship ตรงๆ (models/borrow_request.py)
        # ไม่ eager-load จะพัง MissingGreenlet ทันทีที่มีคำขอที่ approved_by/returned_by ไม่ใช่ null
        selectinload(BorrowRequest.approver),
        selectinload(BorrowRequest.receiver),
    )

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
    - ลด quantity_available ของทุก equipment ใน request (ทั้ง durable และ consumable)
    - due_date = วันที่นักศึกษาขอคืนเอง (requested_due_date) ตอนยื่นคำขอ — ไม่คำนวณจาก setting แล้ว
    - ส่งแจ้งเตือนนักศึกษา

    ไม่ตั้ง returned=True ให้ item ใดทั้งสิ้น แม้แต่ consumable —
    แอดมินต้องสรุปผลภายหลังว่าคืนครบ/ใช้หมด/เสียหาย (CLAUDE.md §5)
    """
    req = await _load_request(db, request_id)

    if req.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot approve request with status '{req.status}'.",
        )

    # ล็อกอุปกรณ์ก่อนอ่านค่าสต็อกมาตัดสินใจ — ล็อกทั้ง "กลุ่ม" ของทุก item ไม่ใช่แค่หน่วยที่ผูกไว้ตอนยื่น
    # เพราะรุ่นที่มีหลายหน่วย (ครุภัณฑ์/วัสดุ) หน่วยที่ผูกไว้ตอนยื่นอาจถูกคำขออื่นอนุมัติแซงไปก่อน
    # ต้องเลือกหน่วยอื่นในรุ่นเดียวกันแทนได้ — ไม่มีการล็อกนี้ = แอดมิน 2 คนกดอนุมัติของชิ้นสุดท้ายพร้อมกัน
    # จะอ่านได้ค่าเดียวกันทั้งคู่ ผ่านเงื่อนไขทั้งคู่ แล้วเขียนทับกัน = ปล่อยของชิ้นเดียวออกไป 2 ครั้งโดยไม่มี error
    #   order_by(code)     เรียงลำดับการล็อกให้เหมือนกันทุก transaction กัน deadlock + ได้ลำดับ "รหัสต่ำสุดก่อน" มาในตัว
    #   populate_existing  บังคับให้ค่าที่ selectinload โหลดไว้ก่อนหน้าถูกเขียนทับด้วยค่าที่เพิ่งล็อก
    group_keys = {(i.equipment.name, i.equipment.item_type) for i in req.items}
    conditions = [(Equipment.name == n) & (Equipment.item_type == t) for n, t in group_keys]
    locked_rows = list((await db.execute(
        select(Equipment)
        .where(or_(*conditions))
        .order_by(Equipment.code)
        .with_for_update()
        .execution_options(populate_existing=True)
    )).scalars().all())
    rows_by_group: dict[tuple[str, str], list[Equipment]] = {}
    for r in locked_rows:
        rows_by_group.setdefault((r.name, r.item_type), []).append(r)

    now = datetime.now(timezone.utc)
    for item in req.items:
        eq = item.equipment
        group = rows_by_group.get((eq.name, eq.item_type)) or [eq]

        if len(group) <= 1:
            # เช็คซ้ำตอนอนุมัติ — สถานะอาจเปลี่ยนเป็นห้ามยืมหลังนักศึกษายื่นคำขอ (พฤติกรรมเดิมเป๊ะ)
            if not eq.is_borrowable:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Equipment '{eq.name}' is not lendable.",
                )
            if eq.status != "available":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Equipment '{eq.name}' is not available (status: {eq.status}).",
                )
            if eq.quantity_available < item.quantity:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Equipment '{eq.name}' no longer has sufficient stock.",
                )
            chosen = eq
        else:
            # รุ่นที่มีหลายหน่วย — เลือกหน่วยรหัสต่ำสุดที่ว่างจริง ณ ตอนนี้เสมอ ไม่ใช่หน่วยที่ผูกไว้ตอนยื่น
            # (group เรียงตาม code จากการล็อกด้านบนแล้ว) หน่วยเดิมยังว่างก็จะถูกเลือกอยู่ดีเพราะเป็นรหัสต่ำสุด
            chosen = next(
                (g for g in group if g.is_borrowable and g.status == "available" and g.quantity_available >= item.quantity),
                None,
            )
            if chosen is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Equipment '{eq.name}' no longer has sufficient stock.",
                )
            if chosen.id != eq.id:
                item.equipment_id = chosen.id
                item.equipment = chosen

        # หักสต็อกทั้ง durable และ consumable — ของออกจากคลังแล้ว
        # consumable ไม่ auto-คืนอีกต่อไป: admin ต้องสรุปผลภายหลัง (คืนครบ/ใช้หมด/เสียหาย)
        chosen.quantity_available -= item.quantity
        # ล็อกราคาต่อหน่วย ณ วันอนุมัติ ใช้คิดต้นทุนวัสดุที่ถูกใช้ไป
        item.unit_value_snapshot = chosen.unit_value

    req.status = "approved"
    req.approved_by = admin.id
    req.approved_at = now
    req.due_date = req.requested_due_date

    await _notify(db, req.student_id, "approved",
                  f"คำขอ {req.request_code} ได้รับการอนุมัติแล้ว กรุณาคืนภายใน {req.due_date}",
                  borrow_request_id=req.id)
    await audit_service.log_action(db, admin, "approve_request", "borrow_requests", req.id,
                                   {"request_code": req.request_code, "due_date": str(req.due_date)})
    await db.commit()

    # แจ้งเตือนนักศึกษาทางอีเมลด้วย — ต้อง commit ก่อนเผื่อส่งช้า/พัง ไม่กระทบผลอนุมัติ
    try:
        await send_email(
            req.student.email,
            f"คำขอ {req.request_code} ได้รับการอนุมัติ",
            f"<p>คำขอยืม <b>{escape(req.request_code)}</b> ได้รับการอนุมัติแล้ว "
            f"กรุณาคืนภายใน {req.due_date}</p>",
        )
    except Exception as e:  # ponytail: อีเมลพังไม่ควรทำให้ผลอนุมัติเสีย
        print(f"[email] แจ้งนักศึกษา {req.student.email} ไม่สำเร็จ: {e}")


async def reject_request(
    db: AsyncSession, admin: User, request_id: uuid.UUID, reason: str
) -> None:
    """ปฏิเสธคำขอ พร้อมบันทึกเหตุผล"""
    req = await _load_request(db, request_id)
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
    await audit_service.log_action(db, admin, "reject_request", "borrow_requests", req.id,
                                   {"request_code": req.request_code, "reason": reason})
    await db.commit()

    # แจ้งเตือนนักศึกษาทางอีเมลด้วย — reason เป็นข้อความที่ admin พิมพ์เอง ต้อง escape กัน HTML injection
    try:
        await send_email(
            req.student.email,
            f"คำขอ {req.request_code} ถูกปฏิเสธ",
            f"<p>คำขอยืม <b>{escape(req.request_code)}</b> ถูกปฏิเสธ: {escape(reason)}</p>",
        )
    except Exception as e:  # ponytail: อีเมลพังไม่ควรทำให้ผลปฏิเสธเสีย
        print(f"[email] แจ้งนักศึกษา {req.student.email} ไม่สำเร็จ: {e}")


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

    # เคลียร์ธงเกินกำหนดถ้าไม่เหลือรายการที่ยังไม่คืนและเลยกำหนดแล้ว
    # ไม่มีบรรทัดนี้ นักศึกษาที่ต่อเวลาถูกต้องจะติดธงค้างคืนไปตลอด — ไม่มีจุดไหนรีเซ็ตธงนี้เลย
    still_overdue = (await db.execute(
        select(BorrowItem.id).where(
            BorrowItem.borrow_request_id == req.id,
            BorrowItem.returned == False,
            func.coalesce(BorrowItem.extended_due_date, req.due_date or date.today()) < date.today(),
        ).limit(1)
    )).first()
    req.is_overdue = still_overdue is not None

    await db.commit()


async def request_return_items(
    db: AsyncSession, current_user: User, request_id: uuid.UUID, item_ids: list[uuid.UUID]
) -> None:
    """นักศึกษาแจ้งขอคืนอุปกรณ์ (ทีละชิ้น/หลายชิ้น/ทั้งหมด) — แค่ตั้ง flag แจ้ง admin

    ไม่แตะ returned/quantity_available เลย — การคืนจริงยังต้องผ่าน return_item/return_all_items
    (admin only) เหมือนเดิมทุกประการ ตาม CLAUDE.md ข้อ 5
    """
    req = await _load_request(db, request_id)
    if current_user.role != "admin" and req.student_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    if req.status != "approved":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only request return on approved requests.",
        )

    matched = []
    for item_id in item_ids:
        item = next((i for i in req.items if i.id == item_id), None)
        if not item:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found.")
        if item.returned:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Item already returned.")
        matched.append(item)

    now = datetime.now(timezone.utc)
    for item in matched:
        item.return_requested = True
        item.return_requested_at = now

    # แจ้งเตือน admin ทุกคน (in-app) — ยกเว้นตัวเอง กัน admin ที่ยืมของตัวเองแจ้งตัวเองซ้ำซ้อน
    admins = (await db.execute(select(User).where(User.role == "admin", User.is_active == True))).scalars().all()
    for admin in admins:
        if admin.id == current_user.id:
            continue
        await _notify(db, admin.id, "return_requested_admin",
                      f"นักศึกษาแจ้งขอคืนอุปกรณ์ {len(matched)} รายการจากคำขอ {req.request_code}",
                      borrow_request_id=req.id)
    await db.commit()

    # แจ้งเตือน admin ทางอีเมลด้วย — ต้อง commit ก่อนเผื่อส่งช้า/พัง ไม่กระทบผลการแจ้งขอคืน
    safe_name = escape(current_user.full_name)
    safe_code = escape(req.request_code)
    for admin in admins:
        if admin.id == current_user.id:
            continue
        try:
            await send_email(
                admin.email,
                f"นักศึกษาแจ้งขอคืนคำขอ {req.request_code}",
                f"<p>{safe_name} แจ้งขอคืนอุปกรณ์ {len(matched)} รายการจากคำขอ <b>{safe_code}</b> "
                f"กรุณาเข้าระบบเพื่อตรวจสอบและยืนยันรับคืน</p>",
            )
        except Exception as e:  # ponytail: อีเมลพังไม่ควรทำให้แจ้งขอคืนไม่สำเร็จ
            print(f"[email] แจ้ง admin {admin.email} ไม่สำเร็จ: {e}")


async def return_item(
    db: AsyncSession, admin: User, request_id: uuid.UUID, item_id: uuid.UUID, body: ReturnItemRequest
) -> None:
    """
    ยืนยันรับคืน/สรุปผลอุปกรณ์ (admin only):
    - durable ใช้สถานะ ok/damaged/lost ; consumable ใช้ returned_full/used_up/discarded
    - สถานะที่คืนของเข้าคลัง (ok, returned_full) → เพิ่ม quantity_available กลับ
    - สถานะที่เสียหาย (damaged/lost/discarded) ต้องแนบรูปหลักฐานอย่างน้อย 1 รูป
    - ทุก item สรุปผลครบ → request.status = completed
    """
    req = await _load_request(db, request_id)
    if req.status != "approved":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Request is not in approved status.")

    item = next((i for i in req.items if i.id == item_id), None)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found.")
    if item.returned:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Item already returned.")

    valid = CONSUMABLE_CONDITIONS if item.item_type_snapshot == "consumable" else DURABLE_CONDITIONS
    if body.condition_on_return not in valid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid condition value for this item type.")
    # เสียหาย/สูญหาย/ทิ้ง ต้องมีรูปหลักฐาน
    if body.condition_on_return in PHOTO_REQUIRED_CONDITIONS and not body.damage_photo_urls:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ต้องแนบรูปความเสียหายอย่างน้อย 1 รูป")

    now = datetime.now(timezone.utc)
    item.returned = True
    item.returned_at = now
    item.condition_on_return = body.condition_on_return
    item.damage_note = body.damage_note
    item.damage_photo_urls = body.damage_photo_urls
    item.return_requested = False  # เคลียร์ป้ายแจ้งขอคืน กัน badge ค้างหลังคืนจริงแล้ว
    item.return_requested_at = None
    req.returned_by = admin.id  # ผู้รับคืนล่าสุด — ใบคืนต้องระบุว่าใครรับของมา

    if body.condition_on_return in STOCK_RETURN_CONDITIONS:
        item.equipment.quantity_available += item.quantity

    # ถ้าทุก item returned แล้ว → complete request
    # consumable ถูก auto-return ตอน approve แล้ว ดังนั้น all() ครอบคลุมทั้งหมด
    if all(i.returned for i in req.items):
        req.status = "completed"
        req.returned_at = now

    await _notify(db, req.student_id, "returned_confirmed",
                  f"รับคืนอุปกรณ์จากคำขอ {req.request_code} แล้ว",
                  borrow_request_id=req.id)
    await audit_service.log_action(db, admin, "confirm_return", "borrow_items", item.id,
                                   {"request_code": req.request_code,
                                    "condition": body.condition_on_return})
    await db.commit()

    # แจ้งเตือนนักศึกษาทางอีเมลด้วย
    try:
        await send_email(
            req.student.email,
            f"รับคืนอุปกรณ์จากคำขอ {req.request_code}",
            f"<p>รับคืนอุปกรณ์จากคำขอ <b>{escape(req.request_code)}</b> แล้ว</p>",
        )
    except Exception as e:  # ponytail: อีเมลพังไม่ควรทำให้ผลรับคืนเสีย
        print(f"[email] แจ้งนักศึกษา {req.student.email} ไม่สำเร็จ: {e}")


async def return_all_items(db: AsyncSession, admin: User, request_id: uuid.UUID) -> None:
    """รับคืนครุภัณฑ์ (durable) ทุกชิ้นพร้อมกันแบบสภาพปกติ — admin only

    วัสดุสิ้นเปลือง (consumable) ไม่รวมในปุ่มนี้ ต้องสรุปผลทีละชิ้น (คืนครบ/ใช้หมด/เสียหาย)
    request จะ completed ก็ต่อเมื่อทุก item สรุปผลครบแล้วเท่านั้น
    """
    req = await _load_request(db, request_id)
    if req.status != "approved":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Request is not in approved status.")

    now = datetime.now(timezone.utc)
    for item in req.items:
        if not item.returned and item.item_type_snapshot == "durable":
            item.returned = True
            item.returned_at = now
            item.condition_on_return = "ok"
            item.return_requested = False  # เคลียร์ป้ายแจ้งขอคืน กัน badge ค้างหลังคืนจริงแล้ว
            item.return_requested_at = None
            item.equipment.quantity_available += item.quantity
            req.returned_by = admin.id

    # complete เฉพาะเมื่อไม่มี item ค้างสรุป (รวมวัสดุที่ยังไม่ถูกสรุปผล)
    if all(i.returned for i in req.items):
        req.status = "completed"
        req.returned_at = now

    await _notify(db, req.student_id, "returned_confirmed",
                  f"รับคืนครุภัณฑ์จากคำขอ {req.request_code} แล้ว",
                  borrow_request_id=req.id)
    await audit_service.log_action(db, admin, "confirm_return", "borrow_requests", req.id,
                                   {"request_code": req.request_code, "durable_all": True})
    await db.commit()

    # แจ้งเตือนนักศึกษาทางอีเมลด้วย
    try:
        await send_email(
            req.student.email,
            f"รับคืนครุภัณฑ์จากคำขอ {req.request_code}",
            f"<p>รับคืนครุภัณฑ์จากคำขอ <b>{escape(req.request_code)}</b> แล้ว</p>",
        )
    except Exception as e:  # ponytail: อีเมลพังไม่ควรทำให้ผลรับคืนเสีย
        print(f"[email] แจ้งนักศึกษา {req.student.email} ไม่สำเร็จ: {e}")


async def generate_pdf(
    db: AsyncSession, current_user: User, request_id: uuid.UUID
) -> bytes:
    """สร้าง PDF ใบยืม ตรวจสอบว่าเป็นเจ้าของหรือ admin

    คำขอที่ยังไม่อนุมัติ (pending) ออกเป็น 'ใบร่าง' ฉบับเดียวกับที่นักศึกษาเห็นตอนส่งคำขอ
    แอดมินจึงตรวจเอกสารตัวเดียวกันก่อนกดอนุมัติ ต่างกันแค่มีเลขคำขอจริงแล้ว
    """
    from app.utils.pdf import generate_borrow_pdf, generate_preview_pdf as _gen_preview
    req = await get_request(db, current_user, request_id)
    if req.status == "pending":
        req.due_date = req.requested_due_date
        return _gen_preview(req)
    return generate_borrow_pdf(req)


async def generate_return_pdf(
    db: AsyncSession, current_user: User, request_id: uuid.UUID
) -> bytes:
    """สร้าง PDF ใบรับคืนอุปกรณ์ (สรุปสภาพเมื่อคืน) — เจ้าของหรือ admin"""
    from app.utils.pdf import generate_return_pdf as _gen
    req = await get_request(db, current_user, request_id)
    return _gen(req)


async def generate_preview_pdf(
    db: AsyncSession, current_user: User, body: BorrowRequestCreate
) -> bytes:
    """สร้าง PDF 'ร่างใบยืม' จากตะกร้า ก่อนกดส่งคำขอจริง — ไม่บันทึกลง DB

    ให้ผู้ยืมเห็นเอกสารตัวอย่างก่อนยืนยัน (advisor #3) โดยประกอบ object แบบเดียวกับ
    response จริงจากรายการอุปกรณ์ในตะกร้า แล้วส่งเข้าตัวสร้าง PDF ร่วม
    """
    from app.utils.pdf import generate_preview_pdf as _gen

    ids = [it.equipment_id for it in body.items]
    result = await db.execute(select(Equipment).where(Equipment.id.in_(ids)))
    eq_map = {e.id: e for e in result.scalars().all()}

    items = [
        BorrowItemResponse(
            id=uuid.uuid4(),
            equipment_id=it.equipment_id,
            equipment_name=(eq_map[it.equipment_id].name if it.equipment_id in eq_map else None),
            equipment_code=(eq_map[it.equipment_id].code if it.equipment_id in eq_map else None),
            equipment_unit=(eq_map[it.equipment_id].unit if it.equipment_id in eq_map else None),
            equipment_value=(
                float(eq_map[it.equipment_id].unit_value)
                if it.equipment_id in eq_map and eq_map[it.equipment_id].unit_value is not None
                else None
            ),
            item_type_snapshot=(eq_map[it.equipment_id].item_type if it.equipment_id in eq_map else "durable"),
            quantity=it.quantity,
            returned=False, returned_at=None, condition_on_return=None,
            damage_note=None, damage_photo_urls=None, renewed_count=0, extended_due_date=None,
            return_requested=False, return_requested_at=None,
        )
        for it in body.items
    ]
    now = datetime.now(timezone.utc)
    req = BorrowRequestResponse(
        id=uuid.uuid4(),
        request_code=f"REQ-{now.year}-{_ident(current_user)}-XXXX (ตัวอย่าง — เลขจริงออกเมื่อส่งคำขอ)",
        student_id=current_user.id,
        student_name=current_user.full_name,
        student_email=current_user.email,
        student_number=current_user.student_id,
        purpose=body.purpose,
        status="pending",
        requested_at=now,
        approved_by=None, approved_at=None, rejection_reason=None,
        requested_due_date=body.requested_due_date,
        due_date=body.requested_due_date,
        is_overdue=False, returned_at=None,
        items=items,
    )
    return _gen(req)


async def delete_request(db: AsyncSession, admin: User, request_id: uuid.UUID) -> None:
    """ลบประวัติการยืม — อนุญาตเฉพาะ completed / rejected / cancelled"""
    result = await db.execute(select(BorrowRequest).where(BorrowRequest.id == request_id))
    req = result.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found.")
    if req.status not in ("completed", "rejected", "cancelled"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ลบได้เฉพาะคำขอที่เสร็จสิ้น / ปฏิเสธ / ยกเลิกแล้วเท่านั้น",
        )
    await db.execute(delete(Notification).where(Notification.borrow_request_id == request_id))
    await db.execute(delete(BorrowItem).where(BorrowItem.borrow_request_id == request_id))
    await db.execute(delete(BorrowRequest).where(BorrowRequest.id == request_id))
    await db.commit()


async def send_manual_reminder(db: AsyncSession, request_id: uuid.UUID) -> None:
    """ส่ง reminder แบบ manual โดย admin — ทั้ง in-app และอีเมล"""
    result = await db.execute(
        select(BorrowRequest)
        .options(selectinload(BorrowRequest.student))
        .where(BorrowRequest.id == request_id)
    )
    req = result.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found.")
    if req.status != "approved":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Request is not active.")

    await _notify(db, req.student_id, "due_soon",
                  f"แจ้งเตือน: คำขอ {req.request_code} ครบกำหนดคืนวันที่ {req.due_date}",
                  borrow_request_id=req.id)
    await db.commit()

    try:
        await send_email(
            req.student.email,
            f"แจ้งเตือน: คำขอ {req.request_code} ครบกำหนดคืน",
            f"<p>คำขอยืม <b>{escape(req.request_code)}</b> ครบกำหนดคืนวันที่ {req.due_date} "
            f"กรุณานำอุปกรณ์มาคืน</p>",
        )
    except Exception as e:  # ponytail: อีเมลพังไม่ควรทำให้ส่ง reminder ล้ม
        print(f"[email] แจ้งนักศึกษา {req.student.email} ไม่สำเร็จ: {e}")
