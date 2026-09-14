import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class EquipmentPart(Base):
    """ชิ้นส่วนที่ติดตั้งเข้ากับครุภัณฑ์ตัวหนึ่ง (เช่น RAM ที่อัพเกรดจาก 8GB เป็น 16GB)

    ประเด็นจากอาจารย์: อัพเกรดของบนครุภัณฑ์เลขเดิม แต่ "อายุของเครื่องหลักกับของที่อัพเกรดต้องแยกจากกัน"
    จึงเก็บเป็นแถวของตัวเองที่มีวันที่ติดตั้ง/ราคา/อายุการใช้งานของตัวเอง — ติดตั้งหรือถอดชิ้นส่วน
    ต้องไม่แตะ equipment.acquired_at / equipment.unit_value ของเครื่องหลักเด็ดขาด

    ตั้งชื่อ unit_value / acquired_at / useful_life_years ให้ตรงกับ Equipment โดยตั้งใจ —
    equipment_service.book_value() รับ object ที่มี 3 attribute นี้แบบ duck-typing จึงคำนวณค่าเสื่อม
    ของชิ้นส่วนด้วยฟังก์ชันเดียวกับเครื่องหลักได้เลย ไม่ต้องเขียนสูตรซ้ำ

    ponytail: ไม่ผูกกับสต็อกในคลัง — ของอัพเกรดส่วนใหญ่ซื้อจากใบจัดซื้อนอกระบบ และตอนถอดออกระบบไม่มีทาง
    รู้ว่าเก็บเข้าคลัง/ทิ้ง/ใส่เครื่องอื่นต่อ ถ้าจะผูกจริงค่อยเพิ่ม source_equipment_id ทีหลัง
    """

    __tablename__ = "equipment_parts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    equipment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    serial_number: Mapped[str | None] = mapped_column(String(255), nullable=True)  # ไม่ unique — ไม่อยู่ในทะเบียน
    unit_value: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    acquired_at: Mapped[date | None] = mapped_column(Date, nullable=True)  # วันที่ติดตั้ง = วันที่เริ่มนับอายุ
    useful_life_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # ถอดออกแล้วไม่ลบแถวทิ้ง — ประวัติการอัพเกรดคือหลักฐาน (หลักการเดียวกับ audit log ที่ลบไม่ได้)
    removed_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    removed_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # ชิ้นนี้ติดตั้งมาแทนชิ้นไหน (เฟส 8) — ได้ไทม์ไลน์ "SSD 256 → 512 → 1TB" ต่อเนื่อง
    # ไม่ใช่กองชิ้นส่วนที่ไม่รู้ว่าอันไหนแทนอันไหน · ON DELETE SET NULL: ลบต้นสายแล้วสายที่เหลือต้องไม่หายตาม
    replaces_part_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment_parts.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    equipment = relationship("Equipment", back_populates="parts")

    @property
    def is_installed(self) -> bool:
        return self.removed_at is None
