import uuid
from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Integer, String, Table, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

# ตารางเชื่อม many-to-many — อุปกรณ์หนึ่งชิ้นอยู่ได้หลายหมวดพร้อมกัน (เช่น สายไฟ = Electronic + วัสดุ)
equipment_category_links = Table(
    "equipment_category_links",
    Base.metadata,
    Column("equipment_id", ForeignKey("equipment.id", ondelete="CASCADE"), primary_key=True),
    Column("category_id", ForeignKey("equipment_categories.id", ondelete="CASCADE"), primary_key=True),
)


class Equipment(Base):
    __tablename__ = "equipment"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    item_type: Mapped[str] = mapped_column(String(20), nullable=False)  # durable / consumable
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)  # cover = image_urls[0] (sync อัตโนมัติ)
    image_urls: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
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

    categories = relationship(
        "EquipmentCategory", secondary=equipment_category_links, back_populates="equipment"
    )
    borrow_items = relationship("BorrowItem", back_populates="equipment")

    __table_args__ = (
        Index("ix_equipment_item_type", "item_type"),
        Index("ix_equipment_status", "status"),
    )
