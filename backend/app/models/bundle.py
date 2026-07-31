import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Bundle(Base):
    """ชุดอุปกรณ์ที่แอดมินตั้งไว้ล่วงหน้า (เช่น "ชุดคอมพิวเตอร์" = PC + เมาส์ + คีย์บอร์ด + จอ)

    เป็นแค่ทางลัดในการหยิบของใส่ตะกร้า — พอกดเพิ่มลงตะกร้าแล้วจะแตกเป็นรายการปกติ
    คำขอยืม/ใบยืม/การคืน จึงไม่รู้จักชุดเลย และผู้ใช้ถอดของออกจากชุดได้อิสระ
    """

    __tablename__ = "bundles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # อุปกรณ์ตัวกระตุ้น — กดเพิ่มตัวนี้ลงตะกร้าแล้วให้ขยายเป็นทั้งชุดอัตโนมัติ (เช่น คอมพิวเตอร์ตั้งโต๊ะ → พ่วงเมาส์/คีย์บอร์ด/จอ)
    trigger_equipment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    items = relationship("BundleItem", back_populates="bundle", cascade="all, delete-orphan")
    trigger_equipment = relationship("Equipment", foreign_keys=[trigger_equipment_id])

    @property
    def trigger_equipment_name(self) -> str | None:
        """ชื่อรุ่นของอุปกรณ์ตัวกระตุ้น — ใช้จับคู่ทุกยูนิตที่ชื่อเดียวกัน (เช่น คอมตั้งโต๊ะ 40 เครื่องรุ่นเดียวกัน ใช้ชุดเดียว)"""
        return self.trigger_equipment.name if self.trigger_equipment else None


class BundleItem(Base):
    __tablename__ = "bundle_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bundle_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bundles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    equipment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment.id"), nullable=False, index=True
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    bundle = relationship("Bundle", back_populates="items")
    equipment = relationship("Equipment")

    # ข้อมูลอุปกรณ์ที่หน้าเว็บต้องใช้ตอนกดเพิ่มทั้งชุดลงตะกร้า (ชื่อ/หน่วย/ของคงเหลือ)
    @property
    def equipment_name(self) -> str | None:
        return self.equipment.name if self.equipment else None

    @property
    def equipment_code(self) -> str | None:
        return self.equipment.code if self.equipment else None

    @property
    def item_type(self) -> str | None:
        return self.equipment.item_type if self.equipment else None

    @property
    def unit(self) -> str | None:
        return self.equipment.unit if self.equipment else None

    @property
    def quantity_available(self) -> int | None:
        return self.equipment.quantity_available if self.equipment else None

    @property
    def is_borrowable(self) -> bool | None:
        return self.equipment.is_borrowable if self.equipment else None
