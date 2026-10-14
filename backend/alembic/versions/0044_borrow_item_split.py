"""คืนบางส่วน / แยกสภาพในรายการเดียว (SKGRent ข้อ 2 — 24 ก.ย. 69)

borrow_items.split_from_id: ส่วนที่รับคืนไปก่อนถูกแตกเป็นแถวใหม่ชี้กลับมาที่รายการเดิม

Revision ID: 0044
Revises: 0043
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("borrow_items", sa.Column(
        "split_from_id", UUID(as_uuid=True),
        sa.ForeignKey("borrow_items.id", ondelete="CASCADE"), nullable=True))
    op.create_index("ix_borrow_items_split_from_id", "borrow_items", ["split_from_id"])


def downgrade() -> None:
    op.drop_index("ix_borrow_items_split_from_id", table_name="borrow_items")
    op.drop_column("borrow_items", "split_from_id")
