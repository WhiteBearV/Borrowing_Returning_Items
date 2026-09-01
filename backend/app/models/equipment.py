import uuid
from datetime import datetime

from sqlalchemy import (
    JSON, Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, Numeric,
    String, Table, Text, func, text,
)
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
    # SN จากผู้ผลิต — คนละอย่างกับ code (เลขครุภัณฑ์/รหัสวัสดุที่ระบบออกเอง) ไม่บังคับกรอก ใช้ตรวจนับของจริง
    serial_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    item_type: Mapped[str] = mapped_column(String(20), nullable=False)  # durable / material / consumable
    # durable = ครุภัณฑ์ (ทะเบียน), material = วัสดุใช้ซ้ำ (บอร์ด/คิต), consumable = วัสดุสิ้นเปลือง (ใช้หมด)
    # material ยืมแบบจำนวน (เหมือน consumable) แต่คืนแบบ ok/damaged/lost (เหมือน durable)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)  # cover = image_urls[0] (sync อัตโนมัติ)
    image_urls: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)  # เฉพาะ consumable
    unit_value: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)  # มูลค่า/ราคาต่อหน่วย (บาท) — โชว์ในใบยืม
    quantity_total: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    quantity_available: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    low_stock_threshold: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="available")
    # available / borrowed / under_repair / damaged / retired
    # ของที่อยู่ในทะเบียนแต่ไม่ให้ยืมออกจากห้อง (โต๊ะ/ตู้/ทีวี/เครื่องประจำห้อง)
    # แยกจาก status เพราะ status ถูกเขียนทับทุกครั้งที่ import ไฟล์ทะเบียนใหม่ ฟิลด์นี้ import ไม่แตะ
    is_borrowable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
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
        # partial unique index — กัน SN ซ้ำแต่ไม่กระทบแถวที่ยังไม่กรอก (NULL หลายแถวได้ปกติ, ดู migration 0019)
        Index(
            "ix_equipment_serial_number_unique", "serial_number",
            unique=True, postgresql_where=text("serial_number IS NOT NULL"),
        ),
        # ตาข่ายชั้นสุดท้ายของสต็อก — ถ้ามีเส้นทางไหนหักสต็อกโดยลืมล็อกแถว
        # จะได้ error ทันทีแทนที่จะเป็นสต็อกติดลบเงียบ ๆ (ดู migration 0016)
        CheckConstraint(
            "quantity_available >= 0 AND quantity_available <= quantity_total",
            name="ck_equipment_quantity_available_range",
        ),
    )
