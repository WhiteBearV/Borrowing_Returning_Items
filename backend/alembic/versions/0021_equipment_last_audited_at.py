"""เพิ่มคอลัมน์ last_audited_at ให้ equipment (ตรวจนับกายภาพ) + setting audit_interval_days

ตรวจนับล่าสุดว่าเจอของจริงตรงตำแหน่งที่บันทึกไว้ไหม — เก็บแค่ตัวชี้ล่าสุด ใช้คำนวณ "ครบกำหนดตรวจนับ"
สดตอน query (last_audited_at + audit_interval_days) ไม่ backfill next_audit_due แยก เพราะแก้ interval
ทีหลังจะได้ไม่ต้องอัปเดตทุกแถว ประวัติการตรวจนับแต่ละครั้งจริง ๆ เก็บใน audit_logs (append-only) อยู่แล้ว
ไม่สร้างตารางใหม่ซ้ำซ้อน (ดู CLAUDE.md §audit log)

ค่าเริ่มต้น audit_interval_days = 180 (ทุกเทอม) ยืนยันกับผู้ใช้แล้ว ปรับได้ทีหลังในหน้า Settings

Revision ID: 0021
Revises: 0020
"""
from alembic import op
from sqlalchemy.sql import table, column
import sqlalchemy as sa

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

settings_table = table(
    "settings",
    column("key", sa.String),
    column("value", sa.String),
    column("description", sa.String),
)


def upgrade() -> None:
    op.add_column("equipment", sa.Column("last_audited_at", sa.DateTime(timezone=True), nullable=True))
    op.bulk_insert(settings_table, [{
        "key": "audit_interval_days",
        "value": "180",
        "description": "ความถี่ตรวจนับอุปกรณ์ทางกายภาพ (วัน) — ถ้าไม่ตรวจนานเกินนี้ ถือว่าครบกำหนดตรวจใหม่",
    }])


def downgrade() -> None:
    op.execute("DELETE FROM settings WHERE key = 'audit_interval_days'")
    op.drop_column("equipment", "last_audited_at")
