import uuid
from datetime import date, datetime

from sqlalchemy import (
    JSON, Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Integer, Numeric,
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
    # ผู้ผลิต + รุ่น (เฟส 8) — แยกออกจาก name ตามมาตรฐานการตั้งชื่อครุภัณฑ์ (docs/naming-convention.md)
    # ชื่อ = ป้ายให้คนอ่าน ("เซ็นเซอร์อุณหภูมิและความชื้น DHT11") · รุ่น = ค่าที่เหมือนกันทุกชิ้น ("DHT11")
    # ต่างจาก serial_number (ไม่ซ้ำรายชิ้น) และ code (รหัสทะเบียนที่ระบบออกให้)
    manufacturer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model_number: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    item_type: Mapped[str] = mapped_column(String(20), nullable=False)  # durable / material / consumable
    # durable = ครุภัณฑ์ (ทะเบียน), material = วัสดุใช้ซ้ำ (บอร์ด/คิต), consumable = วัสดุสิ้นเปลือง (ใช้หมด)
    # material ยืมแบบจำนวน (เหมือน consumable) แต่คืนแบบ ok/damaged/lost (เหมือน durable)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)  # cover = image_urls[0] (sync อัตโนมัติ)
    image_urls: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)  # เฉพาะ consumable
    unit_value: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)  # มูลค่า/ราคาต่อหน่วย (บาท) — โชว์ในใบยืม
    # วันที่ได้มา/รับเข้าทะเบียน — ห้ามใช้ created_at แทนเด็ดขาด เพราะ split/restock สร้างแถวใหม่
    # ทำให้วันที่รีเซ็ต และของ 704 แถวที่ seed ครั้งแรกมี created_at เท่ากันหมด (ดู migration 0026)
    acquired_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    # อายุการใช้งาน (ปี) เฉพาะชิ้นนี้ — ว่าง = ใช้ค่ากลาง depreciation_years_default จาก settings
    useful_life_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # มูลค่าตามบัญชีที่แอดมินกรอกทับค่าคำนวณ — มีค่าเมื่อไหร่ชนะสูตรค่าเสื่อมเสมอ (ดู equipment_service.book_value)
    book_value_override: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
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
    # ค่าคุณภาพ (เฟส 10, 15 ก.ย. 69) — เปิดติดตามได้ทีละรุ่น (ครุภัณฑ์/วัสดุใช้ซ้ำเท่านั้นตามธุรกิจ แต่ไม่บังคับที่ DB)
    # quality_baseline ว่าง = "ยังไม่ประเมิน" (ห้ามใช้ 0 แทนความหมายนี้) — สูตร/การประเมินมีจุดเดียวที่
    # equipment_service.current_quality() / assess_quality() เท่านั้น (ดู CLAUDE.md)
    quality_tracked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # อายุการใช้งานที่ใช้คิดคุณภาพ — แยกจาก useful_life_years (อายุทางบัญชี) โดยตั้งใจ ว่าง = ใช้ค่ากลาง
    # quality_life_years_default จาก settings
    quality_life_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quality_baseline: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    quality_baseline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    categories = relationship(
        "EquipmentCategory", secondary=equipment_category_links, back_populates="equipment"
    )
    borrow_items = relationship("BorrowItem", back_populates="equipment")
    # ชิ้นส่วนที่ติดตั้ง/เคยติดตั้งกับหน่วยนี้ (ดู EquipmentPart) — ลบอุปกรณ์ถาวรแล้วชิ้นส่วนหายตาม (CASCADE)
    parts = relationship("EquipmentPart", back_populates="equipment", cascade="all, delete-orphan")

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
