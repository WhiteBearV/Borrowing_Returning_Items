import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, func
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
