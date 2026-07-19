"""borrow_requests.returned_by (ผู้รับคืน)

Revision ID: 0011
Revises: 0010

ใบคืนต้องระบุว่า admin คนไหนเป็นผู้รับของคืน — เดิมรู้แค่ผู้อนุมัติ (approved_by)
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("borrow_requests", sa.Column("returned_by", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_borrow_requests_returned_by", "borrow_requests", "users", ["returned_by"], ["id"]
    )


def downgrade() -> None:
    op.drop_constraint("fk_borrow_requests_returned_by", "borrow_requests", type_="foreignkey")
    op.drop_column("borrow_requests", "returned_by")
