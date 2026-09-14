import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # actor_id เป็น null ได้ (SET NULL เมื่อ user ถูกลบ) แต่ actor_name/identifier snapshot
    # ไว้ตั้งแต่ตอนบันทึก จึงยังรู้ว่าใครทำแม้ user จะถูกลบไปแล้ว — ประวัติลบไม่ได้
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    actor_identifier: Mapped[str | None] = mapped_column(String(255), nullable=True)  # เลขนศ./username
    # สิทธิ์ ณ ตอนที่ทำ — role ของบัญชีเปลี่ยนได้ภายหลัง ประวัติต้องบอกสิทธิ์ตอนนั้น ไม่ใช่สิทธิ์ปัจจุบัน
    # (แถวก่อน migration 0029 เป็น null — เดาย้อนหลังไม่ได้ ไม่งั้น log จะโกหก)
    actor_role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    # approve_request / reject_request / confirm_return / create_equipment / update_equipment
    target_table: Mapped[str] = mapped_column(String(100), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    actor = relationship("User", back_populates="audit_logs")
