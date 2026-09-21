import os
import uuid
from datetime import date, datetime, timezone, timedelta
from html import escape

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import TZ, settings
from app.models.borrow_item import BorrowItem
from app.models.borrow_request import BorrowRequest
from app.models.equipment import Equipment, equipment_category_links
from app.models.equipment_part import EquipmentPart
from app.models.notification import Notification
from app.models.setting import Setting
from app.models.user import User
from app.schemas.borrow import (
    ApproveRequest,
    BorrowItemResponse,
    BorrowRequestCreate,
    BorrowRequestResponse,
    FineEditRequest,
    FineWaiveRequest,
    PaginatedBorrowRequests,
    ReturnItemRequest,
)
from app.services import audit_service, equipment_service, users_service
from app.utils.duedate import effective_due_date, fmt_date
from app.utils.email import send_email
from app.utils.identity import user_identifier
from app.utils.roles import STAFF_ROLES, is_staff

# กันนักศึกษาพิมพ์วันที่คาดว่าจะคืนเพี้ยน (เช่น อีก 100 ปี) — ไม่ใช่ business rule ที่ต้องปรับตาม
# settings เป็นแค่ sanity cap กันค่าพิมพ์ผิดหลุดเข้าระบบ
MAX_REQUESTED_DUE_DATE_YEARS = 3

# สถานะตอนสรุปผลอุปกรณ์ แยกตามชนิด
DURABLE_CONDITIONS = {"ok", "damaged", "lost"}
CONSUMABLE_CONDITIONS = {"returned_full", "used_up", "discarded"}  # คืนครบ / ใช้หมด / เสียหายทิ้ง
STOCK_RETURN_CONDITIONS = {"ok", "returned_full"}   # สถานะที่คืนของเข้าสต็อก
PHOTO_REQUIRED_CONDITIONS = {"damaged", "lost", "discarded"}  # ต้องแนบรูปหลักฐาน


async def _get_setting_int(db: AsyncSession, key: str) -> int:
    """อ่านค่า int จาก settings — seed data ต้องมีครบ ดู alembic/versions/0002_seed_settings"""
    result = await db.execute(select(Setting).where(Setting.key == key))
    return int(result.scalar_one().value)


async def _get_setting_float(db: AsyncSession, key: str, default: str) -> float:
    """อ่านค่าตัวเงินจาก settings — มี default เผื่อ DB ที่ยังไม่ได้รัน migration ค่าปรับ (0034)"""
    result = await db.execute(select(Setting).where(Setting.key == key))
    row = result.scalar_one_or_none()
    return float(row.value if row else default)


async def _get_setting_str(db: AsyncSession, key: str, default: str) -> str:
    """อ่านค่า string จาก settings — มี default เผื่อ DB ที่ยังไม่ได้รัน migration ล่าสุด
    (ต่างจาก _get_setting_int ที่ยอมพังถ้าไม่มี เพราะค่าพวกนั้นเป็นกฎธุรกิจที่ขาดไม่ได้)
    """
    result = await db.execute(select(Setting).where(Setting.key == key))
    row = result.scalar_one_or_none()
    return row.value if row else default


def _ident(user: User) -> str:
    """ส่วนกลางของเลขคำขอ — ตัดความยาวไว้เพราะ request_code เป็น String(40) และ username ยาวได้ถึง 100"""
    return user_identifier(user)[:20]


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


def _to_utc(dt: datetime) -> datetime:
    """เวลาที่ผู้ใช้กรอกจากหน้าเว็บไม่มี timezone ติดมา — ถือเป็นเวลาไทยเสมอ แล้วเก็บเป็น UTC

    ไม่แปลงจะเพี้ยน 7 ชั่วโมงทันที (นัด 13:00 กลายเป็น 20:00 ในเอกสาร) เพราะ _local ฝั่งแสดงผล
    แปลง UTC → +7 อยู่แล้ว และ asyncpg ต้องการ datetime ที่มี tzinfo สำหรับคอลัมน์ timestamptz
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(timezone.utc)


def _fmt_appoint(dt: datetime | None, location: str | None) -> str:
    """ข้อความนัดหมายในภาษาคน สำหรับแจ้งเตือน/อีเมล เช่น "08/09/2026 เวลา 13:00 น. ที่ ห้องพัสดุ" """
    if not dt:
        return ""
    local = dt.astimezone(TZ) if dt.tzinfo else dt.replace(tzinfo=timezone.utc).astimezone(TZ)
    when = f"{local:%d/%m/%Y} เวลา {local:%H:%M} น."
    return f"{when} ที่ {location}" if location else when


def _validate_requested_due_date(d: date) -> None:
    """วันคืนที่ผู้ใช้เลือกต้องเป็นอนาคตและไม่เกินเพดานกันพิมพ์ผิด — ใช้ทั้งวันของทั้งใบและวันรายชิ้น"""
    if d <= date.today():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Requested return date must be in the future.",
        )
    # timedelta แทน .replace(year=...) กัน ValueError ตอนวันนี้เป็น 29 ก.พ. ปีอธิกสุรทิน
    if d > date.today() + timedelta(days=365 * MAX_REQUESTED_DUE_DATE_YEARS):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Requested return date is too far in the future (max {MAX_REQUESTED_DUE_DATE_YEARS} years).",
        )


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
    is_admin = is_staff(current_user)

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

    _validate_requested_due_date(body.requested_due_date)
    # วันคืนรายชิ้น (เฟส 3) ต้องผ่านด่านเดียวกับวันของทั้งใบ ไม่งั้นเป็นทางอ้อมข้ามเพดาน
    for item_req in body.items:
        if item_req.requested_due_date:
            _validate_requested_due_date(item_req.requested_due_date)

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
    # (eq, quantity, requested_due_date ของบรรทัดนั้น)
    resolved: list[tuple[Equipment, int, date | None]] = []
    for item_req in body.items:
        eq_result = await db.execute(select(Equipment).where(Equipment.id == item_req.equipment_id))
        eq = eq_result.scalar_one_or_none()
        if not eq:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Equipment {item_req.equipment_id} not found.",
            )
        group = (
            [eq] if eq.item_type == "consumable"
            else await equipment_service.find_group_members(db, eq.name, eq.item_type)
        )
        if len(group) <= 1:
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
            if eq.quantity_available < item_req.quantity:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Equipment '{eq.name}' has insufficient stock (available: {eq.quantity_available}).",
                )
            resolved.append((eq, item_req.quantity, item_req.requested_due_date))
        else:
            eligible = [g for g in group if g.is_borrowable and g.status == "available" and g.quantity_available > 0]
            # ลำดับจ่ายของ — จุดเดียวที่ equipment_service.dispatch_order() (ปกติ: ถูกใช้น้อยสุดก่อน ·
            # รุ่นติดตามคุณภาพ + ผู้ยืมเป็นนักศึกษา: จับคู่อายุที่เหลือกับเวลาเรียนที่เหลือ) group มาจาก
            # find_group_members ที่เรียงตาม code ต้องเรียงใหม่ตรงนี้ ไม่ใช่ไปแก้ ORDER BY ของ query
            # (จุดนั้นเป็นลำดับล็อก ห้ามแตะ)
            eligible = await equipment_service.dispatch_order(db, eligible, current_user)
            if len(eligible) < item_req.quantity:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Equipment '{eq.name}' has insufficient stock (available: {len(eligible)}).",
                )
            for unit in eligible[:item_req.quantity]:
                resolved.append((unit, 1, item_req.requested_due_date))

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

    for eq, quantity, item_due in resolved:
        db.add(BorrowItem(
            borrow_request_id=req.id,
            equipment_id=eq.id,
            item_type_snapshot=eq.item_type,
            quantity=quantity,
            # ไม่ระบุวันรายชิ้น = ใช้วันของทั้งใบ (เก็บค่าเดียวกันไว้เลย ให้แอดมินเห็นวันของทุกแถวตอนอนุมัติ)
            requested_due_date=item_due or body.requested_due_date,
            equipment_name=eq.name,
            equipment_code=eq.code,
            equipment_unit=eq.unit,
            equipment_serial_number=eq.serial_number,
        ))

    # แจ้งเตือน admin ทุกคน (in-app) — ยกเว้นตัวเอง กัน admin ที่ยืมของตัวเอง
    # ได้แจ้งเตือน "มีคำขอใหม่" ซ้ำกับคำขอที่ตัวเองเพิ่งส่ง
    admins = (await db.execute(select(User).where(User.role.in_(STAFF_ROLES), User.is_active == True))).scalars().all()
    for admin in admins:
        if admin.id == current_user.id:
            continue
        await _notify(db, admin.id, "new_request_admin",
                      f"คำขอยืมใหม่ {req.request_code} จาก {current_user.full_name}",
                      borrow_request_id=req.id)

    # เก็บชื่ออุปกรณ์ลง detail ตั้งแต่ตอนเขียน (ไม่ join ทีหลัง) — ของอาจถูกลบถาวรได้ ประวัติต้องยังอ่านออก
    await audit_service.log_action(db, current_user, "create_request", "borrow_requests", req.id, {
        "request_code": req.request_code,
        "items": [f"{eq.name} ×{qty}" for eq, qty, _ in resolved],
        "requested_due_date": str(req.requested_due_date),
        "purpose": req.purpose,
    })
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
    needs_attention: bool = False,
    search: str | None = None,
    own_only: bool = False,
    item_type: str | None = None,
    category_id: uuid.UUID | None = None,
) -> PaginatedBorrowRequests:
    """นักศึกษาเห็นแค่ของตัวเอง / admin เห็นทั้งหมด เว้นแต่ own_only=True (บังคับกรองเฉพาะของตัวเอง
    แม้ role เป็น admin — ใช้กับหน้า "คำขอยืมของฉัน" ของ admin เอง แยกจากหน้า "ประวัติการยืมทั้งหมด")

    needs_attention=True: รวมคำขอที่ admin ต้อง "ทำอะไรสักอย่าง" ในหน้าเดียว — pending (รออนุมัติ) +
    approved ที่มี item แจ้งขอคืนแล้ว (return_requested) หรือขอต่อเวลาแล้ว (renew_requested) ไม่ต้องสลับไปหน้า
    "ประวัติทั้งหมด" แยกต่างหาก

    search: ค้นชื่อผู้ยืม/รหัสนักศึกษา/ชื่ออุปกรณ์ในรายการ — ใช้หน้า "ประวัติการยืมทั้งหมด" (admin)

    item_type / category_id: คืนคำขอที่ "มีอย่างน้อย 1 รายการ" ตรงเงื่อนไข (ไม่ใช่ทุกรายการ) —
    คำขอหนึ่งใบยืมของหลายประเภทพร้อมกันได้ กรองแบบ "ทุกรายการต้องตรง" จะได้ผลลัพธ์ว่างเปล่าเป็นส่วนใหญ่
    ต้องกรองที่ชั้นนี้ ไม่ใช่ฝั่ง frontend เพราะรายการถูกแบ่งหน้า (กรองหลังแบ่งหน้าจะได้ผลไม่ครบ)
    """
    query = select(BorrowRequest).options(
        selectinload(BorrowRequest.items).selectinload(BorrowItem.equipment),
        selectinload(BorrowRequest.student),
        # approver_name/receiver_name เป็น property ที่อ่าน relationship ตรงๆ (models/borrow_request.py)
        # ไม่ eager-load จะพัง MissingGreenlet ทันทีที่มีคำขอที่ approved_by/returned_by ไม่ใช่ null
        selectinload(BorrowRequest.approver),
        selectinload(BorrowRequest.receiver),
    )

    if not is_staff(current_user) or own_only:
        query = query.where(BorrowRequest.student_id == current_user.id)
    if needs_attention:
        has_return_requested = (
            select(BorrowItem.id)
            .where(
                BorrowItem.borrow_request_id == BorrowRequest.id,
                BorrowItem.return_requested == True,  # noqa: E712
                BorrowItem.returned == False,  # noqa: E712
            )
            .exists()
        )
        has_renew_requested = (
            select(BorrowItem.id)
            .where(
                BorrowItem.borrow_request_id == BorrowRequest.id,
                BorrowItem.renew_requested == True,  # noqa: E712
            )
            .exists()
        )
        query = query.where(or_(BorrowRequest.status == "pending", has_return_requested, has_renew_requested))
    elif filter_status:
        query = query.where(BorrowRequest.status == filter_status)
    if overdue_only:
        query = query.where(BorrowRequest.is_overdue == True)
    if item_type:
        # ใช้ snapshot บนรายการ ไม่ join equipment — อุปกรณ์ที่ถูกลบถาวรแล้ว (equipment_id = NULL)
        # ต้องยังกรองตามประเภทเดิมได้ ประวัติต้องไม่หายไปเพราะของถูกลบทีหลัง
        query = query.where(
            select(BorrowItem.id).where(
                BorrowItem.borrow_request_id == BorrowRequest.id,
                BorrowItem.item_type_snapshot == item_type,
            ).exists()
        )
    if category_id:
        # หมวดหมู่ไม่มี snapshot จึงต้องผ่าน equipment จริง — รายการที่อุปกรณ์ถูกลบไปแล้วจะไม่เข้าเงื่อนไขนี้
        query = query.where(
            select(BorrowItem.id)
            .join(equipment_category_links,
                  equipment_category_links.c.equipment_id == BorrowItem.equipment_id)
            .where(
                BorrowItem.borrow_request_id == BorrowRequest.id,
                equipment_category_links.c.category_id == category_id,
            ).exists()
        )
    if search:
        pattern = f"%{search}%"
        has_matching_item = (
            select(BorrowItem.id)
            .where(BorrowItem.borrow_request_id == BorrowRequest.id, BorrowItem.equipment_name.ilike(pattern))
            .exists()
        )
        # join กับ users เพื่อค้นชื่อ/รหัสนักศึกษา — ระวัง User.student_id (เลขรหัสนักศึกษา, string) คนละตัวกับ
        # BorrowRequest.student_id (UUID FK ไปหา users.id) ห้ามสลับกัน
        query = query.join(User, User.id == BorrowRequest.student_id).where(
            or_(User.full_name.ilike(pattern), User.student_id.ilike(pattern),
                User.username.ilike(pattern), has_matching_item)
        )

    query = query.order_by(BorrowRequest.requested_at.desc())

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar() or 0

    result = await db.execute(query.offset((page - 1) * page_size).limit(page_size))
    items = list(result.scalars().all())
    await _attach_request_student_year(db, items)
    return PaginatedBorrowRequests(items=items, total=total, page=page, page_size=page_size)  # type: ignore


async def _attach_request_student_year(db: AsyncSession, requests: list[BorrowRequest]) -> None:
    """เติม student_year_label ที่คำนวณจาก setting `academic_year_start` จริง (ไม่ใช่ค่าเริ่มต้นคงที่) ให้
    คำขอแต่ละใบ — BorrowRequest.student_year_label เป็น sync property ไม่มี DB session อ่าน setting เองได้
    จึงต้องให้ service (ที่มี session) คำนวณผ่าน users_service.attach_study_year() ที่เดียวกับหน้าจัดการ
    ผู้ใช้ แล้วเซ็ตค่ากลับผ่าน property setter (ดู models/borrow_request.py) — เรียกจาก list_requests/
    get_request/create_request (ผ่าน get_request) ทุกจุดที่คืน BorrowRequestResponse ให้ไคลเอนต์
    """
    students = [r.student for r in requests if r.student is not None]
    if not students:
        return
    await users_service.attach_study_year(db, students)
    for r in requests:
        if r.student is not None:
            r.student_year_label = r.student.study_year_label


async def get_request(
    db: AsyncSession, current_user: User, request_id: uuid.UUID
) -> BorrowRequestResponse:
    """ดึงคำขอ + รายการอุปกรณ์ทั้งหมด ตรวจสอบว่าเป็นเจ้าของหรือ admin"""
    req = await _load_request(db, request_id)
    if not is_staff(current_user) and req.student_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    await _attach_request_student_year(db, [req])
    return BorrowRequestResponse.model_validate(req)


async def cancel_request(
    db: AsyncSession, current_user: User, request_id: uuid.UUID, reason: str = "",
) -> None:
    """ยกเลิกคำขอที่ status=pending เท่านั้น — บังคับเหตุผล (8 ก.ย. 69)

    เก็บลง `cancel_reason` แยกจาก `rejection_reason` (ของแอดมิน) เพราะเป็นคนละคนพูดคนละเรื่อง
    ถ้าใช้ช่องเดียวกันจะอ่านประวัติไม่ออกว่าใครเป็นคนยกเลิก
    """
    result = await db.execute(select(BorrowRequest).where(BorrowRequest.id == request_id))
    req = result.scalar_one_or_none()
    if not req or req.student_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found.")
    if req.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only pending requests can be cancelled.",
        )
    reason = (reason or "").strip()
    if not reason:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="กรุณาระบุเหตุผลที่ยกเลิกคำขอ")
    req.status = "cancelled"
    req.cancel_reason = reason
    await audit_service.log_action(db, current_user, "cancel_request", "borrow_requests", req.id,
                                   {"request_code": req.request_code, "reason": reason})
    await db.commit()


def _build_item_row_html(item: BorrowItem) -> str:
    """สร้าง HTML แถวรูป+รายละเอียดอุปกรณ์ 1 ชิ้น สำหรับอีเมลอนุมัติคำขอ

    ไม่มีรูป (image_url เป็น None หรือ equipment ถูกลบถาวรไปแล้ว — ON DELETE SET NULL) ใช้กล่องเทาแทน
    ไม่อ้างอิงไฟล์ที่ไม่มีอยู่จริงในอีเมล — โชว์รหัสเสมอเมื่อมีค่า รวมวัสดุสิ้นเปลือง (ตรงกับ pdf.py แล้ว)
    """
    name = escape(item.equipment_name or "-")
    code = escape(item.equipment_code or "-")
    unit = escape(item.equipment_unit or "ชิ้น")
    image_url = item.equipment.image_url if item.equipment else None
    if image_url:
        img_html = (
            f'<img src="{settings.APP_BASE_URL}{image_url}" alt="{name}" '
            f'style="max-width:240px;max-height:180px;border-radius:8px;display:block;margin-bottom:8px;" />'
        )
    else:
        img_html = (
            '<div style="width:240px;height:120px;background:#f3f4f6;border-radius:8px;'
            'display:flex;align-items:center;justify-content:center;color:#9ca3af;'
            'font-size:12px;margin-bottom:8px;">ไม่มีรูปภาพ</div>'
        )
    return (
        '<div style="margin-bottom:16px;padding:12px;border:1px solid #e5e7eb;border-radius:10px;">'
        f'{img_html}'
        '<table style="font-size:13px;color:#374151;border-collapse:collapse;">'
        f'<tr><td style="color:#6b7280;padding:2px 8px 2px 0;">ชื่ออุปกรณ์</td><td style="font-weight:600;">{name}</td></tr>'
        f'<tr><td style="color:#6b7280;padding:2px 8px 2px 0;">รหัส</td><td>{code}</td></tr>'
        f'<tr><td style="color:#6b7280;padding:2px 8px 2px 0;">จำนวน</td><td>{item.quantity} {unit}</td></tr>'
        '</table></div>'
    )


async def approve_request(
    db: AsyncSession, admin: User, request_id: uuid.UUID, body: ApproveRequest | None = None
) -> None:
    """
    อนุมัติคำขอ (ทั้งใบ หรือเลือกอนุมัติบางชิ้น):
    - ลด quantity_available เฉพาะชิ้นที่อนุมัติ (ทั้ง durable และ consumable)
    - วันครบกำหนดของแต่ละชิ้น: แอดมินระบุ > วันที่นักศึกษาขอสำหรับชิ้นนั้น > วันของทั้งใบ
      (ไม่คำนวณจาก setting) ส่วน req.due_date = วันที่ช้าที่สุดของชิ้นที่อนุมัติ ใช้แสดงผลรวม
    - ไม่ส่ง body มาเลย = อนุมัติทุกชิ้นเหมือนพฤติกรรมเดิมทุกประการ
    - ปฏิเสธครบทุกชิ้น = ทั้งใบถูกปฏิเสธ (ไม่มีของออกจากคลังสักชิ้น จะเรียกว่าอนุมัติไม่ได้)
    - หน่วยที่จ่ายจริง: ปกติระบบเลือกหน่วยที่ถูกใช้มาน้อยสุดในรุ่นนั้นให้ แอดมินระบุ equipment_id
      รายชิ้นมาทับได้ (เช่น จ่ายเครื่องที่วางอยู่ตรงหน้าเคาน์เตอร์)
    - ส่งแจ้งเตือนนักศึกษา บอกให้ชัดว่าอนุมัติกี่ชิ้น ชิ้นไหนไม่อนุมัติเพราะอะไร

    ไม่ตั้ง returned=True ให้ item ใดทั้งสิ้น แม้แต่ consumable —
    แอดมินต้องสรุปผลภายหลังว่าคืนครบ/ใช้หมด/เสียหาย (CLAUDE.md §5)
    """
    req = await _load_request(db, request_id)

    if req.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot approve request with status '{req.status}'.",
        )

    decisions = {d.item_id: d for d in (body.items if body else [])}
    if decisions.keys() - {i.id for i in req.items}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found.")

    # แยกชิ้นที่อนุมัติ/ไม่อนุมัติก่อนแตะสต็อก — ชิ้นที่แอดมินไม่พูดถึงถือว่าอนุมัติ
    approved: list[BorrowItem] = []
    rejected: list[tuple[BorrowItem, str]] = []
    due_by_item: dict[uuid.UUID, date] = {}
    # หน่วยที่แอดมินเลือกจ่ายเอง (ทับกฎ "ถูกใช้น้อยสุดก่อน") — ว่าง = ให้ระบบเลือกให้ตามปกติ
    forced_unit_by_item: dict[uuid.UUID, uuid.UUID] = {}
    for item in req.items:
        d = decisions.get(item.id)
        if d and not d.approved:
            reason = (d.rejection_reason or "").strip()
            if not reason:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Rejection reason is required for each rejected item.",
                )
            rejected.append((item, reason))
            continue
        due = (d.due_date if d else None) or item.requested_due_date or req.requested_due_date
        # วันที่ผ่านมาแล้วแปลว่าของเลยกำหนดตั้งแต่วินาทีที่จ่ายออกไป — ไม่ใช่สิ่งที่ตั้งใจแน่ ๆ
        if due < date.today():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Due date for '{item.equipment_name}' must not be in the past.",
            )
        due_by_item[item.id] = due
        if d and d.equipment_id:
            forced_unit_by_item[item.id] = d.equipment_id
        approved.append(item)

    # ล็อกอุปกรณ์ก่อนอ่านค่าสต็อกมาตัดสินใจ — ล็อกทั้ง "กลุ่ม" ของทุก item ไม่ใช่แค่หน่วยที่ผูกไว้ตอนยื่น
    # เพราะรุ่นที่มีหลายหน่วย (ครุภัณฑ์/วัสดุ) หน่วยที่ผูกไว้ตอนยื่นอาจถูกคำขออื่นอนุมัติแซงไปก่อน
    # ต้องเลือกหน่วยอื่นในรุ่นเดียวกันแทนได้ — ไม่มีการล็อกนี้ = แอดมิน 2 คนกดอนุมัติของชิ้นสุดท้ายพร้อมกัน
    # จะอ่านได้ค่าเดียวกันทั้งคู่ ผ่านเงื่อนไขทั้งคู่ แล้วเขียนทับกัน = ปล่อยของชิ้นเดียวออกไป 2 ครั้งโดยไม่มี error
    #   order_by(code)     เรียงลำดับการล็อกให้เหมือนกันทุก transaction กัน deadlock — เป็น "ลำดับล็อก" เท่านั้น
    #                      ส่วน "ลำดับจ่ายของ" เรียงใหม่ทีหลังด้วย dispatch_key (ถูกใช้น้อยสุดก่อน) ดูใต้ลูปนี้
    #   populate_existing  บังคับให้ค่าที่ selectinload โหลดไว้ก่อนหน้าถูกเขียนทับด้วยค่าที่เพิ่งล็อก
    group_keys = {(i.equipment.name, i.equipment.item_type) for i in approved}
    conditions = [(Equipment.name == n) & (Equipment.item_type == t) for n, t in group_keys]
    # ปฏิเสธหมดทั้งใบ = ไม่มีของออกจากคลัง ไม่ต้องล็อกอะไรเลย (or_() ที่ไม่มีเงื่อนไขคือ query ที่ผิด)
    locked_rows = list((await db.execute(
        select(Equipment)
        .where(or_(*conditions))
        .order_by(Equipment.code)
        .with_for_update()
        .execution_options(populate_existing=True)
    )).scalars().all()) if conditions else []
    rows_by_group: dict[tuple[str, str], list[Equipment]] = {}
    for r in locked_rows:
        rows_by_group.setdefault((r.name, r.item_type), []).append(r)
    # ล็อกไปแล้วด้วยลำดับ code (คงเดิม กัน deadlock) — เรียงใหม่ใน memory ด้วย dispatch_order() จุดเดียว
    # (ดู create_request ด้านบน) borrower คือผู้ยืมเจ้าของคำขอ (req.student) ไม่ใช่ admin ที่กำลังอนุมัติ
    usage = await equipment_service.usage_days_map(db, [r.id for r in locked_rows])
    for key in list(rows_by_group.keys()):
        rows_by_group[key] = await equipment_service.dispatch_order(
            db, rows_by_group[key], req.student, usage_days=usage)

    now = datetime.now(timezone.utc)
    dep_years, dep_salvage = await equipment_service._depreciation_settings(db)
    for item in approved:
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
            # รุ่นที่มีหลายหน่วย — เลือกหน่วยที่ถูกใช้มาน้อยสุดซึ่งว่างจริง ณ ตอนนี้เสมอ ไม่ใช่หน่วยที่ผูกไว้ตอนยื่น
            # (group เรียงด้วย dispatch_key แล้วด้านบน) หน่วยเดิมยังว่างก็มักถูกเลือกอยู่ดีเพราะเรียงเกณฑ์เดียวกัน
            # แอดมินระบุหน่วยมาเองได้ (ข้อ 9) — ของจริงบางทีต้องจ่ายเครื่องที่วางอยู่ตรงหน้า ไม่ใช่ที่ระบบเลือก
            forced_id = forced_unit_by_item.get(item.id)
            candidates = [g for g in group if g.id == forced_id] if forced_id else group
            if forced_id and not candidates:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Selected unit is not part of '{eq.name}'.",
                )
            chosen = next(
                (g for g in candidates
                 if g.is_borrowable and g.status == "available" and g.quantity_available >= item.quantity),
                None,
            )
            if chosen is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(f"Selected unit for '{eq.name}' is no longer available."
                            if forced_id else f"Equipment '{eq.name}' no longer has sufficient stock."),
                )
            if chosen.id != eq.id:
                item.equipment_id = chosen.id
                item.equipment = chosen

        # หักสต็อกทั้ง durable และ consumable — ของออกจากคลังแล้ว
        # consumable ไม่ auto-คืนอีกต่อไป: admin ต้องสรุปผลภายหลัง (คืนครบ/ใช้หมด/เสียหาย)
        chosen.quantity_available -= item.quantity
        # ล็อกราคาต่อหน่วย + ชื่อ/รหัส/หน่วยนับ ณ วันอนุมัติ — ต้องเป็นค่าของ chosen (หน่วยที่จัดสรรจริง)
        # ไม่ใช่ eq ตัวที่ยื่นไว้ตอนแรก และต้องล็อกไว้เพราะหลังจากนี้แถว equipment อาจถูกแก้ชื่อ/ปลดระวาง/ลบถาวรได้
        item.unit_value_snapshot = chosen.unit_value
        # มูลค่าตามบัญชีเดินทุกวัน — ต้อง snapshot ณ วันอนุมัติเหมือนราคาทุน ไม่งั้นพิมพ์ใบยืมใบเดิม
        # ซ้ำอีกเดือนจะได้ตัวเลขไม่เท่าเดิม (dep_years/dep_salvage อ่านไว้ครั้งเดียวก่อนลูป)
        item.book_value_snapshot = equipment_service.book_value(chosen, dep_years, dep_salvage)
        item.equipment_name = chosen.name
        item.equipment_code = chosen.code
        item.equipment_unit = chosen.unit
        item.equipment_serial_number = chosen.serial_number

    for item in approved:
        item.item_status = "approved"
        item.due_date = due_by_item[item.id]
    for item, reason in rejected:
        item.item_status = "rejected"
        item.rejection_reason = reason
        item.due_date = None

    # นัดรับของ — เว้นว่างได้ (จ่ายทันทีหน้าเคาน์เตอร์) เก็บเฉพาะตอนอนุมัติจริง
    # ปฏิเสธทั้งใบแล้วยังเก็บนัดไว้ = ผู้ยืมเห็นวันนัดรับของที่ไม่มีวันได้รับ
    if approved and body:
        req.pickup_at = _to_utc(body.pickup_at) if body.pickup_at else None
        req.pickup_location = (body.pickup_location or "").strip() or None
        req.pickup_note = (body.pickup_note or "").strip() or None
    pickup_text = _fmt_appoint(req.pickup_at, req.pickup_location)

    reject_summary = " · ".join(f"{i.equipment_name}: {r}" for i, r in rejected)
    if approved:
        req.status = "approved"
        req.approved_by = admin.id
        req.approved_at = now
        # วันของทั้งใบ = ช้าสุดของชิ้นที่อนุมัติ (ใช้แสดงผลรวมและ index เดิม) ส่วนการทวง/เอกสาร
        # อ่านวันรายชิ้นผ่าน effective_due_date เสมอ
        req.due_date = max(due_by_item.values())
        req.rejection_reason = reject_summary or None
        msg = (f"คำขอ {req.request_code} ได้รับการอนุมัติแล้ว กรุณาคืนภายใน {fmt_date(req.due_date)}"
               if not rejected else
               f"คำขอ {req.request_code} อนุมัติ {len(approved)} จาก {len(req.items)} รายการ "
               f"(กำหนดคืนไม่เกิน {fmt_date(req.due_date)}) — ไม่อนุมัติ: {reject_summary}")
        # นัดรับของต้องอยู่ในแจ้งเตือนบรรทัดเดียวกัน ผู้ยืมจะได้ไม่ต้องเปิดหาว่าไปรับที่ไหนตอนไหน
        if pickup_text:
            msg += f" — รับของ {pickup_text}"
        await _notify(db, req.student_id, "approved", msg, borrow_request_id=req.id)
    else:
        # ไม่มีของออกจากคลังสักชิ้น = ปฏิเสธทั้งใบ (ไม่งั้นใบนี้จะค้างเป็น approved ที่ไม่มีอะไรให้คืน)
        req.status = "rejected"
        req.rejection_reason = reject_summary
        await _notify(db, req.student_id, "rejected",
                      f"คำขอ {req.request_code} ถูกปฏิเสธ: {reject_summary}",
                      borrow_request_id=req.id)

    await audit_service.log_action(
        db, admin, "approve_request" if approved else "reject_request", "borrow_requests", req.id,
        {
            "request_code": req.request_code,
            "due_date": str(req.due_date) if approved else None,
            "approved_items": [f"{i.equipment_name} ({fmt_date(due_by_item[i.id])})" for i in approved],
            "rejected_items": [f"{i.equipment_name}: {r}" for i, r in rejected],
            "pickup": pickup_text or None,
        },
    )
    await db.commit()

    # แจ้งเตือนนักศึกษาทางอีเมลด้วย — ต้อง commit ก่อนเผื่อส่งช้า/พัง ไม่กระทบผลอนุมัติ
    # เหตุผลปฏิเสธเป็นข้อความที่ admin พิมพ์เอง ต้อง escape กัน HTML injection
    try:
        rejected_html = (
            "<p><b>รายการที่ไม่อนุมัติ</b></p><ul>"
            + "".join(f"<li>{escape(i.equipment_name or '-')}: {escape(r)}</li>" for i, r in rejected)
            + "</ul>"
        ) if rejected else ""
        pickup_html = (
            f'<p style="padding:10px;background:#eff6ff;border-radius:8px;">'
            f'<b>นัดรับของ:</b> {escape(pickup_text)}'
            + (f'<br/>{escape(req.pickup_note)}' if req.pickup_note else "")
            + "</p>"
        ) if pickup_text else ""
        if approved:
            item_rows_html = "".join(_build_item_row_html(item) for item in approved)
            await send_email(
                req.student.email,
                f"คำขอ {req.request_code} ได้รับการอนุมัติ",
                f"<h2>สวัสดี {escape(req.student.full_name)}</h2>"
                # อนุมัติครบทุกชิ้น (กรณีปกติ) ใช้ข้อความเดิม — บอก "N จาก M" เฉพาะตอนที่ไม่ครบจริง ๆ
                + (f"<p>มีรายการอุปกรณ์ถูกยืมในชื่อของคุณ ซึ่งคุณได้รับการอนุมัติเรียบร้อยแล้ว "
                   f"กรุณาคืนภายในวันที่ {fmt_date(req.due_date)} รายละเอียดอุปกรณ์อยู่ด้านล่าง</p>"
                   if not rejected else
                   f"<p>คำขอของคุณได้รับการอนุมัติ {len(approved)} จาก {len(req.items)} รายการ "
                   f"กรุณาคืนภายในวันที่ที่ระบุในแต่ละรายการ (ช้าสุด {fmt_date(req.due_date)})</p>")
                + '<p style="padding:10px;background:#fffbeb;border-radius:8px;">'
                  "<b>อย่าลืม:</b> ดาวน์โหลดใบยืมจากหน้า &quot;การยืมของฉัน&quot; "
                  "แล้วปริ้นลงลายเซ็นผู้ยืม นำมาแสดงตอนรับของ "
                  "หรือส่งไฟล์ที่เซ็นแล้วให้เจ้าหน้าที่</p>"
                + f"{pickup_html}{rejected_html}{item_rows_html}",
            )
        else:
            await send_email(
                req.student.email,
                f"คำขอ {req.request_code} ถูกปฏิเสธ",
                f"<p>คำขอยืม <b>{escape(req.request_code)}</b> ไม่ได้รับอนุมัติ</p>{rejected_html}",
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


def _all_settled(req: BorrowRequest) -> bool:
    """คำขอปิดได้หรือยัง — นับเฉพาะชิ้นที่ถูกอนุมัติ ชิ้นที่ไม่อนุมัติไม่เคยออกจากคลังจึงไม่ต้องคืน"""
    return all(i.returned for i in req.items if i.item_status != "rejected")


def _find_item(req: BorrowRequest, item_id: uuid.UUID) -> BorrowItem:
    item = next((i for i in req.items if i.id == item_id), None)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found.")
    return item


async def _recompute_overdue(db: AsyncSession, req: BorrowRequest) -> None:
    """เคลียร์/ตั้งธงเกินกำหนดใหม่จากรายการที่ยังไม่คืน — เรียกซ้ำได้ทุกจุดที่ extended_due_date เปลี่ยน"""
    still_overdue = (await db.execute(
        select(BorrowItem.id).where(
            BorrowItem.borrow_request_id == req.id,
            BorrowItem.returned == False,
            BorrowItem.item_status != "rejected",   # ชิ้นที่ไม่อนุมัติไม่เคยออกจากคลัง ไม่มีวันเกินกำหนด
            func.coalesce(BorrowItem.extended_due_date, BorrowItem.due_date,
                          req.due_date or date.today()) < date.today(),
        ).limit(1)
    )).first()
    req.is_overdue = still_overdue is not None


async def request_renew_item(
    db: AsyncSession, current_user: User, request_id: uuid.UUID, item_id: uuid.UUID,
    requested_date: date, reason: str,
) -> None:
    """นักศึกษายื่นคำขอต่อเวลา (เลือกวันที่+เหตุผลเอง) — แค่ตั้ง flag รอ admin อนุมัติ ยังไม่ขยายกำหนดคืนจริง

    mirror pattern เดียวกับ request_return_items — เช็ค max_renew_count ตอนขอเลย (fail-fast) ไม่รอไปเช็ค
    ตอนอนุมัติ เพราะคำขอที่ปฏิเสธไม่นับครั้งอยู่แล้ว (นับเฉพาะตอนอนุมัติจริงใน approve_renew_item)
    """
    max_renew = await _get_setting_int(db, "max_renew_count")
    max_days_ahead = await _get_setting_int(db, "max_renew_days")

    req = await _load_request(db, request_id)
    if not is_staff(current_user) and req.student_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    if req.status != "approved":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Can only renew items on approved requests.")

    item = _find_item(req, item_id)
    if item.item_status == "rejected":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Item was not approved.")
    if item.returned:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Item already returned.")
    if item.renew_requested:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A renewal request is already pending for this item.")
    if item.renewed_count >= max_renew:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot renew more than {max_renew} time(s).",
        )
    if requested_date <= date.today():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Requested date must be in the future.")
    if requested_date > date.today() + timedelta(days=max_days_ahead):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Requested date is too far ahead (max {max_days_ahead} days from today).",
        )

    item.renew_requested = True
    item.renew_requested_at = datetime.now(timezone.utc)
    item.renew_requested_date = requested_date
    item.renew_reason = reason
    item.renew_rejected_reason = None

    # แจ้งเตือน admin ทุกคน (in-app) — ยกเว้นตัวเอง กัน admin ที่ยืมของตัวเองแจ้งตัวเองซ้ำซ้อน
    admins = (await db.execute(select(User).where(User.role.in_(STAFF_ROLES), User.is_active == True))).scalars().all()
    for admin in admins:
        if admin.id == current_user.id:
            continue
        await _notify(db, admin.id, "renew_requested_admin",
                      f"นักศึกษาแจ้งขอต่อเวลา {item.equipment_name} จากคำขอ {req.request_code}",
                      borrow_request_id=req.id)
    await audit_service.log_action(db, current_user, "request_renew", "borrow_items", item.id, {
        "request_code": req.request_code, "item": item.equipment_name,
        "new_due_date": str(requested_date), "reason": reason,
    })
    await db.commit()

    # แจ้งเตือน admin ทางอีเมลด้วย — ต้อง commit ก่อนเผื่อส่งช้า/พัง ไม่กระทบผลการยื่นคำขอ
    safe_name = escape(current_user.full_name)
    safe_code = escape(req.request_code)
    safe_item = escape(item.equipment_name or "")
    for admin in admins:
        if admin.id == current_user.id:
            continue
        try:
            await send_email(
                admin.email,
                f"นักศึกษาแจ้งขอต่อเวลาคำขอ {req.request_code}",
                f"<p>{safe_name} แจ้งขอต่อเวลา <b>{safe_item}</b> จากคำขอ <b>{safe_code}</b> "
                f"ถึงวันที่ {fmt_date(requested_date)} กรุณาเข้าระบบเพื่อตรวจสอบและอนุมัติ/ปฏิเสธ</p>",
            )
        except Exception as e:  # ponytail: อีเมลพังไม่ควรทำให้ยื่นคำขอไม่สำเร็จ
            print(f"[email] แจ้ง admin {admin.email} ไม่สำเร็จ: {e}")


async def approve_renew_item(
    db: AsyncSession, admin: User, request_id: uuid.UUID, item_id: uuid.UUID
) -> None:
    """อนุมัติคำขอต่อเวลา — ขยาย extended_due_date ไปตามวันที่นักศึกษาขอ + นับ renewed_count"""
    req = await _load_request(db, request_id)
    item = _find_item(req, item_id)
    if not item.renew_requested:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No pending renewal request for this item.")

    old_due = effective_due_date(item, req)
    item.extended_due_date = item.renew_requested_date
    item.renewed_count += 1
    item.renew_requested = False
    item.renew_requested_at = None
    item.renew_rejected_reason = None

    await _recompute_overdue(db, req)

    await _notify(db, req.student_id, "renew_approved",
                  f"คำขอต่อเวลา {item.equipment_name} จากคำขอ {req.request_code} ได้รับการอนุมัติ "
                  f"กำหนดคืนใหม่ {fmt_date(item.extended_due_date)}",
                  borrow_request_id=req.id)
    await audit_service.log_action(db, admin, "approve_renew", "borrow_items", item.id, {
        "request_code": req.request_code, "item": item.equipment_name,
        "old_due_date": str(old_due) if old_due else None,
        "new_due_date": str(item.extended_due_date),
    })
    await db.commit()

    try:
        await send_email(
            req.student.email,
            f"คำขอต่อเวลา {req.request_code} ได้รับการอนุมัติ",
            f"<p>คำขอต่อเวลา <b>{escape(item.equipment_name or '')}</b> จากคำขอ <b>{escape(req.request_code)}</b> "
            f"ได้รับการอนุมัติแล้ว กำหนดคืนใหม่ {fmt_date(item.extended_due_date)}</p>",
        )
    except Exception as e:  # ponytail: อีเมลพังไม่ควรทำให้ผลอนุมัติเสีย
        print(f"[email] แจ้งนักศึกษา {req.student.email} ไม่สำเร็จ: {e}")


async def reject_renew_item(
    db: AsyncSession, admin: User, request_id: uuid.UUID, item_id: uuid.UUID, reason: str
) -> None:
    """ปฏิเสธคำขอต่อเวลา — ไม่แตะ renewed_count/extended_due_date เลย (ไม่นับเป็นครั้งที่ใช้ไป)"""
    req = await _load_request(db, request_id)
    item = _find_item(req, item_id)
    if not item.renew_requested:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No pending renewal request for this item.")

    item.renew_rejected_reason = reason
    item.renew_requested = False
    item.renew_requested_at = None

    await _notify(db, req.student_id, "renew_rejected",
                  f"คำขอต่อเวลา {item.equipment_name} จากคำขอ {req.request_code} ถูกปฏิเสธ: {reason}",
                  borrow_request_id=req.id)
    await audit_service.log_action(db, admin, "reject_renew", "borrow_items", item.id, {
        "request_code": req.request_code, "item": item.equipment_name, "reason": reason,
    })
    await db.commit()

    try:
        await send_email(
            req.student.email,
            f"คำขอต่อเวลา {req.request_code} ถูกปฏิเสธ",
            f"<p>คำขอต่อเวลา <b>{escape(item.equipment_name or '')}</b> จากคำขอ <b>{escape(req.request_code)}</b> "
            f"ถูกปฏิเสธ: {escape(reason)}</p>",
        )
    except Exception as e:  # ponytail: อีเมลพังไม่ควรทำให้ผลปฏิเสธเสีย
        print(f"[email] แจ้งนักศึกษา {req.student.email} ไม่สำเร็จ: {e}")


async def request_return_items(
    db: AsyncSession, current_user: User, request_id: uuid.UUID, item_ids: list[uuid.UUID],
    appoint_at: datetime, appoint_location: str,
) -> None:
    """นักศึกษาแจ้งขอคืนอุปกรณ์ (ทีละชิ้น/หลายชิ้น/ทั้งหมด) พร้อม**นัดวัน-เวลา-สถานที่** — แค่ตั้ง flag แจ้ง admin

    นัดหมายบังคับกรอกตั้งแต่เฟส 4 (feedback อาจารย์ ข้อ 12) เก็บรายชิ้นเพราะคืนแยกชิ้นได้
    ไม่แตะ returned/quantity_available เลย — การคืนจริงยังต้องผ่าน return_item/return_all_items
    (admin only) เหมือนเดิมทุกประการ ตาม CLAUDE.md ข้อ 5
    """
    req = await _load_request(db, request_id)
    if not is_staff(current_user) and req.student_id != current_user.id:
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
        if item.item_status == "rejected":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Item was not approved.")
        if item.returned:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Item already returned.")
        matched.append(item)

    appoint_at = _to_utc(appoint_at)
    if appoint_at < datetime.now(timezone.utc) - timedelta(hours=1):
        # เผื่อ 1 ชม. ให้คนที่กำลังเดินมาคืน "เมื่อกี้" แต่ห้ามนัดย้อนหลังเป็นวัน ๆ (คิวจะเพี้ยน)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Return appointment must not be in the past.")

    now = datetime.now(timezone.utc)
    for item in matched:
        item.return_requested = True
        item.return_requested_at = now
        item.return_appoint_at = appoint_at
        item.return_appoint_location = appoint_location

    appoint_text = _fmt_appoint(appoint_at, appoint_location)
    # แจ้งเตือน admin ทุกคน (in-app) — ยกเว้นตัวเอง กัน admin ที่ยืมของตัวเองแจ้งตัวเองซ้ำซ้อน
    admins = (await db.execute(select(User).where(User.role.in_(STAFF_ROLES), User.is_active == True))).scalars().all()
    for admin in admins:
        if admin.id == current_user.id:
            continue
        await _notify(db, admin.id, "return_requested_admin",
                      f"{current_user.full_name} นัดคืนอุปกรณ์ {len(matched)} รายการ "
                      f"จากคำขอ {req.request_code} — {appoint_text}",
                      borrow_request_id=req.id)
    # log ระดับคำขอ (ไม่ใช่รายชิ้น) — แจ้งขอคืนทีเดียวหลายชิ้น เขียนแถวเดียวพอ
    await audit_service.log_action(db, current_user, "request_return", "borrow_requests", req.id, {
        "request_code": req.request_code,
        "items": [i.equipment_name for i in matched],
        "count": len(matched),
        "appointment": appoint_text,
    })
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
                f"นักศึกษานัดคืนอุปกรณ์ คำขอ {req.request_code}",
                f"<p>{safe_name} แจ้งขอคืนอุปกรณ์ {len(matched)} รายการจากคำขอ <b>{safe_code}</b></p>"
                f"<p><b>นัดคืน:</b> {escape(appoint_text)}</p>"
                f"<p>กรุณาเข้าระบบเพื่อตรวจสอบและยืนยันรับคืน</p>",
            )
        except Exception as e:  # ponytail: อีเมลพังไม่ควรทำให้แจ้งขอคืนไม่สำเร็จ
            print(f"[email] แจ้ง admin {admin.email} ไม่สำเร็จ: {e}")


# ใบยืมที่เซ็นแล้วมักมาเป็นไฟล์สแกน PDF หรือรูปถ่ายจากมือถือ (ไฟล์ใหญ่กว่ารูปอุปกรณ์จึงให้ถึง 10MB)
SIGNED_FORM_EXT = {".pdf", ".jpg", ".jpeg", ".png", ".webp"}
SIGNED_FORM_MAX_BYTES = 10 * 1024 * 1024


def _assert_can_see_request(req: BorrowRequest, user: User) -> None:
    """เจ้าของคำขอหรือเจ้าหน้าที่เท่านั้น — ใช้ร่วมกันทั้งอัปโหลดและเปิดดูใบยืมที่เซ็นแล้ว"""
    if not is_staff(user) and req.student_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")


async def upload_signed_form(
    db: AsyncSession, current_user: User, request_id: uuid.UUID, file: UploadFile
) -> str:
    """ผู้ยืมอัปโหลดใบยืมที่เซ็นแล้ว แทนการปริ้นถือมาแสดงตอนรับของ — คืนชื่อไฟล์ที่เก็บ

    เก็บไฟล์ล่าสุดไฟล์เดียวต่อคำขอ (อัปโหลดใหม่ = ทับของเดิม) เพราะเอกสารที่มีผลคือฉบับล่าสุดเสมอ
    ไฟล์เก่ายังค้างในโฟลเดอร์โดยตั้งใจ — ถ้าเถียงกันว่าเซ็นอะไรไว้ ยังตามชื่อไฟล์จาก audit log ได้

    เฟส 7: ไฟล์ไปอยู่ใน PRIVATE_UPLOAD_DIR ที่ไม่ได้ mount เป็น static แล้ว (ของเดิมอยู่ /uploads
    ที่เปิดได้ด้วย URL เปล่า = เอกสารที่มีลายเซ็น+ชื่อ+รหัส นศ. หลุดถ้าลิงก์รั่ว) เปิดดูได้ทาง
    get_signed_form() ที่ตรวจสิทธิ์เท่านั้น และตรวจ magic bytes กันไฟล์ปลอมนามสกุลตั้งแต่ตอนรับเข้า
    """
    req = await _load_request(db, request_id)
    _assert_can_see_request(req, current_user)
    # ใบร่างยังไม่มีเลขครุภัณฑ์/วันคืนจริง เซ็นมาก่อนอนุมัติก็ไม่มีความหมาย
    if req.status != "approved":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Can only upload signed form on approved requests.")

    filename = await equipment_service.save_private_upload(
        file, SIGNED_FORM_EXT, SIGNED_FORM_MAX_BYTES)
    req.signed_form_file = filename
    req.signed_form_at = datetime.now(timezone.utc)

    admins = (await db.execute(
        select(User).where(User.role.in_(STAFF_ROLES), User.is_active == True)
    )).scalars().all()
    for admin in admins:
        if admin.id == current_user.id:
            continue
        await _notify(db, admin.id, "signed_form_uploaded",
                      f"{current_user.full_name} อัปโหลดใบยืมที่เซ็นแล้วของคำขอ {req.request_code}",
                      borrow_request_id=req.id)
    await audit_service.log_action(db, current_user, "upload_signed_form", "borrow_requests", req.id, {
        "request_code": req.request_code,
        "file": filename,
    })
    await db.commit()
    return filename


async def get_signed_form(
    db: AsyncSession, current_user: User, request_id: uuid.UUID
) -> tuple[str, str]:
    """คืน (path จริงบนดิสก์, ชื่อไฟล์) ของใบยืมที่เซ็นแล้ว หลังตรวจสิทธิ์ — เจ้าของคำขอหรือเจ้าหน้าที่

    ประกอบ path จาก basename เท่านั้น (ค่าที่เก็บถูกตั้งเป็น uuid ตอนอัปโหลดอยู่แล้ว) กัน path
    traversal ถ้าวันหนึ่งมีใครเขียนค่าลงคอลัมน์นี้จากทางอื่น — ../ ใด ๆ จะถูกตัดทิ้งก่อนเปิดไฟล์

    ลง audit ทุกครั้งที่เปิดดูตามที่ตกลงในแผนเฟส 7 — เอกสารมีข้อมูลส่วนบุคคล ต้องตอบได้ว่าใครเปิดดูบ้าง
    """
    req = await _load_request(db, request_id)
    _assert_can_see_request(req, current_user)
    if not req.signed_form_file:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No signed form uploaded.")

    filename = os.path.basename(req.signed_form_file)
    path = os.path.join(settings.PRIVATE_UPLOAD_DIR, filename)
    if not os.path.isfile(path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Signed form file is missing.")

    await audit_service.log_action(db, current_user, "view_signed_form", "borrow_requests", req.id, {
        "request_code": req.request_code,
        "file": filename,
    })
    await db.commit()
    return path, filename


async def _fine_settings(db: AsyncSession) -> tuple[float, int, float]:
    """อัตราค่าปรับที่ใช้อยู่ ณ ตอนนี้ — (บาท/วัน, วันผ่อนผัน, เพดานต่อรายการ) อ่านทีเดียวต่อการรับคืน 1 ครั้ง"""
    return (
        await _get_setting_float(db, "fine_per_day_per_item", "10"),
        int(await _get_setting_float(db, "fine_grace_days", "0")),
        await _get_setting_float(db, "fine_max_per_item", "0"),
    )


def _compute_fine(
    item: BorrowItem, req: BorrowRequest, condition: str, returned_date: date,
    rate: float, grace_days: int, cap: float,
) -> dict:
    """คำนวณค่าปรับของอุปกรณ์ 1 ชิ้น ณ วันที่รับคืน — ฟังก์ชันบริสุทธิ์ ไม่แตะ DB (เทสได้ตรง ๆ)

    ค่าปรับล่าช้า = (วันที่คืนจริง − วันครบกำหนดที่ใช้จริง − วันผ่อนผัน) × อัตราต่อวัน จำกัดที่เพดาน
    ค่าเสียหาย   = มูลค่าตามบัญชี ณ วันอนุมัติ (book_value_snapshot) เฉพาะสถานะที่ของไม่ได้กลับเข้าคลัง

    ใช้ book_value ไม่ใช่ราคาที่ซื้อ เพราะเป็นมูลค่าที่หักค่าเสื่อมตามอายุแล้ว มีที่มาตามระเบียบพัสดุ
    และ **ไม่ใช่** สถิติการใช้งาน (จำนวนครั้ง/วันที่ถูกยืม ในหน้าความคุ้มค่า) ซึ่งเรียกเป็นเงินไม่ได้
    """
    due = effective_due_date(item, req)
    days_late = max(0, (returned_date - due).days - grace_days) if due and returned_date > due else 0
    late_amount = round(days_late * rate, 2)
    if cap > 0:
        late_amount = min(late_amount, cap)

    damage_amount = 0.0
    if condition in PHOTO_REQUIRED_CONDITIONS and item.book_value_snapshot is not None:
        damage_amount = float(item.book_value_snapshot)

    return {
        "days_late": days_late,
        "late_amount": late_amount,
        "damage_amount": damage_amount,
        "basis": {
            "due_date": due.isoformat() if due else None,
            "returned_date": returned_date.isoformat(),
            "condition": condition,
            "rate_per_day": rate,
            "grace_days": grace_days,
            "cap": cap or None,
            "book_value_used": damage_amount or None,
        },
    }


def _apply_fine(item: BorrowItem, calc: dict, late_override: float | None = None,
                damage_override: float | None = None) -> float:
    """เขียนผลการคำนวณลงแถว (freeze) แล้วคืนยอดรวม — ยอดที่แอดมินกรอกทับชนะค่าที่คำนวณได้

    เก็บ basis ที่คำนวณได้ไว้เสมอแม้จะถูกกรอกทับ เพื่อให้ยังตอบได้ว่า "ระบบคิดเท่าไหร่ ทำไมถึงแก้"
    """
    item.fine_days_late = calc["days_late"]
    item.fine_late_amount = round(late_override, 2) if late_override is not None else calc["late_amount"]
    item.fine_damage_amount = round(damage_override, 2) if damage_override is not None else calc["damage_amount"]
    basis = dict(calc["basis"])
    if late_override is not None or damage_override is not None:
        basis["computed_late_amount"] = calc["late_amount"]
        basis["computed_damage_amount"] = calc["damage_amount"]
    item.fine_basis = basis
    total = float(item.fine_late_amount) + float(item.fine_damage_amount)
    item.fine_status = "unpaid" if total > 0 else "none"
    return total


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
    if item.item_status == "rejected":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Item was not approved.")
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
    item.return_appoint_at = None   # คิวนัดคืนต้องหายจากหน้าแอดมินทันทีที่รับของแล้ว
    req.returned_by = admin.id  # ผู้รับคืนล่าสุด — ใบคืนต้องระบุว่าใครรับของมา

    if body.condition_on_return in STOCK_RETURN_CONDITIONS:
        item.equipment.quantity_available += item.quantity
    elif body.condition_on_return in PHOTO_REQUIRED_CONDITIONS and item.equipment.quantity_total == 1:
        # แถวนี้แทนหน่วยเดียว (ไม่ใช่ก้อนวัสดุ/สิ้นเปลืองที่ยังไม่แยกรายชิ้น quantity_total>1) — เสีย/สูญหาย/ทิ้ง
        # แล้วเป็นสถานะจริงของอุปกรณ์ชิ้นนั้นเลย ไม่ใช่แค่ตัวเลขสต็อกลด ไม่งั้น status ค้าง "available" ทั้งที่
        # ของหายไปแล้วจริง ๆ (เจอบั๊กจริง — quantity_available เหลือ 0 แต่ status ยังขึ้น "พร้อม" ให้ยืม)
        # quantity_total>1 ไม่แตะ status เพราะแค่หน่วยเดียวในก้อนเสีย ไม่ได้แปลว่าทั้งก้อนเสียหมด
        item.equipment.status = "unavailable" if body.condition_on_return == "lost" else "damaged"

    rate, grace, cap = await _fine_settings(db)
    calc = _compute_fine(item, req, body.condition_on_return, now.astimezone(TZ).date(), rate, grace, cap)
    fine_total = _apply_fine(item, calc, body.fine_late_amount_override, body.fine_damage_amount_override)

    # ถ้าทุก item returned แล้ว → complete request
    # ข้ามชิ้นที่แอดมินไม่อนุมัติ (ไม่เคยออกจากคลัง ไม่มีอะไรให้คืน) ไม่งั้นคำขอจะไม่มีวันปิด
    if _all_settled(req):
        req.status = "completed"
        req.returned_at = now

    fine_note = f" · มีค่าปรับ {fine_total:,.2f} บาท" if fine_total > 0 else ""
    await _notify(db, req.student_id, "returned_confirmed",
                  f"รับคืนอุปกรณ์จากคำขอ {req.request_code} แล้ว{fine_note}",
                  borrow_request_id=req.id)
    await audit_service.log_action(db, admin, "confirm_return", "borrow_items", item.id,
                                   {"request_code": req.request_code,
                                    "item": item.equipment_name,
                                    "condition": body.condition_on_return,
                                    **({"fine_days_late": item.fine_days_late,
                                        "fine_late_amount": float(item.fine_late_amount),
                                        "fine_damage_amount": float(item.fine_damage_amount)}
                                       if fine_total > 0 else {})})
    await db.commit()

    # ประเมินคุณภาพใหม่ (ไม่บังคับ) — จังหวะที่ 4 ของ 4 จังหวะให้ประเมิน (ดู CLAUDE.md): รับคืนแบบชำรุด
    # เฉพาะเครื่องที่เปิดติดตามคุณภาพอยู่เท่านั้น ไม่ส่ง quality_after มา = ไม่แตะค่าคุณภาพเลย
    if (body.condition_on_return == "damaged" and body.quality_after is not None
            and item.equipment is not None and item.equipment.quality_tracked):
        await equipment_service.assess_quality(
            db, admin, item.equipment.id, body.quality_after,
            f"รับคืนแบบชำรุด: {req.request_code}", event="return_damaged",
        )

    # แจ้งเตือนนักศึกษาทางอีเมลด้วย
    try:
        await send_email(
            req.student.email,
            f"รับคืนอุปกรณ์จากคำขอ {req.request_code}",
            f"<p>รับคืนอุปกรณ์จากคำขอ <b>{escape(req.request_code)}</b> แล้ว</p>"
            + (f"<p>มีค่าปรับ <b>{fine_total:,.2f} บาท</b> "
               f"(ล่าช้า {item.fine_days_late} วัน) ดูรายละเอียดได้ในหน้าประวัติการยืม</p>"
               if fine_total > 0 else ""),
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
    rate, grace, cap = await _fine_settings(db)
    fine_total = 0.0
    for item in req.items:
        if not item.returned and item.item_status != "rejected" and item.item_type_snapshot == "durable":
            item.returned = True
            item.returned_at = now
            item.condition_on_return = "ok"
            item.return_requested = False  # เคลียร์ป้ายแจ้งขอคืน กัน badge ค้างหลังคืนจริงแล้ว
            item.return_requested_at = None
            item.return_appoint_at = None
            item.equipment.quantity_available += item.quantity
            req.returned_by = admin.id
            # คืนสภาพปกติก็ยังโดนค่าปรับได้ถ้าเลยกำหนด — ปุ่มลัดนี้ไม่ใช่ทางหนีค่าปรับ
            fine_total += _apply_fine(
                item, _compute_fine(item, req, "ok", now.astimezone(TZ).date(), rate, grace, cap))

    # complete เฉพาะเมื่อไม่มี item ค้างสรุป (รวมวัสดุที่ยังไม่ถูกสรุปผล)
    if _all_settled(req):
        req.status = "completed"
        req.returned_at = now

    fine_note = f" · มีค่าปรับรวม {fine_total:,.2f} บาท" if fine_total > 0 else ""
    await _notify(db, req.student_id, "returned_confirmed",
                  f"รับคืนครุภัณฑ์จากคำขอ {req.request_code} แล้ว{fine_note}",
                  borrow_request_id=req.id)
    await audit_service.log_action(db, admin, "confirm_return", "borrow_requests", req.id,
                                   {"request_code": req.request_code, "durable_all": True,
                                    **({"fine_late_amount": round(fine_total, 2)} if fine_total > 0 else {})})
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
    value_source = await _get_setting_str(db, "pdf_value_source", "acquisition")
    if req.status == "pending":
        req.due_date = req.requested_due_date
        return _gen_preview(req, value_source)
    await _attach_equipment_specs(db, req)
    return generate_borrow_pdf(req, value_source)


async def _attach_equipment_specs(db: AsyncSession, req: BorrowRequestResponse) -> None:
    """เติมสเปกของชิ้นส่วนที่ติดตั้งอยู่ ณ ตอนนี้ ลงในรายการของใบยืม (เฟส 8, ข้อ 17)

    ครุภัณฑ์ที่ผ่านการอัพเกรด (RAM/SSD) ต้องระบุในเอกสารที่ผู้ยืมเซ็นว่ารับของไปทั้งอะไรบ้าง
    ไม่งั้นคืนมาแล้วของหายไปชิ้นหนึ่งก็เถียงกันไม่ได้ว่าตอนรับไปมีหรือเปล่า
    """
    eq_ids = [i.equipment_id for i in req.items if i.equipment_id]
    if not eq_ids:
        return
    rows = (await db.execute(
        select(EquipmentPart.equipment_id, EquipmentPart.name)
        .where(EquipmentPart.equipment_id.in_(eq_ids), EquipmentPart.removed_at.is_(None))
        .order_by(EquipmentPart.acquired_at)
    )).all()
    if not rows:
        return
    specs: dict[uuid.UUID, list[str]] = {}
    for eq_id, name in rows:
        specs.setdefault(eq_id, []).append(name)
    for item in req.items:
        names = specs.get(item.equipment_id)
        if names:
            item.equipment_specs = " · ".join(names)


async def generate_return_pdf(
    db: AsyncSession, current_user: User, request_id: uuid.UUID
) -> bytes:
    """สร้าง PDF ใบรับคืนอุปกรณ์ (สรุปสภาพเมื่อคืน) — เจ้าของหรือ admin"""
    from app.utils.pdf import generate_return_pdf as _gen
    req = await get_request(db, current_user, request_id)
    return _gen(req, await _get_setting_str(db, "pdf_value_source", "acquisition"))


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
    dep_years, dep_salvage = await equipment_service._depreciation_settings(db)

    items = [
        BorrowItemResponse(
            id=uuid.uuid4(),
            equipment_id=it.equipment_id,
            equipment_name=(eq_map[it.equipment_id].name if it.equipment_id in eq_map else None),
            equipment_code=(eq_map[it.equipment_id].code if it.equipment_id in eq_map else None),
            equipment_unit=(eq_map[it.equipment_id].unit if it.equipment_id in eq_map else None),
            equipment_serial_number=(
                eq_map[it.equipment_id].serial_number if it.equipment_id in eq_map else None
            ),
            equipment_value=(
                float(eq_map[it.equipment_id].unit_value)
                if it.equipment_id in eq_map and eq_map[it.equipment_id].unit_value is not None
                else None
            ),
            # ร่างยังไม่มี snapshot (ยังไม่อนุมัติ) → คำนวณสดจากของในคลัง ณ ตอนเปิดดูร่าง
            book_value=(
                equipment_service.book_value(eq_map[it.equipment_id], dep_years, dep_salvage)
                if it.equipment_id in eq_map else None
            ),
            item_type_snapshot=(eq_map[it.equipment_id].item_type if it.equipment_id in eq_map else "durable"),
            quantity=it.quantity,
            # ร่างยังไม่มีวันครบกำหนดจริง — ใบร่างพิมพ์วันที่ "ขอไว้" ของแต่ละชิ้น (ไม่ระบุ = วันของทั้งใบ)
            requested_due_date=it.requested_due_date or body.requested_due_date,
            due_date=None,
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
        borrower_identifier=user_identifier(current_user),
        borrower_is_student=bool(current_user.student_id),
        student_major=current_user.major,
        purpose=body.purpose,
        status="pending",
        requested_at=now,
        approved_by=None, approved_at=None, rejection_reason=None,
        requested_due_date=body.requested_due_date,
        due_date=body.requested_due_date,
        is_overdue=False, returned_at=None,
        items=items,
    )
    return _gen(req, await _get_setting_str(db, "pdf_value_source", "acquisition"))


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
    # log ก่อนลบ — ต้องอ่านค่าจากแถวที่กำลังจะหายไป และการลบประวัติเป็นการกระทำที่ต้องตรวจสอบได้ที่สุด
    await audit_service.log_action(db, admin, "delete_request", "borrow_requests", req.id, {
        "request_code": req.request_code, "status": req.status,
    })
    await db.execute(delete(Notification).where(Notification.borrow_request_id == request_id))
    await db.execute(delete(BorrowItem).where(BorrowItem.borrow_request_id == request_id))
    await db.execute(delete(BorrowRequest).where(BorrowRequest.id == request_id))
    await db.commit()


async def send_manual_reminder(db: AsyncSession, request_id: uuid.UUID) -> None:
    """ส่ง reminder แบบ manual โดย admin — ทั้ง in-app และอีเมล

    ทวงด้วยวัน "ที่ใกล้ที่สุดของชิ้นที่ยังไม่คืน" ไม่ใช่วันช้าสุดของทั้งใบ ตั้งแต่วันคืนแยกรายชิ้นได้
    (ทวงด้วยวันช้าสุด = บอกให้ผู้ยืมคืนช้ากว่ากำหนดจริงของบางชิ้น)
    """
    req = await _load_request(db, request_id)
    if req.status != "approved":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Request is not active.")

    dues = [d for d in (effective_due_date(i, req) for i in req.items
                        if not i.returned and i.item_status != "rejected") if d]
    due = min(dues) if dues else req.due_date

    await _notify(db, req.student_id, "due_soon",
                  f"แจ้งเตือน: คำขอ {req.request_code} ครบกำหนดคืนวันที่ {fmt_date(due)}",
                  borrow_request_id=req.id)
    await db.commit()

    try:
        await send_email(
            req.student.email,
            f"แจ้งเตือน: คำขอ {req.request_code} ครบกำหนดคืน",
            f"<p>คำขอยืม <b>{escape(req.request_code)}</b> ครบกำหนดคืนวันที่ {fmt_date(due)} "
            f"กรุณานำอุปกรณ์มาคืน</p>",
        )
    except Exception as e:  # ponytail: อีเมลพังไม่ควรทำให้ส่ง reminder ล้ม
        print(f"[email] แจ้งนักศึกษา {req.student.email} ไม่สำเร็จ: {e}")


def _load_fine_item(req: BorrowRequest, item_id: uuid.UUID) -> BorrowItem:
    """หารายการที่มีค่าปรับค้างชำระ — ทั้ง 3 การกระทำ (แก้ยอด/ชำระ/ยกเว้น) ทำได้เฉพาะสถานะ unpaid

    ยอดที่ชำระแล้วหรือยกเว้นแล้วคือสถานะปลายทาง แก้ต่อไม่ได้ ไม่งั้นประวัติการเงินย้อนหลังเปลี่ยนได้เรื่อย ๆ
    """
    item = next((i for i in req.items if i.id == item_id), None)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found.")
    if item.fine_status != "unpaid":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="ทำได้เฉพาะค่าปรับที่ยังค้างชำระเท่านั้น")
    return item


async def update_fine(
    db: AsyncSession, admin: User, request_id: uuid.UUID, item_id: uuid.UUID, body: FineEditRequest
) -> None:
    """แก้ยอดค่าปรับที่ระบบคิดให้ (เจ้าหน้าที่) — บังคับกรอกเหตุผลเพราะเป็นการแก้ตัวเลขที่เรียกเงิน

    ยอดใหม่แทนที่ของเดิมทั้งคู่ ส่วน fine_basis (อัตรา/วันที่ใช้คำนวณ) คงไว้ตามเดิม
    เพื่อให้ยังเทียบได้ว่าสูตรคิดเท่าไหร่ แล้วคนแก้เป็นเท่าไหร่ ด้วยเหตุผลอะไร
    """
    req = await _load_request(db, request_id)
    item = _load_fine_item(req, item_id)

    old = (float(item.fine_late_amount or 0), float(item.fine_damage_amount or 0))
    item.fine_late_amount = round(body.late_amount, 2)
    item.fine_damage_amount = round(body.damage_amount, 2)
    if item.fine_total <= 0:
        item.fine_status = "none"

    await audit_service.log_action(db, admin, "update_fine", "borrow_items", item.id, {
        "request_code": req.request_code,
        "item": item.equipment_name,
        "changes": {
            "fine_late_amount": [old[0], float(item.fine_late_amount)],
            "fine_damage_amount": [old[1], float(item.fine_damage_amount)],
        },
        "reason": body.reason,
    })
    await db.commit()


async def pay_fine(db: AsyncSession, admin: User, request_id: uuid.UUID, item_id: uuid.UUID) -> None:
    """บันทึกว่าชำระค่าปรับแล้ว (เจ้าหน้าที่) — ระบบไม่รับเงินเอง แค่บันทึกว่ารับไว้แล้วเมื่อไหร่โดยใคร"""
    req = await _load_request(db, request_id)
    item = _load_fine_item(req, item_id)
    item.fine_status = "paid"

    await audit_service.log_action(db, admin, "pay_fine", "borrow_items", item.id, {
        "request_code": req.request_code, "item": item.equipment_name, "amount": item.fine_total,
    })
    await _notify(db, req.student_id, "fine_paid",
                  f"บันทึกการชำระค่าปรับ {item.fine_total:,.2f} บาท ของคำขอ {req.request_code} แล้ว",
                  borrow_request_id=req.id)
    await db.commit()


async def waive_fine(
    db: AsyncSession, superadmin: User, request_id: uuid.UUID, item_id: uuid.UUID, body: FineWaiveRequest
) -> None:
    """ยกเว้นค่าปรับ (superadmin เท่านั้น) — ยอดเดิมยังอยู่ในแถว เปลี่ยนแค่สถานะ

    ไม่ล้างยอดเป็น 0 โดยตั้งใจ: รายงานต้องตอบได้ว่า "ยกเว้นไปเท่าไหร่" ไม่ใช่แค่ "ไม่มีค่าปรับ"
    """
    req = await _load_request(db, request_id)
    item = _load_fine_item(req, item_id)
    item.fine_status = "waived"
    item.fine_waived_by = superadmin.id
    item.fine_waived_reason = body.reason
    item.fine_waived_at = datetime.now(timezone.utc)

    await audit_service.log_action(db, superadmin, "waive_fine", "borrow_items", item.id, {
        "request_code": req.request_code, "item": item.equipment_name,
        "amount": item.fine_total, "reason": body.reason,
    })
    await _notify(db, req.student_id, "fine_waived",
                  f"ค่าปรับ {item.fine_total:,.2f} บาท ของคำขอ {req.request_code} ได้รับการยกเว้น",
                  borrow_request_id=req.id)
    await db.commit()
