from typing import Annotated

from pydantic import BaseModel, EmailStr, Field, field_validator

# ขั้นต่ำ 8 ตัว — ก่อนหน้านี้ไม่จำกัดเลย สมัครด้วยรหัส "1" ก็ผ่าน
# เพดาน 72 ตัวเพราะ bcrypt ตัดส่วนที่เกินทิ้งเงียบ ๆ ปล่อยไว้ผู้ใช้จะเข้าใจผิดว่ารหัสยาวกว่าที่ใช้จริง
Password = Annotated[str, Field(min_length=8, max_length=72)]


def _strip_student_id(v: str | None) -> str | None:
    """ตัดช่องว่างหน้า-หลังก่อนตรวจ pattern \\d{10}

    ผู้ใช้บางคน copy-paste หรือมือถือ autofill มาพร้อม space ต่อท้ายโดยไม่รู้ตัว
    ถ้าไม่ strip ก่อน pattern จะ fail เงียบ ๆ กลายเป็น 422 ที่ผู้ใช้งง เพราะรหัสที่กรอกดูถูกต้องทุกตัว
    ใช้ร่วมกันทั้ง RegisterRequest (สมัครเอง) และ UserCreateRequest (แอดมินเพิ่มผู้ใช้ ดู schemas/user.py)
    """
    if not isinstance(v, str):
        return v  # ปล่อยให้ pydantic ตัดสินเอง (int/list/bool → error ตามเดิม)
    v = v.strip()
    return v or None  # เว้นว่าง/เว้นวรรคล้วน → normalize เป็น None เหมือน _blank_sn_to_none (schemas/equipment.py)


class RegisterRequest(BaseModel):
    full_name: str
    # ต้องตรงกับ pattern="\d{10}" ฝั่ง frontend (RegisterPage.jsx) — เดิม backend ไม่เช็คเลย
    # เรียก API ตรง ๆ (ข้าม frontend) แล้วตั้ง student_id เป็นอะไรก็ได้ผ่านหมด
    student_id: Annotated[str, Field(pattern=r"^\d{10}$")]
    email: EmailStr
    password: Password
    major: str  # comp_eng / digital_design

    _normalize_student_id = field_validator("student_id", mode="before")(_strip_student_id)


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
