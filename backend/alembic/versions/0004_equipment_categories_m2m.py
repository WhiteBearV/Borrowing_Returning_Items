"""equipment ↔ categories many-to-many

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-01
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "equipment_category_links",
        sa.Column("equipment_id", UUID(as_uuid=True),
                  sa.ForeignKey("equipment.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("category_id", UUID(as_uuid=True),
                  sa.ForeignKey("equipment_categories.id", ondelete="CASCADE"), primary_key=True),
    )
    # ย้ายข้อมูลเดิม (category_id เดี่ยว) เข้าตารางเชื่อม แล้วค่อยลบคอลัมน์
    op.execute(
        "INSERT INTO equipment_category_links (equipment_id, category_id) "
        "SELECT id, category_id FROM equipment"
    )
    op.drop_column("equipment", "category_id")


def downgrade() -> None:
    op.add_column("equipment", sa.Column("category_id", UUID(as_uuid=True),
                  sa.ForeignKey("equipment_categories.id"), nullable=True))
    # เอาหมวดแรกกลับมาเป็น category_id เดี่ยว
    op.execute(
        "UPDATE equipment e SET category_id = ("
        "SELECT category_id FROM equipment_category_links l "
        "WHERE l.equipment_id = e.id LIMIT 1)"
    )
    op.drop_table("equipment_category_links")
