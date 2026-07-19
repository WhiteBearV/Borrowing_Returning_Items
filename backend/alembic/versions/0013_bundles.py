"""bundles + bundle_items (ยืมเป็นชุด — advisor #9)

Revision ID: 0013
Revises: 0012

ชุดเป็นแค่ทางลัดหยิบของใส่ตะกร้า ไม่ผูกกับ borrow_requests จึงไม่แตะตารางคำขอเดิม
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bundles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "bundle_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("bundle_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("bundles.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("equipment_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("equipment.id"), nullable=False, index=True),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_table("bundle_items")
    op.drop_table("bundles")
