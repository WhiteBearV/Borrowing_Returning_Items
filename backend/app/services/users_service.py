import uuid

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import audit_service, equipment_service, settings_service
from app.models.auth_token import AuthToken
from app.models.borrow_item import BorrowItem
from app.models.borrow_request import BorrowRequest
from app.models.notification import Notification
from app.core.security import hash_password
from app.models.user import User
from app.utils.identity import is_student_identifier
from app.utils.roles import ALL_ROLES, ROLE_LABEL_TH, SUPERADMIN
from app.utils.study_year import compute_study_year, year_group_key
from app.schemas.user import PaginatedUsers, UserCreateRequest, UserUpdateRequest


async def attach_study_year(db: AsyncSession, users: list[User]) -> None:
    """เติม year_level/is_retained/remaining_study_years/study_year_label ให้ user objects ก่อนแปลงเป็น
    response — pattern เดียวกับ equipment_service.attach_book_values อ่าน setting academic_year_start
    ครั้งเดียวต่อ request แล้วคำนวณผ่าน app.utils.study_year (จุดเดียว) ให้ทุกแถว

    role != "student" ถือเป็นบุคลากรเสมอ (ส่ง enrollment_year=None เข้าสูตรแทนค่าจริงที่อาจค้างอยู่) แม้บัญชี
    จะเคยเป็นนักศึกษามาก่อนแล้วถูกเลื่อนสิทธิ์เป็น admin/superadmin ที่ /users/{id}/role — role ปัจจุบันคือ
    ความจริงเสมอ ไม่งั้นบัญชีที่เพิ่งเลื่อนสิทธิ์จะยังโชว์ "ปีที่ X" และถูกเข้าเงื่อนไขจับคู่คุณภาพผิดพลาด
    (พบตอนรีวิวรอบ 2 — MINOR 6)
    """
    if not users:
        return
    start = await settings_service.get_academic_year_start(db)
    for u in users:
        enrollment_year = u.enrollment_year if u.role == "student" else None
        info = compute_study_year(enrollment_year, u.study_years or 4, academic_year_start=start)
        u.year_level = info.year_level
        u.is_retained = info.is_retained
        u.remaining_study_years = info.remaining_study_years
        u.study_year_label = info.label


async def create_user(db: AsyncSession, admin: User, body: UserCreateRequest) -> User:
    """แอดมินสร้างบัญชีผู้ใช้ใหม่ (student หรือ admin) — verified ทันที ไม่ต้องยืนยันอีเมล"""
    if body.role not in ALL_ROLES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role.")
    exists = (await db.execute(select(User).where(User.email == body.email))).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered.")
    if body.student_id:
        dup = (await db.execute(select(User).where(User.student_id == body.student_id))).scalar_one_or_none()
        if dup:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Student ID already registered.")
    if body.username:
        # login รับได้ทั้ง student_id/username/email — username ที่เป็นเลข 10 หลักจะแยกไม่ออกจากรหัสนักศึกษา
        if is_student_identifier(body.username):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="รหัสประจำตัวของอาจารย์/เจ้าหน้าที่ต้องไม่ใช่ตัวเลข 10 หลัก (ซ้ำรูปแบบรหัสนักศึกษา)",
            )
        # เดิมไม่เช็คตรงนี้เลย ปล่อยให้ไปชน unique constraint ของ DB แล้วกลายเป็น 500 แทนที่จะเป็น 400
        dup_username = (await db.execute(select(User).where(User.username == body.username))).scalar_one_or_none()
        if dup_username:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username already registered.")
    # อาจารย์/เจ้าหน้าที่ไม่มี enrollment_year (บุคลากร) · นักศึกษาที่แอดมินเพิ่มเองก็คำนวณปีที่เข้าศึกษาจาก
    # รหัสได้เหมือนตอนสมัครเอง (จุดเดียวกับ auth_service.register / migration 0040 backfill)
    from app.utils.study_year import enrollment_year_from_student_id
    user = User(
        email=body.email,
        full_name=body.full_name,
        username=body.username,
        student_id=body.student_id,
        phone=body.phone,
        major=body.major,
        password_hash=hash_password(body.password),
        role=body.role,
        email_verified=True,
        is_active=True,
        enrollment_year=enrollment_year_from_student_id(body.student_id) if body.student_id else None,
    )
    db.add(user)
    await db.flush()  # ได้ user.id ก่อนเขียน audit
    await audit_service.log_action(db, admin, "create_user", "users", user.id, {
        "full_name": user.full_name, "email": user.email, "role": user.role,
        "identifier": user.student_id or user.username,
    })
    await db.commit()
    await db.refresh(user)
    await attach_study_year(db, [user])
    return user


async def update_profile(db: AsyncSession, user: User, body: UserUpdateRequest) -> User:
    """แก้โปรไฟล์ของตัวเอง — **แก้สาขาเองไม่ได้** (8 ก.ย. 69)

    สาขาถูกใช้กำหนดสิทธิ์/สถิติ และมีที่มาจากรายชื่อที่สาขารับรอง (เฟส 9) ปล่อยให้ผู้ใช้เปลี่ยนเองเมื่อไหร่ก็ได้
    เท่ากับข้อมูลสาขาในระบบเชื่อถือไม่ได้เลย — ต้องให้เจ้าหน้าที่แก้ให้ (หรือแก้ที่รายชื่อแล้วสมัครใหม่)
    """
    if body.full_name is not None:
        user.full_name = body.full_name
    await db.commit()
    await db.refresh(user)
    await attach_study_year(db, [user])
    return user


async def update_avatar(db: AsyncSession, user: User, file: UploadFile) -> User:
    """อัปโหลดรูปโปรไฟล์ของผู้ใช้เอง — ใช้ save_image ตัวเดียวกับรูปอุปกรณ์"""
    user.avatar_url = await equipment_service.save_image(file)
    await db.commit()
    await db.refresh(user)
    await attach_study_year(db, [user])
    return user


async def list_users(
    db: AsyncSession, page: int, page_size: int, role: str | None, major: str | None,
    approval_status: str | None = None, year_group: str | None = None,
) -> PaginatedUsers:
    """year_group: "1".."4" (ชั้นปี) / "retained" (ตกค้าง) / "staff" (บุคลากร) / "unknown" (นักศึกษาที่
    enrollment_year เป็น None — คนละกลุ่มกับ "staff" จริง ดู dashboard_service.YEAR_GROUP_LABEL) ไม่ใช่
    คอลัมน์ตรงใน DB (ชั้นปีคำนวณสดจาก enrollment_year) ต้องดึงมาทั้งหมดที่ตรงตัวกรองอื่นก่อน แล้วกรอง/
    แบ่งหน้าในหน่วยความจำ — สเกล ≤300 ผู้ใช้ (CLAUDE.md) พอทำแบบนี้ได้โดยไม่ต้องพึ่ง window function/
    คอลัมน์ generated
    """
    query = select(User)
    if role:
        query = query.where(User.role == role)
    if major:
        query = query.where(User.major == major)
    if approval_status:
        query = query.where(User.approval_status == approval_status)

    if year_group:
        start = await settings_service.get_academic_year_start(db)
        rows = list((await db.execute(query)).scalars().all())

        def matches(u: User) -> bool:
            # ใช้ year_group_key() จุดเดียวกับ dashboard_service.get_summary() (แก้ตามรีวิวรอบ 4, M-b) —
            # เดิมคำนวณ/พับกลุ่ม "นอกช่วง 1-4 ที่ยังไม่ตกค้างตามนิยาม" ไม่ตรงกับ dashboard ทำให้ user บางคน
            # (เช่น study_years ค้างข้อมูลเก่านอกช่วง 2-4) การ์ดนับว่าอยู่กลุ่ม retained แต่กรองที่นี่ไม่เจอเลย
            # สักกลุ่ม (role != student ถือเป็นบุคลากรเสมอ — กฎเดียวกับ attach_study_year แม้ enrollment_year
            # จะยังค้างจากก่อนถูกเลื่อนสิทธิ์ก็ตาม — year_group_key() รับ is_student ตรง ๆ ไม่ใช่ role)
            return year_group_key(
                u.role == "student", u.enrollment_year, u.study_years or 4, academic_year_start=start,
            ) == year_group

        rows = [u for u in rows if matches(u)]
        total = len(rows)
        items = rows[(page - 1) * page_size: (page - 1) * page_size + page_size]
        await attach_study_year(db, items)
        return PaginatedUsers(items=items, total=total, page=page, page_size=page_size)  # type: ignore

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar() or 0
    result = await db.execute(query.offset((page - 1) * page_size).limit(page_size))
    items = list(result.scalars().all())
    await attach_study_year(db, items)
    return PaginatedUsers(items=items, total=total, page=page, page_size=page_size)  # type: ignore


async def delete_user(db: AsyncSession, admin: User, user_id: uuid.UUID) -> None:
    """ลบ user ที่ปิดใช้งานแล้วออกจาก DB พร้อม cascade (notifications, borrow history)"""
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    if user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ปิดใช้งานบัญชีก่อนลบ")

    # log ก่อนลบ — อ่านค่าจากแถวที่กำลังจะหาย และการลบบัญชีลบประวัติการยืมตามไปด้วย ต้องตรวจสอบได้
    await audit_service.log_action(db, admin, "delete_user", "users", user.id, {
        "full_name": user.full_name, "email": user.email, "role": user.role,
        "identifier": user.student_id or user.username,
    })

    # ลบ child records ตาม FK ก่อน
    req_ids = (await db.execute(
        select(BorrowRequest.id).where(BorrowRequest.student_id == user_id)
    )).scalars().all()
    for req_id in req_ids:
        await db.execute(delete(Notification).where(Notification.borrow_request_id == req_id))
        await db.execute(delete(BorrowItem).where(BorrowItem.borrow_request_id == req_id))
    await db.execute(delete(BorrowRequest).where(BorrowRequest.student_id == user_id))
    await db.execute(delete(Notification).where(Notification.user_id == user_id))
    await db.execute(delete(AuthToken).where(AuthToken.user_id == user_id))
    # user นี้อาจเป็น admin ที่เคย approve/รับคืนคำขอของ student คนอื่น (ไม่ใช่แค่ของตัวเอง) — เคลียร์ FK
    # ก่อนลบ ไม่งั้นชน borrow_requests_approved_by_fkey/returned_by_fkey กลายเป็น 500 แทนที่จะลบสำเร็จ
    await db.execute(update(BorrowRequest).where(BorrowRequest.approved_by == user_id).values(approved_by=None))
    await db.execute(update(BorrowRequest).where(BorrowRequest.returned_by == user_id).values(returned_by=None))
    # ไม่ลบ audit_logs — ต้องเก็บประวัติไว้ (ห้ามลบ audit trail ด้วยการลบบัญชี)
    # FK เป็น ON DELETE SET NULL: actor_id กลายเป็น null แต่ actor_name/identifier snapshot ยังอยู่
    await db.execute(delete(User).where(User.id == user_id))
    await db.commit()


async def update_status(db: AsyncSession, admin: User, user_id: uuid.UUID, is_active: bool) -> User:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    user.is_active = is_active
    await audit_service.log_action(db, admin, "update_user_status", "users", user.id, {
        "full_name": user.full_name, "is_active": is_active,
    })
    await db.commit()
    await db.refresh(user)
    await attach_study_year(db, [user])
    return user


async def update_approval(
    db: AsyncSession, admin: User, user_id: uuid.UUID, approve: bool, note: str | None = None
) -> User:
    """รับรอง/ปฏิเสธผู้สมัครที่ระบบตรวจแล้วไม่ตรงรายชื่อของสาขา (เฟส 9)

    ปฏิเสธไม่ลบบัญชีทิ้ง — เก็บไว้พร้อมเหตุผลเพื่อให้ตอบได้ว่าใครขอเข้ามาแล้วไม่ผ่านเพราะอะไร
    (ลบจริงยังทำได้ที่เมนูลบบัญชี ซึ่งเป็นสิทธิ์ superadmin)
    """
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    if user.approval_status == "approved" and approve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="บัญชีนี้ผ่านการอนุมัติแล้ว")

    user.approval_status = "approved" if approve else "rejected"
    user.approval_note = (note or "").strip() or user.approval_note
    await audit_service.log_action(
        db, admin, "approve_registration" if approve else "reject_registration", "users", user.id, {
            "full_name": user.full_name, "identifier": user.student_id or user.username,
            "major": user.major, **({"reason": note.strip()} if note and note.strip() else {}),
        })
    db.add(Notification(
        user_id=user.id, type="registration_reviewed", channel="in_app",
        message=("บัญชีของคุณได้รับการอนุมัติแล้ว เข้าใช้งานระบบได้ทันที" if approve
                 else f"คำขอสมัครใช้งานไม่ได้รับอนุมัติ{f' — {note.strip()}' if note and note.strip() else ''}"),
    ))
    await db.commit()
    await db.refresh(user)
    await attach_study_year(db, [user])
    return user


async def update_role(
    db: AsyncSession, admin: User, user_id: uuid.UUID, role: str, reason: str | None = None
) -> User:
    """เปลี่ยนระดับสิทธิ์ของผู้ใช้ — เรียกได้จาก endpoint ที่กัน require_superadmin ไว้แล้วเท่านั้น

    กันเคสที่ผู้ดูแลระบบสูงสุดคนสุดท้ายลดสิทธิ์ตัวเองจนไม่เหลือใครแก้ระบบได้อีก (ต้องแก้ที่ DB เท่านั้น
    ซึ่งเป็นสิ่งที่เราตั้งใจเลี่ยงตั้งแต่แรก)
    """
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    if role not in ALL_ROLES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role.")
    if user.role == role:
        return user
    if user.role == SUPERADMIN and role != SUPERADMIN:
        remaining = (await db.execute(
            select(func.count(User.id)).where(User.role == SUPERADMIN, User.is_active == True)  # noqa: E712
        )).scalar() or 0
        if remaining <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"ต้องเหลือ{ROLE_LABEL_TH[SUPERADMIN]}อย่างน้อย 1 บัญชีเสมอ",
            )
    old_role = user.role
    user.role = role
    await audit_service.log_action(db, admin, "update_user_role", "users", user.id, {
        "full_name": user.full_name,
        "changes": {"role": [old_role, role]},
        "reason": reason,
    })
    await db.commit()
    await db.refresh(user)
    await attach_study_year(db, [user])
    return user


async def update_study(
    db: AsyncSession, admin: User, user_id: uuid.UUID,
    enrollment_year: int | None, study_years: int | None, is_transfer: bool | None, reason: str,
    enrollment_year_set: bool = True,
) -> User:
    """แอดมินแก้ปีที่เข้าศึกษา/จำนวนปี/เทียบโอนของผู้ใช้รายคน (เฟส 10) — เคสพิเศษที่สูตรอัตโนมัติไม่ตรง
    (ย้ายสาขา/เทียบโอนที่ยังไม่ได้ตั้งค่าตอนสมัคร/ข้อมูลรหัสผิด) บังคับเหตุผลเสมอเพราะกระทบกฎจ่ายของ
    (จับคู่อายุอุปกรณ์กับเวลาเรียนที่เหลือ) ไม่ใช่แค่ข้อมูลแสดงผล

    enrollment_year_set: แยก "ไม่ได้ส่งฟิลด์นี้มา" ออกจาก "ส่งมาเป็น null ตั้งใจล้างค่า" (router อ่านจาก
    `"enrollment_year" in body.model_fields_set`) — เดิมเช็คแค่ `enrollment_year is not None` ทำให้ส่ง null
    มาล้างค่า (เช่นแก้กลับเป็น "ไม่รู้ชั้นปี") ทำไม่ได้เลยสักครั้ง เพราะ None ถูกตีความว่า "ไม่ได้แก้" เสมอ
    (พบตอนรีวิวรอบ 2 — MINOR 8) study_years/is_transfer ไม่มีปัญหานี้เพราะไม่มีสถานะ "ล้างค่า" ที่มีความหมาย
    """
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    reason = (reason or "").strip()
    if not reason:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="กรุณาระบุเหตุผลที่แก้ไขข้อมูลชั้นปี")

    changes: dict[str, list] = {}
    if enrollment_year_set and enrollment_year != user.enrollment_year:
        changes["enrollment_year"] = [user.enrollment_year, enrollment_year]
        user.enrollment_year = enrollment_year
    if study_years is not None and study_years != user.study_years:
        changes["study_years"] = [user.study_years, study_years]
        user.study_years = study_years
    if is_transfer is not None and is_transfer != user.is_transfer:
        changes["is_transfer"] = [user.is_transfer, is_transfer]
        user.is_transfer = is_transfer

    if changes:
        await audit_service.log_action(db, admin, "update_user_study", "users", user.id, {
            "full_name": user.full_name, "identifier": user.student_id or user.username,
            "changes": changes, "reason": reason,
        })
        await db.commit()
        await db.refresh(user)
    await attach_study_year(db, [user])
    return user
