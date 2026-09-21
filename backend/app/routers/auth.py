from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    StudyYearPreviewResponse,
    TokenResponse,
    VerifyEmailRequest,
)
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=201)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)) -> dict:
    await auth_service.register(db, body)
    return {"detail": "Registration successful. Please verify your email."}


@router.get("/study-year-preview", response_model=StudyYearPreviewResponse)
async def study_year_preview(
    student_id: str = Query(..., min_length=10, max_length=10),
    db: AsyncSession = Depends(get_db),
) -> StudyYearPreviewResponse:
    """พรีวิว "ปีการศึกษา … · ชั้นปีที่ …" ใต้ช่องรหัสนักศึกษาตอนสมัคร — public, คำนวณจากรหัสอย่างเดียว"""
    return await auth_service.study_year_preview(db, student_id)


@router.post("/verify-email")
async def verify_email(body: VerifyEmailRequest, db: AsyncSession = Depends(get_db)) -> dict:
    await auth_service.verify_email(db, body.token)
    return {"detail": "Email verified successfully."}


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    return await auth_service.login(db, body)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    return await auth_service.refresh_token(db, body.refresh_token)


@router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)) -> dict:
    await auth_service.forgot_password(db, body.email)
    return {"detail": "Reset link sent if email exists."}


@router.post("/reset-password")
async def reset_password(body: ResetPasswordRequest, db: AsyncSession = Depends(get_db)) -> dict:
    await auth_service.reset_password(db, body.token, body.new_password)
    return {"detail": "Password reset successful."}
