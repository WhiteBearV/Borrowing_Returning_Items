"""แคชเวกเตอร์ของรูป/ชื่ออุปกรณ์ สำหรับค้นหาด้วยรูป (25 พ.ย. 69)

คีย์ = hash ของเนื้อหา (url รูป หรือข้อความชื่อ) + ชื่อโมเดล — ไม่ผูกกับแถว equipment
แก้ชื่อ/เปลี่ยนรูป = hash ใหม่ → เติมแถวใหม่เอง ไม่ต้องคอย invalidate · แถวที่ไม่มีใครอ้างแล้ว job ทุกคืนลบทิ้ง
เปลี่ยนโมเดล = คนละคีย์ สร้างใหม่ทั้งชุดโดยไม่ทับของเดิม
"""
from datetime import datetime

from sqlalchemy import REAL, DateTime, String, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Embedding(Base):
    __tablename__ = "embeddings"

    kind: Mapped[str] = mapped_column(String(10), primary_key=True)  # image | text
    source_hash: Mapped[str] = mapped_column(String(64), primary_key=True)  # sha256 ของ url/ข้อความ
    model: Mapped[str] = mapped_column(String(100), primary_key=True)
    vector: Mapped[list[float]] = mapped_column(ARRAY(REAL), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
