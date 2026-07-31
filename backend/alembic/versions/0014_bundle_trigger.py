"""bundles.trigger_equipment_id — กดเพิ่มอุปกรณ์ตัวกระตุ้นแล้วขยายเป็นทั้งชุด

Revision ID: 0014
Revises: 0013

ON DELETE SET NULL — ลบอุปกรณ์แล้วชุดยังอยู่ แค่ไม่มีตัวกระตุ้น
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bundles",
        sa.Column("trigger_equipment_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_bundles_trigger_equipment", "bundles", "equipment",
        ["trigger_equipment_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_bundles_trigger_equipment_id", "bundles", ["trigger_equipment_id"])


def downgrade() -> None:
    op.drop_index("ix_bundles_trigger_equipment_id", table_name="bundles")
    op.drop_constraint("fk_bundles_trigger_equipment", "bundles", type_="foreignkey")
    op.drop_column("bundles", "trigger_equipment_id")
