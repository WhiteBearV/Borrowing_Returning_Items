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

    # ชั้นปี (เฟส 10) — enrollment_year/study_years/is_transfer เป็นคอลัมน์จริง ส่วน year_level/is_retained/
    # remaining_study_years/study_year_label เป็นค่าคำนวณสด (users_service.attach_study_year เติมให้ก่อน
    # แปลงเป็น response — pattern เดียวกับ equipment_service.attach_book_values) ห้ามคำนวณซ้ำฝั่ง frontend
    enrollment_year: int | None = None
    study_years: int = 4
    is_transfer: bool = False
    year_level: int | None = None
    is_retained: bool = False
    remaining_study_years: int | None = None
    study_year_label: str = "บุคลากร"

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


class UserStudyUpdateRequest(BaseModel):
    """แอดมินแก้ปีที่เข้าศึกษา/จำนวนปี/เทียบโอนรายคน (เฟส 10) — เคสพิเศษที่สูตรอัตโนมัติไม่ตรง
    (ย้ายสาขา/รหัสไม่ตรงรูปแบบ/เทียบโอนที่ยังไม่ได้ตั้งค่า) บังคับเหตุผลเสมอเพราะแก้ข้อมูลที่กระทบกฎจ่ายของ
    """
    enrollment_year: int | None = Field(None, ge=2500, le=2700)
    # ช่วงเดียวกับตอนสมัคร (RegisterRequest.study_years — 2/3/4 ตามแผน) — ไม่เปิดกว้างกว่านั้นให้แอดมิน
    # เพราะแผนไม่มีเหตุผลทางธุรกิจสำหรับค่านอกช่วงนี้ (แก้ตามรีวิวรอบ 3, MINOR-12) ข้อมูลเก่า/นำเข้าที่ยัง
    # ค้างค่านอกช่วงนี้อยู่ (ก่อนแก้) ยังอ่าน/แสดงผลได้ปกติ — dashboard_service กันไม่ให้ตกหล่นไว้แล้ว (MINOR-2)
    # แค่แก้ผ่านฟอร์มนี้ซ้ำเป็นค่านอกช่วงไม่ได้อีกต่อไป
    study_years: int | None = Field(None, ge=2, le=4)
    is_transfer: bool | None = None
    reason: str = Field(..., min_length=1)

    # min_length=1 เฉยๆ ยอมรับ " " (ช่องว่างล้วน) ผ่านได้ — บังคับ strip แล้วต้องไม่ว่างจริง (พบตอนรีวิวรอบ 2)
    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("กรุณาระบุเหตุผลที่แก้ไขข้อมูลชั้นปี")
        return v


class PaginatedUsers(BaseModel):
    items: list[UserResponse]
    total: int
    page: int
    page_size: int


class UserApprovalRequest(BaseModel):
    """อนุมัติ/ปฏิเสธผู้สมัครที่ไม่อยู่ในรายชื่อของสาขา (เฟส 9)"""
    approve: bool
    note: str | None = Field(None, max_length=500)
