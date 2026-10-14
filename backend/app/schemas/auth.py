from typing import Annotated, Literal

from pydantic import AfterValidator, StringConstraints, BaseModel, EmailStr, Field, field_validator

# ขั้นต่ำ 8 ตัว — ก่อนหน้านี้ไม่จำกัดเลย สมัครด้วยรหัส "1" ก็ผ่าน
# เพดาน 72 ตัวเพราะ bcrypt ตัดส่วนที่เกินทิ้งเงียบ ๆ ปล่อยไว้ผู้ใช้จะเข้าใจผิดว่ารหัสยาวกว่าที่ใช้จริง
def _fits_bcrypt(v: str) -> str:
    """bcrypt ใช้แค่ 72 ไบต์แรก — ภาษาไทย 1 ตัว = 3 ไบต์ รหัส 30 ตัวจึงถูกตรวจแค่ 24 ตัวแรก (R2-07)"""
    if len(v.encode()) > 72:
        raise ValueError("รหัสผ่านยาวเกินไป (ไม่เกิน 72 ไบต์ — ตัวอักษรไทยนับ 3 ไบต์ต่อตัว)")
    return v


Password = Annotated[str, Field(min_length=8, max_length=72), AfterValidator(_fits_bcrypt)]


# ชื่อ-นามสกุล: ตัดช่องว่างหัวท้าย ห้ามว่าง/ช่องว่างล้วน (R3-06 — ชื่อนี้ขึ้นบนใบยืมและ audit) · ไม่บังคับว่าต้องมีนามสกุล
# คนที่ไม่มีนามสกุลให้กรอก "-" ในช่องนามสกุล (ผู้ใช้กำหนด 1 ต.ค. 69 — เจอนาน ๆ ครั้ง)
FullName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
# ชื่อ/เหตุผลที่ "ต้องมีตัวอักษรจริง" ทุกจุด (หมวดหมู่ · อุปกรณ์ · ชุดอุปกรณ์ · เหตุผล) — min_length อย่างเดียวปล่อยช่องว่างล้วนผ่าน
# และ `name: str` เฉย ๆ รับ "" ได้ (QA รอบ 5, R5-03: หมวดหมู่/อุปกรณ์ชื่อว่างโผล่ในตัวเลือกทุกหน้า)
NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


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
    full_name: FullName
    # ต้องตรงกับ pattern="\d{10}" ฝั่ง frontend (RegisterPage.jsx) — เดิม backend ไม่เช็คเลย
    # เรียก API ตรง ๆ (ข้าม frontend) แล้วตั้ง student_id เป็นอะไรก็ได้ผ่านหมด
    student_id: Annotated[str, Field(pattern=r"^\d{10}$")]
    email: EmailStr
    # ^0\d{9}$ ไม่ใช่ ^\d{10}$ เฉย ๆ — เบอร์มือถือไทยขึ้นต้นด้วย 0 เสมอ ตรงกับ placeholder "08XXXXXXXX"
    phone: Annotated[str, Field(pattern=r"^0\d{9}$")]
    password: Password
    major: Literal["comp_eng", "digital_design"]  # ค่าอื่นทำให้ใบยืมไม่พิมพ์สาขา (R2-06)
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
    identifier: Annotated[str, Field(max_length=255)]  # student_id, username, or email
    # bcrypt รับได้ 72 ไบต์ — ยาวกว่านั้นเดิมหลุดเป็น 500 (R2-07) · ไม่ใช้ Password เพราะรหัสเก่าสั้นกว่า 8 อาจยังมี
    password: Annotated[str, Field(max_length=72)]


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
