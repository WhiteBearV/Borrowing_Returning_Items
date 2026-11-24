"""ป้ายอัตราค่าปรับคืนเกินกำหนด (23 พ.ย. 69) — แต่ละรุ่นปรับต่างกันได้ (เครื่อง 3.8 แสนกับ breadboard ไม่ควรปรับเท่ากัน)

ผู้ดูแลสูงสุดสร้าง/แก้/ลบป้าย · เจ้าหน้าที่เลือกป้ายให้อุปกรณ์ (ทั้งรุ่น) · อัตราถูกล็อกลง `borrow_items.fine_rate_snapshot` ตอนอนุมัติ
แก้ราคาป้ายภายหลังจึงไม่กระทบของที่ยืมอยู่ · ป้ายค่าเริ่มต้น (is_default) ใช้กับอุปกรณ์รุ่นใหม่ มีได้ป้ายเดียว
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, Numeric, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class FineRate(Base):
    __tablename__ = "fine_rates"
    __table_args__ = (
        CheckConstraint("amount_per_day >= 0", name="ck_fine_rates_amount_nonneg"),
        Index("uq_fine_rates_default", "is_default", unique=True, postgresql_where=text("is_default")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    amount_per_day: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
