import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.auth import Password, _strip_student_id


class UserResponse(BaseModel):
    id: uuid.UUID
    student_id: str | None
    # รหัสประจำตัวของอาจารย์/เจ้าหน้าที่ (นักศึกษาใช้ student_id) — เดิมไม่มีในสคีมา ทำให้หน้าจัดการผู้ใช้
    # โชว์แอดมินทุกคนเป็น "—" ทั้งที่ระบบเก็บค่าไว้แล้ว
    username: str | None = None
    full_name: str
    email: EmailStr
    phone: str | None = None
    role: str
    major: str | None
    avatar_url: str | None = None
    email_verified: bool
    is_active: bool
    # คิวอนุมัติผู้สมัคร (เฟส 9) — approved / pending / rejected · note บอกว่าติดตรงไหน
    approval_status: str = "approved"
    approval_note: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class UserCreateRequest(BaseModel):
    email: EmailStr
    full_name: str
    password: Password
    role: str = "student"  # student / admin / superadmin (ดู app/utils/roles.py)
    username: str | None = None
    # เดิมไม่มี pattern เลย ต่างจาก RegisterRequest.student_id — แอดมินเพิ่มผู้ใช้ผ่านฟอร์มนี้ได้
    # โดยตั้ง student_id เป็นอะไรก็ได้ ทำให้ข้อมูลไม่ตรงรูปแบบ \d{10} หลุดเข้าระบบ
    student_id: Annotated[str | None, Field(pattern=r"^\d{10}$")] = None
    # ไม่บังคับ (ต่างจาก RegisterRequest.phone) — แอดมินสร้างบัญชีแทนคนอื่น ไม่มีเบอร์ตอนสร้างก็ได้
    phone: Annotated[str | None, Field(pattern=r"^0\d{9}$")] = None
    major: str | None = None

    _normalize_student_id = field_validator("student_id", mode="before")(_strip_student_id)
    # เว้นวรรคหัวท้ายทำให้ค้นหา/ล็อกอินไม่เจอทั้งที่ตาเห็นว่าตรง — normalize เหมือน student_id/phone
    _normalize_username = field_validator("username", mode="before")(_strip_student_id)
    _normalize_phone = field_validator("phone", mode="before")(_strip_student_id)


class UserUpdateRequest(BaseModel):
    full_name: str | None = None
    major: str | None = None


class UserStatusUpdateRequest(BaseModel):
    is_active: bool


class UserRoleUpdateRequest(BaseModel):
    """เปลี่ยนระดับสิทธิ์ผู้ใช้ — เฉพาะผู้ดูแลระบบสูงสุด (ดู app/utils/roles.py)"""
    role: str
    reason: str | None = None  # เหตุผลที่บันทึกลง audit — ใครเลื่อนสิทธิ์ให้ใครเพราะอะไร


class PaginatedUsers(BaseModel):
    items: list[UserResponse]
    total: int
    page: int
    page_size: int


class UserApprovalRequest(BaseModel):
    """อนุมัติ/ปฏิเสธผู้สมัครที่ไม่อยู่ในรายชื่อของสาขา (เฟส 9)"""
    approve: bool
    note: str | None = Field(None, max_length=500)
