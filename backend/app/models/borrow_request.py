import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class BorrowRequest(Base):
    __tablename__ = "borrow_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)  # REQ-2026-<student_id>-<hex6>
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    purpose: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    # pending / approved / rejected / cancelled / completed
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # วันที่นักศึกษาขอคืนเอง ระบุตอนยื่นคำขอ — ไม่มีเพดานสูงสุด แอดมินใช้ดุลพินิจตอนอนุมัติ/ปฏิเสธ
    requested_due_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    is_overdue: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # ผู้รับคืน = admin ที่กดรับคืนล่าสุด (ใบคืนต้องระบุว่าใครรับของมา)
    # ponytail: เก็บระดับคำขอ ถ้าต้องรู้ว่าแต่ละชิ้นใครรับ ค่อยย้ายไป borrow_items.received_by
    returned_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    pdf_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    student = relationship("User", foreign_keys=[student_id], back_populates="borrow_requests_as_student")
    approver = relationship("User", foreign_keys=[approved_by], back_populates="borrow_requests_as_approver")
    receiver = relationship("User", foreign_keys=[returned_by])
    items = relationship("BorrowItem", back_populates="borrow_request", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="borrow_request")

    __table_args__ = (Index("ix_borrow_requests_status", "status"),)

    @property
    def student_name(self) -> str | None:
        return self.student.full_name if self.student else None

    @property
    def student_email(self) -> str | None:
        return self.student.email if self.student else None

    @property
    def student_number(self) -> str | None:
        return self.student.student_id if self.student else None

    @property
    def approver_name(self) -> str | None:
        return self.approver.full_name if self.approver else None

    @property
    def receiver_name(self) -> str | None:
        return self.receiver.full_name if self.receiver else None
