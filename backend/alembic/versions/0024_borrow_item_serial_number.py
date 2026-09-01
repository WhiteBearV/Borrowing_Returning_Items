"""snapshot serial number อุปกรณ์ไว้ใน borrow_items — ให้ใบยืม/ใบคืนโชว์ SN ได้แม้อุปกรณ์ถูกแก้/ลบภายหลัง

แนวทางเดียวกับ 0020 (equipment_name/code/unit)

Revision ID: 0024
Revises: 0023
"""
from alembic import op
import sqlalchemy as sa

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("borrow_items", sa.Column("equipment_serial_number", sa.String(255), nullable=True))
    op.execute(
        "UPDATE borrow_items b SET equipment_serial_number = e.serial_number "
        "FROM equipment e WHERE b.equipment_id = e.id"
    )


def downgrade() -> None:
    op.drop_column("borrow_items", "equipment_serial_number")
