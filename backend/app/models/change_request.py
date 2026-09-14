import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ChangeRequest(Base):
    """คำขอแก้ไขข้อมูลที่ผู้ดูแลคลังยื่นให้ผู้ดูแลระบบสูงสุด (ดู migration 0030)

    payload เป็นข้อความอธิบาย (`detail`) ไม่ใช่คำสั่งที่ระบบเอาไปรันเอง — ผู้ดูแลระบบสูงสุดอ่านแล้ว
    ไปกดทำผ่านหน้าจอปกติซึ่งมี audit log ของตัวเองอยู่แล้ว จากนั้นค่อยกลับมาปิดงาน
    """

    __tablename__ = "change_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # snapshot ชื่อผู้ยื่นไว้ในแถว — ลบบัญชีแล้ว requester_id กลาย NULL แต่ต้องยังรู้ว่าใครขอ
    requester_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    requester_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    target_table: Mapped[str] = mapped_column(String(100), nullable=False)
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    target_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    # pending / approved (ทำให้แล้ว) / rejected
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_by_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    requester = relationship("User", foreign_keys=[requester_id])
    decider = relationship("User", foreign_keys=[decided_by])

    __table_args__ = (Index("ix_change_requests_status", "status"),)
