from typing import Annotated

from pydantic import BaseModel, EmailStr, Field

# ขั้นต่ำ 8 ตัว — ก่อนหน้านี้ไม่จำกัดเลย สมัครด้วยรหัส "1" ก็ผ่าน
# เพดาน 72 ตัวเพราะ bcrypt ตัดส่วนที่เกินทิ้งเงียบ ๆ ปล่อยไว้ผู้ใช้จะเข้าใจผิดว่ารหัสยาวกว่าที่ใช้จริง
Password = Annotated[str, Field(min_length=8, max_length=72)]


class RegisterRequest(BaseModel):
    full_name: str
    # ต้องตรงกับ pattern="\d{10}" ฝั่ง frontend (RegisterPage.jsx) — เดิม backend ไม่เช็คเลย
    # เรียก API ตรง ๆ (ข้าม frontend) แล้วตั้ง student_id เป็นอะไรก็ได้ผ่านหมด
    student_id: Annotated[str, Field(pattern=r"^\d{10}$")]
    email: EmailStr
    password: Password
    major: str  # comp_eng / digital_design


class LoginRequest(BaseModel):
    identifier: str  # student_id, username, or email
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: Password


class VerifyEmailRequest(BaseModel):
    token: str
