import uuid
from datetime import datetime

from pydantic import BaseModel


class EligibleStudentResponse(BaseModel):
    """1 แถวในรายชื่อที่สาขารับรอง (ยังไม่ใช่บัญชีผู้ใช้)"""
    id: uuid.UUID
    student_id: str
    full_name: str
    major: str | None = None
    faculty: str | None = None
    generation: str | None = None
    advisor: str | None = None
    status_code: str | None = None
    source_file: str | None = None
    imported_at: datetime | None = None
    # สมัครใช้งานแล้วหรือยัง — เติมตอน list (ไม่ใช่คอลัมน์) ให้แอดมินเห็นว่าใครยังไม่เข้าระบบ
    has_account: bool = False

    model_config = {"from_attributes": True}


class PaginatedEligibleStudents(BaseModel):
    items: list[EligibleStudentResponse]
    total: int
    page: int
    page_size: int


class StudentImportResult(BaseModel):
    """สรุปผลนำเข้า 1 ไฟล์ — บอกให้ชัดว่าเพิ่มใหม่กี่คน อัปเดตทับกี่คน และอ่านหัวกระดาษได้ว่าอะไร"""
    added: int
    updated: int
    total: int
    faculty: str | None = None
    major: str | None = None
    major_raw: str | None = None
    generation: str | None = None
    advisor: str | None = None
    warnings: list[str] = []
