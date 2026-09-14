import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)
    username: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="student")  # student / admin
    major: Mapped[str | None] = mapped_column(String(50), nullable=True)  # comp_eng / digital_design
    # ไม่บังคับระดับ DB (nullable) — บัญชีที่แอดมินสร้างเอง (UsersPage) ไม่ผ่านฟอร์มสมัครนี้ ไม่มีเบอร์ก็ได้
    # บังคับกรอกเฉพาะระดับ schema ของ self-registration endpoint เท่านั้น (ดู schemas/auth.py RegisterRequest)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # เวลาที่ยอมรับ PDPA ตอนสมัคร — nullable เพราะบัญชีที่แอดมินสร้างไม่ผ่านฟอร์มนี้ ไม่มีค่าได้เช่นกัน
    pdpa_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)  # รูปโปรไฟล์ (/uploads/...)
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # approved / pending / rejected — คิวอนุมัติผู้สมัคร (เฟส 9) แยกจาก is_active คนละความหมาย:
    # is_active=False = แอดมินปิดบัญชีที่เคยใช้ได้ · pending = สมัครมาแต่ไม่อยู่ในรายชื่อของสาขา ยังไม่เคยใช้ได้เลย
    approval_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="approved", server_default="approved")
    approval_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # เวลาที่เรียก API ล่าสุด — ใช้ตอบ "ตอนนี้มีคนใช้งานอยู่กี่คน" ในหน้าตรวจสอบระบบ
    # อัปเดตแบบ throttle ใน dependencies.get_current_user (ไม่ใช่ทุก request) กันเขียน DB ถี่เกินจำเป็น
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    line_user_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    borrow_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")  # เลขรันคำขอยืมต่อผู้ใช้
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # relationships
    borrow_requests_as_student = relationship(
        "BorrowRequest", foreign_keys="BorrowRequest.student_id", back_populates="student"
    )
    borrow_requests_as_approver = relationship(
        "BorrowRequest", foreign_keys="BorrowRequest.approved_by", back_populates="approver"
    )
    auth_tokens = relationship("AuthToken", back_populates="user", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="user")
    audit_logs = relationship("AuditLog", back_populates="actor")

    __table_args__ = (Index("ix_users_role", "role"),)
