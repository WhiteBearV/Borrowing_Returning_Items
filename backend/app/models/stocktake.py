"""ตรวจครุภัณฑ์รายห้อง (16 พ.ย. 69 — feedback ผู้ดูแลคลัง)

1 รอบ = ตรวจ 1 ห้อง (`equipment.location`) ตอนเปิดรอบ snapshot รายการที่ทะเบียนบอกว่าอยู่ห้องนั้นเป็น `pending`
(ถูกยืมอยู่ = `on_loan`) → สแกนเจอ = `found` · สแกนของห้องอื่น = `moved_here` (ย้าย location ให้) → ปิดรอบ ที่เหลือ = `missing`
ชื่อ/รหัส snapshot ไว้ในแถว เพราะอุปกรณ์อาจถูกลบถาวรทีหลัง แต่ใบตรวจต้องยังอ่านได้
"""
import uuid
from datetime import date, datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

STOCKTAKE_RESULTS = ("pending", "found", "moved_here", "missing", "on_loan", "elsewhere")


class StocktakeRound(Base):
    __tablename__ = "stocktake_rounds"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    location: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    started_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    starter = relationship("User", lazy="selectin")
    items = relationship("StocktakeItem", back_populates="round", lazy="selectin",
                         cascade="all, delete-orphan", order_by="StocktakeItem.equipment_code")


class StocktakeItem(Base):
    __tablename__ = "stocktake_items"
    __table_args__ = (UniqueConstraint("round_id", "equipment_id", name="uq_stocktake_item_round_equipment"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    round_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stocktake_rounds.id", ondelete="CASCADE"), nullable=False, index=True)
    equipment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment.id", ondelete="SET NULL"), nullable=True)
    equipment_code: Mapped[str] = mapped_column(String(50), nullable=False)
    equipment_name: Mapped[str] = mapped_column(String(255), nullable=False)
    asset_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    asset_name: Mapped[str | None] = mapped_column(String(255), nullable=True)  # ชื่อตามบัญชี — พิมพ์ในใบตรวจ (0059)
    result: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    # moved_here = ห้องเดิมก่อนย้ายมา · elsewhere = ห้องที่ทะเบียนบอกตอนปิดรอบ (รอบอื่นสแกนเจอที่นั่น)
    from_location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # ตำแหน่งในห้องเดิมก่อนสแกนย้าย — "ยกเลิกการสแกน" คืนได้ครบทั้งห้องและตู้ (0055)
    from_location_detail: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # สภาพตามแบบรายงานทะเบียนคุมทรัพย์สิน (23 พ.ย. 69) — ว่าง = ยังไม่ได้ติ๊ก (ของที่ไม่เจอปล่อยว่าง เผื่อไปเจอที่อื่นภายหลัง)
    condition: Mapped[str | None] = mapped_column(String(20), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)  # บังคับเมื่อ condition ไม่ใช่ normal
    scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scanned_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    round = relationship("StocktakeRound", back_populates="items")
    # ตำแหน่งในห้อง (ตู้/ชั้น) อ่านสดจากอุปกรณ์ — ไว้เดินหาของ ไม่ใช่ผลการตรวจจึงไม่ snapshot
    equipment = relationship("Equipment", lazy="selectin", viewonly=True)

    @property
    def location_detail(self) -> str | None:
        return self.equipment.location_detail if self.equipment else None

    # ราคา / วันที่รับ สำหรับใบตรวจแบบรายงานทะเบียน — อ่านสดจากอุปกรณ์
    @property
    def unit_value(self) -> float | None:
        return float(self.equipment.unit_value) if self.equipment and self.equipment.unit_value is not None else None

    @property
    def acquired_at(self) -> date | None:
        return self.equipment.acquired_at if self.equipment else None
