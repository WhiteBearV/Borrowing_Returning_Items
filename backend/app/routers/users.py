import uuid

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db, require_admin, require_superadmin
from app.models.user import User
from app.schemas.user import (
    UserApprovalRequest,
    PaginatedUsers,
    UserCreateRequest,
    UserResponse,
    UserRoleUpdateRequest,
    UserStatusUpdateRequest,
    UserUpdateRequest,
)
from app.services import users_service

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.patch("/me", response_model=UserResponse)
async def update_me(
    body: UserUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    return await users_service.update_profile(db, current_user, body)


@router.post("/me/avatar", response_model=UserResponse)
async def upload_my_avatar(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """อัปโหลด/เปลี่ยนรูปโปรไฟล์ของตัวเอง"""
    return await users_service.update_avatar(db, current_user, file)


@router.get("", response_model=PaginatedUsers)
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    role: str | None = Query(None),
    major: str | None = Query(None),
    approval_status: str | None = Query(None, pattern="^(approved|pending|rejected)$"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> PaginatedUsers:
    return await users_service.list_users(db, page, page_size, role, major, approval_status)


@router.post("", response_model=UserResponse, status_code=201)
async def create_user(
    body: UserCreateRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> User:
    """แอดมินสร้างบัญชีผู้ใช้ใหม่ (student หรือ admin)"""
    return await users_service.create_user(db, admin, body)


@router.patch("/{user_id}/status", response_model=UserResponse)
async def update_user_status(
    user_id: uuid.UUID,
    body: UserStatusUpdateRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> User:
    return await users_service.update_status(db, admin, user_id, body.is_active)


@router.patch("/{user_id}/approval", response_model=UserResponse)
async def update_user_approval(
    user_id: uuid.UUID,
    body: UserApprovalRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> User:
    """อนุมัติ/ปฏิเสธผู้สมัครที่ไม่ตรงรายชื่อของสาขา (เฟส 9) — เจ้าหน้าที่ทำได้"""
    return await users_service.update_approval(db, admin, user_id, body.approve, body.note)


@router.patch("/{user_id}/role", response_model=UserResponse)
async def update_user_role(
    user_id: uuid.UUID,
    body: UserRoleUpdateRequest,
    admin: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> User:
    """เปลี่ยนระดับสิทธิ์ผู้ใช้ — เฉพาะผู้ดูแลระบบสูงสุด"""
    return await users_service.update_role(db, admin, user_id, body.role, body.reason)


@router.delete("/{user_id}", status_code=204)
async def delete_user(
    user_id: uuid.UUID,
    admin: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> None:
    """ลบบัญชีถาวร — ลบประวัติการยืมของคนนั้นตามไปด้วย จึงจำกัดไว้ที่ผู้ดูแลระบบสูงสุด"""
    await users_service.delete_user(db, admin, user_id)
