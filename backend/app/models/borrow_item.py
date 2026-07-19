import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class BorrowItem(Base):
    __tablename__ = "borrow_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    borrow_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("borrow_requests.id"), nullable=False, index=True
    )
    equipment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment.id"), nullable=False, index=True
    )
    item_type_snapshot: Mapped[str] = mapped_column(String(20), nullable=False)  # durable / consumable
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # ราคาต่อหน่วย ณ วันอนุมัติ — snapshot ไว้เพราะแอดมินแก้ราคาในคลังได้ ต้นทุนย้อนหลังต้องไม่เปลี่ยนตาม
    unit_value_snapshot: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    returned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    condition_on_return: Mapped[str | None] = mapped_column(String(20), nullable=True)  # ok / damaged / lost
    damage_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    damage_photo_urls: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    renewed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    extended_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    borrow_request = relationship("BorrowRequest", back_populates="items")
    equipment = relationship("Equipment", back_populates="borrow_items")

    @property
    def equipment_name(self) -> str | None:
        return self.equipment.name if self.equipment else None

    @property
    def equipment_code(self) -> str | None:
        return self.equipment.code if self.equipment else None

    @property
    def equipment_unit(self) -> str | None:
        return self.equipment.unit if self.equipment else None

    @property
    def equipment_value(self) -> float | None:
        """ราคาต่อหน่วยที่ใช้ในเอกสาร — ใช้ราคา ณ วันอนุมัติก่อน ถ้ายังไม่มี (คำขอเก่า/ยังไม่อนุมัติ) ค่อยดูราคาปัจจุบัน"""
        if self.unit_value_snapshot is not None:
            return float(self.unit_value_snapshot)
        return float(self.equipment.unit_value) if self.equipment and self.equipment.unit_value is not None else None
