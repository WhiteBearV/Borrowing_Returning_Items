"""เปลี่ยนตัวระหว่างยืม (SKGRent ข้อ 4 — 24 ก.ย. 69)

borrow_items.swapped_from_id: แถวของหน่วยที่มาแทน → แถวของหน่วยเดิม
borrow_items.started_at: วันที่ของแถวนี้ออกจากคลังจริง (ว่าง = approved_at ของคำขอ เหมือนเดิมทุกแถว)

Revision ID: 0047
Revises: 0046
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("borrow_items", sa.Column(
        "swapped_from_id", UUID(as_uuid=True),
        sa.ForeignKey("borrow_items.id", ondelete="CASCADE"), nullable=True))
    op.add_column("borrow_items", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("borrow_items", "started_at")
    op.drop_column("borrow_items", "swapped_from_id")
