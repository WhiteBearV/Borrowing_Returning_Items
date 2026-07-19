"""borrow_items.unit_value_snapshot (ราคาต่อหน่วย ณ วันอนุมัติ)

Revision ID: 0012
Revises: 0011

ต้นทุนวัสดุสิ้นเปลืองต้องคิดจากราคา ณ ตอนเบิก ไม่ใช่ราคาปัจจุบันในคลัง
(แอดมินแก้ราคาได้ตลอด ถ้าไม่ snapshot ตัวเลขย้อนหลังจะขยับตาม)
"""
import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("borrow_items", sa.Column("unit_value_snapshot", sa.Numeric(12, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("borrow_items", "unit_value_snapshot")
