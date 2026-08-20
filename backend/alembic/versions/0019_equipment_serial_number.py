"""เพิ่มคอลัมน์ serial_number (SN จากผู้ผลิต) ให้ equipment — คนละอย่างกับ code (เลขครุภัณฑ์/รหัสวัสดุที่ระบบออกเอง)

ใช้ระบุเครื่องตอนตรวจนับอุปกรณ์จริง ไม่บังคับกรอก (ของเดิมทุกแถวยังไม่มี SN อยู่แล้ว)
unique index เป็น partial (WHERE serial_number IS NOT NULL) กัน SN ซ้ำ แต่ไม่กระทบแถวที่ยังไม่กรอก
(NULL หลายแถวได้ปกติ — ไม่งั้น unique constraint ธรรมดาจะกันแถวที่ยังไม่กรอก SN ไม่ได้เกิน 1 แถว)

Revision ID: 0019
Revises: 0018
"""
from alembic import op
import sqlalchemy as sa

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("equipment", sa.Column("serial_number", sa.String(length=255), nullable=True))
    op.create_index(
        "ix_equipment_serial_number_unique",
        "equipment",
        ["serial_number"],
        unique=True,
        postgresql_where=sa.text("serial_number IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_equipment_serial_number_unique", table_name="equipment")
    op.drop_column("equipment", "serial_number")
