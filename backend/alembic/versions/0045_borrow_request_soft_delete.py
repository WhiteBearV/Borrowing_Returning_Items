"""ซ่อนประวัติการยืมแทนการลบถาวร (SKGRent ข้อ 3 — 24 ก.ย. 69)

Revision ID: 0045
Revises: 0044
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("borrow_requests", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("borrow_requests", sa.Column(
        "deleted_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True))
    op.add_column("borrow_requests", sa.Column("delete_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("borrow_requests", "delete_reason")
    op.drop_column("borrow_requests", "deleted_by")
    op.drop_column("borrow_requests", "deleted_at")
