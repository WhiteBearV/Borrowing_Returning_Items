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
    # ^0\d{9}$ ไม่ใช่ ^\d{10}$ เฉย ๆ — เบอร์มือถือไทยขึ้นต้นด้วย 0 เสมอ ตรงกับ placeholder "08XXXXXXXX"
    phone: Annotated[str, Field(pattern=r"^0\d{9}$")]
    password: Password
    major: str  # comp_eng / digital_design
    pdpa_consent: bool
    # หลักสูตร (เฟส 10, 15 ก.ย. 69) — ปกติ 4 ปี (ค่าเริ่มต้น) หรือเทียบโอน 2/3/4 ปีแล้วแต่คน แสดงให้ทุกคน
    # เลือกได้ตั้งแต่ตอนสมัคร (ไม่ใช่เฉพาะคนที่ระบบรู้ว่าเป็นรุ่นเทียบโอน) เพื่อไม่ต้องมี endpoint ที่บอกได้ว่า
    # รหัสนี้อยู่ในรายชื่อหรือไม่ (ข้อมูลส่วนบุคคล) — auth_service ตรวจกับรายชื่อจริงอีกทีตอนสมัครจริง
    is_transfer: bool = False
    # หน้าสมัครเสนอแค่ 2/3/4 (ปกติ = 4) ตามแผน — จำกัดช่วงที่ schema ด้วย ไม่ใช่แค่ frontend (เรียก API
    # ตรง ๆ ข้าม UI จะตั้งเป็นอะไรก็ได้ถ้าไม่บังคับที่นี่) แก้ตามรีวิวรอบ 3, MINOR-12
    study_years: int = Field(4, ge=2, le=4)

    # _strip_student_id เป็น helper strip-ทั่วไป (ไม่ผูกกับ student_id จริง) ใช้ซ้ำกับ phone ได้เลย
    _normalize_student_id = field_validator("student_id", mode="before")(_strip_student_id)
    _normalize_phone = field_validator("phone", mode="before")(_strip_student_id)

    @field_validator("pdpa_consent")
    @classmethod
    def _must_consent(cls, v: bool) -> bool:
        """ปฏิเสธการสมัครถ้าไม่ยอมรับ PDPA — บังคับระดับ backend ด้วย ไม่เชื่อแค่ frontend guard"""
        if not v:
            raise ValueError("ต้องยอมรับคำชี้แจงเกี่ยวกับการใช้ข้อมูลส่วนบุคคลก่อนสมัคร")
        return v


class StudyYearPreviewResponse(BaseModel):
    """พรีวิวปีการศึกษา/ชั้นปีจากรหัสนักศึกษาอย่างเดียว — โชว์ใต้ช่องรหัสนักศึกษาตอนสมัคร (public, ไม่ค้นรายชื่อ)"""
    enrollment_year: int
    academic_year: int
    year_level: int
    label: str


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
