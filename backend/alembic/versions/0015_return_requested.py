"""borrow_items.return_requested/return_requested_at — นักศึกษาแจ้งขอคืน ก่อน admin ยืนยันจริง

Revision ID: 0015
Revises: 0014
"""
import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "borrow_items",
        sa.Column("return_requested", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "borrow_items",
        sa.Column("return_requested_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("borrow_items", "return_requested_at")
    op.drop_column("borrow_items", "return_requested")
