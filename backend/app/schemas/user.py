import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr


class UserResponse(BaseModel):
    id: uuid.UUID
    student_id: str | None
    full_name: str
    email: EmailStr
    role: str
    major: str | None
    email_verified: bool
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class UserCreateRequest(BaseModel):
    email: EmailStr
    full_name: str
    password: str
    role: str = "student"  # student / admin
    username: str | None = None
    student_id: str | None = None
    major: str | None = None


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
