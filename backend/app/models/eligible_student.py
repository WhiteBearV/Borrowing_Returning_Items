import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class EligibleStudent(Base):
    """รายชื่อนักศึกษาที่สาขารับรอง — ใช้ตรวจตอนสมัครใช้งาน (เฟส 9)

    ที่มาของข้อมูลคือไฟล์ "รายชื่อนักศึกษาในที่ปรึกษา" จากสำนักทะเบียน (1 ไฟล์ = 1 อาจารย์ที่ปรึกษา)
    จึงต้องนำเข้าซ้ำได้เรื่อย ๆ แบบอัปเดตทับรายคน (`student_id` unique) ไม่ใช่ล้างทั้งตารางแล้วใส่ใหม่
    — ไม่งั้นนำเข้าไฟล์ของอาจารย์คนที่สองจะลบรายชื่อของคนแรกทิ้ง

    แถวในตารางนี้ **ไม่ใช่บัญชีผู้ใช้** เป็นแค่ "คนนี้มีสิทธิ์สมัคร และถ้าสมัครมา ชื่อ/สาขาต้องเป็นค่านี้"
    """

    __tablename__ = "eligible_students"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id: Mapped[str] = mapped_column(String(20), nullable=False, unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    major: Mapped[str | None] = mapped_column(String(50), nullable=True)
    faculty: Mapped[str | None] = mapped_column(String(255), nullable=True)
    generation: Mapped[str | None] = mapped_column(String(100), nullable=True)
    advisor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    imported_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
