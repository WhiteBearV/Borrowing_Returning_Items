"""ตรวจครุภัณฑ์รายห้องด้วย QR (16 พ.ย. 69)

Revision ID: 0052
Revises: 0051
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stocktake_rounds",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("location", sa.String(255), nullable=False),
        sa.Column("started_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
    )
    op.create_index("ix_stocktake_rounds_location", "stocktake_rounds", ["location"])
    op.create_table(
        "stocktake_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("round_id", UUID(as_uuid=True), sa.ForeignKey("stocktake_rounds.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("equipment_id", UUID(as_uuid=True), sa.ForeignKey("equipment.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("equipment_code", sa.String(50), nullable=False),
        sa.Column("equipment_name", sa.String(255), nullable=False),
        sa.Column("asset_number", sa.String(50), nullable=True),
        sa.Column("result", sa.String(20), nullable=False),
        sa.Column("from_location", sa.String(255), nullable=True),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scanned_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.UniqueConstraint("round_id", "equipment_id", name="uq_stocktake_item_round_equipment"),
    )
    op.create_index("ix_stocktake_items_round_id", "stocktake_items", ["round_id"])


def downgrade() -> None:
    op.drop_table("stocktake_items")
    op.drop_table("stocktake_rounds")
