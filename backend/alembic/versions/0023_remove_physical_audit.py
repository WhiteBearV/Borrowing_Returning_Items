"""ลบระบบตรวจนับอุปกรณ์ทางกายภาพ — ผู้ใช้ยืนยันว่าไม่ได้ใช้ฟีเจอร์นี้เลย ต้องการเอาออกทั้งหมด

ลบคอลัมน์ equipment.last_audited_at + setting audit_interval_days ที่เพิ่มไว้ใน 0021 — เขียน migration
ใหม่แทนการแก้ 0021 เดิม เพราะ 0021 ไม่ใช่ head แล้ว (0022 depend อยู่) แก้ migration เก่าจะพัง revision
chain ของ DB ที่ apply ไปแล้ว (ตรงกับ pattern ที่ 0022 เคยทำตอนแก้ค่า max_renew_days)

audit log เก่าที่เคยเป็น action="physical_audit" ไม่ถูกแตะ (เก็บไว้ตาม CLAUDE.md — audit log ห้ามลบ/แก้)
ฝั่ง frontend ยังคง label ภาษาไทยของ action นี้ไว้ให้อ่านได้ตลอดไป

Revision ID: 0023
Revises: 0022
"""
from alembic import op
from sqlalchemy.sql import table, column
import sqlalchemy as sa

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

settings_table = table(
    "settings",
    column("key", sa.String),
    column("value", sa.String),
    column("description", sa.String),
)


def upgrade() -> None:
    op.drop_column("equipment", "last_audited_at")
    op.execute("DELETE FROM settings WHERE key = 'audit_interval_days'")


def downgrade() -> None:
    op.add_column("equipment", sa.Column("last_audited_at", sa.DateTime(timezone=True), nullable=True))
    op.bulk_insert(settings_table, [{
        "key": "audit_interval_days",
        "value": "180",
        "description": "ความถี่ตรวจนับอุปกรณ์ทางกายภาพ (วัน) — ถ้าไม่ตรวจนานเกินนี้ ถือว่าครบกำหนดตรวจใหม่",
    }])
