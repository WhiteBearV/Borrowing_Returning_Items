import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.auth import Password, _strip_student_id


class UserResponse(BaseModel):
    id: uuid.UUID
    student_id: str | None
    full_name: str
    email: EmailStr
    role: str
    major: str | None
    avatar_url: str | None = None
    email_verified: bool
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class UserCreateRequest(BaseModel):
    email: EmailStr
    full_name: str
    password: Password
    role: str = "student"  # student / admin
    username: str | None = None
    # เดิมไม่มี pattern เลย ต่างจาก RegisterRequest.student_id — แอดมินเพิ่มผู้ใช้ผ่านฟอร์มนี้ได้
    # โดยตั้ง student_id เป็นอะไรก็ได้ ทำให้ข้อมูลไม่ตรงรูปแบบ \d{10} หลุดเข้าระบบ
    student_id: Annotated[str | None, Field(pattern=r"^\d{10}$")] = None
    major: str | None = None

    _normalize_student_id = field_validator("student_id", mode="before")(_strip_student_id)


class UserUpdateRequest(BaseModel):
    full_name: str | None = None
    major: str | None = None


class UserStatusUpdateRequest(BaseModel):
    is_active: bool


class PaginatedUsers(BaseModel):
    items: list[UserResponse]
    total: int
    page: int
    page_size: int
