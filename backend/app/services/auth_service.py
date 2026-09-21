import re
import secrets
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException, status
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import create_access_token, create_refresh_token, decode_token, hash_password, verify_password
from app.models.auth_token import AuthToken
from app.models.notification import Notification
from app.models.user import User
from app.services import audit_service, settings_service, student_import_service
from app.schemas.auth import LoginRequest, RegisterRequest, StudyYearPreviewResponse, TokenResponse
from app.utils.email import send_reset_password_email, send_verification_email
from app.utils.roles import STAFF_ROLES
from app.utils.study_year import academic_year, compute_study_year, enrollment_year_from_student_id


async def register(db: AsyncSession, body: RegisterRequest) -> None:
    """ลงทะเบียนผู้ใช้ใหม่ ตรวจสอบ email domain และส่งลิงก์ยืนยัน email"""
    domain = body.email.split("@")[-1]
    if domain not in settings.allowed_email_domains_list:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Email domain '{domain}' is not allowed.",
        )
    result = await db.execute(select(User).where(User.email == body.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered.")
    result = await db.execute(select(User).where(User.student_id == body.student_id))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Student ID already registered.")

    # เฟส 9: ตรวจกับรายชื่อที่สาขารับรอง — **ชื่อและสาขามาจากรายชื่อ ไม่ใช่จากที่ผู้สมัครพิมพ์เอง**
    # (ประเด็นที่อาจารย์ยกมา: ตอนนี้กันได้แค่โดเมนอีเมล ใครมีเมล cdti ก็เลือกสาขามั่วได้)
    # ไม่อยู่ในรายชื่อ/ชื่อไม่ตรง ไม่ปิดตาย — เข้าคิวรออนุมัติ เพราะ นศ. ใหม่/ตกหล่น/ย้ายสาขา มีจริง
    eligible = await student_import_service.find_eligible(db, body.student_id)
    approval_status, approval_note = "approved", None
    full_name, major = body.full_name, body.major
    if eligible is None:
        approval_status = "pending"
        approval_note = "ไม่พบรหัสนักศึกษานี้ในรายชื่อที่สาขารับรอง"
    elif student_import_service.normalize_name(eligible.full_name) != \
            student_import_service.normalize_name(body.full_name):
        approval_status = "pending"
        approval_note = f"ชื่อไม่ตรงกับรายชื่อของสาขา (ในรายชื่อคือ \"{eligible.full_name}\")"
    else:
        # ตรงทั้งรหัสและชื่อ → ใช้ค่าจากรายชื่อเป็นหลัก (สาขาในไฟล์อ่านไม่ได้ค่อยใช้ที่ผู้สมัครเลือก)
        full_name = eligible.full_name
        major = eligible.major or body.major

        # เฟส 10: รหัสรุ่นที่มี "ทอ" (เทียบโอน) ในรายชื่อ แต่ผู้สมัครเลือกหลักสูตรปกติ — ให้เลือกหลักสูตร
        # เทียบโอนก่อนสมัครต่อ กันบัญชีเทียบโอนถูกสร้างเป็นหลักสูตรปกติ 4 ปีผิด ๆ ซึ่งกระทบกฎจ่ายของ (จับคู่
        # อายุเครื่องกับเวลาเรียนที่เหลือ) ไปตลอดอายุบัญชี
        #
        # ต้องเช็คเฉพาะ branch นี้ (รหัส+ชื่อตรงกันแล้วเท่านั้น) — เดิมเช็คทันทีที่ `eligible is not None`
        # โดยไม่สนว่าชื่อตรงไหม ทำให้ 400 นี้กลายเป็นช่องทางเดา/ยืนยันว่า "รหัสนี้อยู่ในรายชื่อรุ่นเทียบโอน"
        # ได้แม้ผู้โจมตีไม่รู้ชื่อจริงของเจ้าของรหัสเลย (ตอบ 400 ต่างจากตอบ 200 ปกติของรหัสที่ไม่อยู่ในรายชื่อ/
        # ชื่อไม่ตรง = รั่วข้อมูลว่าใครอยู่ในรุ่นไหน) แก้ตามรีวิวรอบ 2 (MINOR 3)
        if eligible.generation and "ทอ" in eligible.generation and not body.is_transfer:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="รหัสนักศึกษานี้อยู่ในรุ่นเทียบโอน กรุณาเลือกหลักสูตร \"เทียบโอน\" และระบุจำนวนปีก่อนสมัคร",
            )
    study_years = body.study_years if body.is_transfer else 4

    user = User(
        full_name=full_name,
        student_id=body.student_id,
        email=body.email,
        phone=body.phone,
        password_hash=hash_password(body.password),
        role="student",
        major=major,
        approval_status=approval_status,
        approval_note=approval_note,
        pdpa_consent_at=datetime.now(timezone.utc),  # ผ่าน RegisterRequest._must_consent มาแล้วเสมอ (True)
        email_verified=settings.DEV_AUTO_VERIFY_EMAIL,  # True ได้เฉพาะตั้ง DEV_AUTO_VERIFY_EMAIL=true ใน .env
        # ชั้นปี (เฟส 10) — enrollment_year มาจาก 2 หลักแรกของรหัสนักศึกษาเสมอ (จุดเดียวกับ migration 0040
        # backfill และ GET /auth/study-year-preview) is_transfer/study_years มาจากที่ผู้สมัครเลือก
        enrollment_year=enrollment_year_from_student_id(body.student_id),
        study_years=study_years,
        is_transfer=body.is_transfer,
    )
    db.add(user)
    await db.flush()  # ได้ user.id ก่อน commit

    # คิวรออนุมัติต้องมีคนเห็น ไม่งั้นผู้สมัครค้างอยู่เงียบ ๆ จนกว่าจะเดินมาถามที่ห้องพัสดุ
    if approval_status == "pending":
        staff = (await db.execute(
            select(User).where(User.role.in_(STAFF_ROLES), User.is_active == True)
        )).scalars().all()
        for admin in staff:
            db.add(Notification(
                user_id=admin.id, type="registration_pending", channel="in_app",
                message=f"มีผู้สมัครรออนุมัติ: {full_name} ({body.student_id}) — {approval_note}",
            ))

    token_str = secrets.token_urlsafe(32)
    auth_token = AuthToken(
        user_id=user.id,
        token=token_str,
        token_type="email_verify",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    db.add(auth_token)
    # ผู้สมัครเป็นทั้งผู้ทำและเป้าหมายของ log นี้ — ต้องตอบให้ได้ว่าบัญชีนี้เข้ามาในระบบเมื่อไหร่
    # ด้วยอีเมล/สาขาอะไร เพราะการปลอมแปลงการสมัครคือประเด็นที่อาจารย์ยกมาโดยตรง
    await audit_service.log_action(db, user, "register", "users", user.id, {
        "full_name": user.full_name, "email": user.email,
        "identifier": user.student_id, "major": user.major,
        "approval_status": approval_status,
        **({"reason": approval_note} if approval_note else {}),
    })
    await db.commit()

    await send_verification_email(body.email, token_str)


async def verify_email(db: AsyncSession, token: str) -> None:
    """ยืนยัน email จาก token ที่ส่งไปทางอีเมล"""
    result = await db.execute(
        select(AuthToken).where(AuthToken.token == token, AuthToken.token_type == "email_verify")
    )
    auth_token = result.scalar_one_or_none()
    if not auth_token:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid token.")
    if auth_token.used_at:
        return  # ponytail: token นี้ยืนยันไปแล้ว (กดซ้ำจากอีกอุปกรณ์/แท็บ) ถือเป็นสำเร็จซ้ำได้ ไม่ต้อง error หลอกผู้ใช้ว่ายืนยันไม่ผ่าน
    if auth_token.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Token expired. Please request a new verification email.")

    user_result = await db.execute(select(User).where(User.id == auth_token.user_id))
    user = user_result.scalar_one()
    user.email_verified = True
    auth_token.used_at = datetime.now(timezone.utc)
    await audit_service.log_action(db, user, "verify_email", "users", user.id,
                                   {"email": user.email})
    await db.commit()


async def login(db: AsyncSession, body: LoginRequest) -> TokenResponse:
    """ตรวจสอบ credentials และคืน JWT access + refresh token — รองรับ student_id, username, หรือ email"""
    from sqlalchemy import or_
    result = await db.execute(
        select(User).where(
            or_(
                User.student_id == body.identifier,
                User.username == body.identifier,
                User.email == body.identifier,
            )
        )
    )
    user = result.scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials.")
    if not user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email not verified. Please check your inbox.",
        )
    if user.approval_status == "pending":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="บัญชีนี้รอเจ้าหน้าที่อนุมัติ (ไม่พบชื่อ/รหัสในรายชื่อที่สาขารับรอง) กรุณาติดต่อห้องพัสดุ")
    if user.approval_status == "rejected":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="คำขอสมัครใช้งานไม่ได้รับอนุมัติ กรุณาติดต่อเจ้าหน้าที่")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled.")

    access = create_access_token(str(user.id), extra={"role": user.role})
    refresh = create_refresh_token(str(user.id))
    return TokenResponse(access_token=access, refresh_token=refresh)


async def refresh_token(db: AsyncSession, token: str) -> TokenResponse:
    """แลก refresh token เป็น access token ใหม่"""
    try:
        payload = decode_token(token)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token.")
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type.")

    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or disabled.")

    access = create_access_token(str(user.id), extra={"role": user.role})
    return TokenResponse(access_token=access, refresh_token=token)  # refresh token เดิมยังใช้ได้จนหมดอายุ


async def forgot_password(db: AsyncSession, email: str) -> None:
    """ส่งลิงก์ reset password ทาง email — ถ้า email ไม่มีในระบบก็ไม่บอก (ป้องกัน user enumeration)"""
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        return  # ponytail: silent return ป้องกัน user enumeration

    token_str = secrets.token_urlsafe(32)
    auth_token = AuthToken(
        user_id=user.id,
        token=token_str,
        token_type="password_reset",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db.add(auth_token)
    await db.commit()
    await send_reset_password_email(email, token_str)


async def reset_password(db: AsyncSession, token: str, new_password: str) -> None:
    """ตั้งรหัสผ่านใหม่โดยใช้ token จากอีเมล"""
    result = await db.execute(
        select(AuthToken).where(AuthToken.token == token, AuthToken.token_type == "password_reset")
    )
    auth_token = result.scalar_one_or_none()
    if not auth_token or auth_token.used_at or auth_token.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token.")

    user_result = await db.execute(select(User).where(User.id == auth_token.user_id))
    user = user_result.scalar_one()
    user.password_hash = hash_password(new_password)
    auth_token.used_at = datetime.now(timezone.utc)
    await db.commit()


async def study_year_preview(db: AsyncSession, student_id: str) -> StudyYearPreviewResponse:
    """พรีวิวปีการศึกษา/ชั้นปีจากรหัสนักศึกษาอย่างเดียว — endpoint สาธารณะ (ไม่ต้องล็อกอิน)

    คำนวณจาก 2 หลักแรกของรหัสอย่างเดียว **ไม่ค้นรายชื่อที่สาขารับรอง** เพราะ endpoint นี้เปิดสาธารณะ —
    ถ้าค้นรายชื่อจะกลายเป็นช่องทางเช็คว่า "รหัสนี้มีอยู่ในรายชื่อไหม" ซึ่งเป็นข้อมูลส่วนบุคคล
    (ดู RegisterRequest.is_transfer — เหตุผลเดียวกับที่ให้ผู้สมัครเลือกหลักสูตรเองแทนที่จะเดาให้)
    ใช้ study_years=4 (ค่ากลาง) เพราะยังไม่รู้ว่าเป็นเทียบโอนไหมตอนนี้
    """
    if not student_id or not re.fullmatch(r"\d{10}", student_id.strip()):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="รหัสนักศึกษาต้องเป็นตัวเลข 10 หลัก")
    enrollment_year = enrollment_year_from_student_id(student_id.strip())
    start = await settings_service.get_academic_year_start(db)
    info = compute_study_year(enrollment_year, 4, academic_year_start=start)
    return StudyYearPreviewResponse(
        enrollment_year=enrollment_year,
        academic_year=academic_year(date.today(), start),
        year_level=info.year_level,
        label=info.label,
    )
