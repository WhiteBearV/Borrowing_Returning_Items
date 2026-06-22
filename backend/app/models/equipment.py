import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Equipment(Base):
    __tablename__ = "equipment"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment_categories.id"), nullable=False, index=True
    )
    item_type: Mapped[str] = mapped_column(String(20), nullable=False)  # durable / consumable
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)  # เฉพาะ consumable
    quantity_total: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    quantity_available: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    low_stock_threshold: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="available")
    # available / borrowed / under_repair / damaged / retired
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    category = relationship("EquipmentCategory", back_populates="equipment")
    borrow_items = relationship("BorrowItem", back_populates="equipment")

    __table_args__ = (
        Index("ix_equipment_item_type", "item_type"),
        Index("ix_equipment_status", "status"),
    )
