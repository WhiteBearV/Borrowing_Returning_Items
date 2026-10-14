"""รอบตรวจเช็คอุปกรณ์ (setting quality_inspect_interval_months — 24 ก.ย. 69)

job รายวันทวงเจ้าหน้าที่ (สัปดาห์ละครั้งอย่างมาก) เมื่อหน่วยที่เปิดติดตามคุณภาพประเมินล่าสุดนานเกินรอบนี้
หรือคุณภาพต่ำกว่าเกณฑ์ · 0 = ไม่ใช้รอบตรวจ (ยังทวงเรื่องคุณภาพต่ำ/ยังไม่ประเมินตามเดิม) · ผู้ดูแลคลังแก้ได้

Revision ID: 0043
Revises: 0042
"""
import sqlalchemy as sa
from alembic import op

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(
        "INSERT INTO settings (key, value, description) VALUES (:k, :v, :d) ON CONFLICT (key) DO NOTHING"
    ).bindparams(k="quality_inspect_interval_months", v="6",
                 d="รอบตรวจเช็คสภาพอุปกรณ์ที่เปิดติดตามคุณภาพ (เดือน) — เลยรอบแล้วระบบแจ้งเจ้าหน้าที่ · 0 = ไม่ใช้รอบตรวจ"))


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM settings WHERE key = 'quality_inspect_interval_months'"))
