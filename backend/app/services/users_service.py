import uuid

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import audit_service, equipment_service
from app.models.auth_token import AuthToken
from app.models.borrow_item import BorrowItem
from app.models.borrow_request import BorrowRequest
from app.models.notification import Notification
from app.core.security import hash_password
from app.models.user import User
from app.utils.identity import is_student_identifier
from app.utils.roles import ALL_ROLES, ROLE_LABEL_TH, SUPERADMIN
from app.schemas.user import PaginatedUsers, UserCreateRequest, UserUpdateRequest


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
    )
    db.add(user)
    await db.flush()  # ได้ user.id ก่อนเขียน audit
    await audit_service.log_action(db, admin, "create_user", "users", user.id, {
        "full_name": user.full_name, "email": user.email, "role": user.role,
        "identifier": user.student_id or user.username,
    })
    await db.commit()
    await db.refresh(user)
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
    return user


async def update_avatar(db: AsyncSession, user: User, file: UploadFile) -> User:
    """อัปโหลดรูปโปรไฟล์ของผู้ใช้เอง — ใช้ save_image ตัวเดียวกับรูปอุปกรณ์"""
    user.avatar_url = await equipment_service.save_image(file)
    await db.commit()
    await db.refresh(user)
    return user


async def list_users(
    db: AsyncSession, page: int, page_size: int, role: str | None, major: str | None,
    approval_status: str | None = None,
) -> PaginatedUsers:
    query = select(User)
    if role:
        query = query.where(User.role == role)
    if major:
        query = query.where(User.major == major)
    if approval_status:
        query = query.where(User.approval_status == approval_status)
    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar() or 0
    result = await db.execute(query.offset((page - 1) * page_size).limit(page_size))
    items = list(result.scalars().all())
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
    return user
