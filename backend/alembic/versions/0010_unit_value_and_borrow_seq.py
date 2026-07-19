"""equipment.unit_value (มูลค่าต่อชิ้น) + users.borrow_seq (เลขรันคำขอต่อผู้ใช้)

Revision ID: 0010
Revises: 0009

- unit_value: มูลค่า/ราคาต่อหน่วยของอุปกรณ์ ไว้แสดงในใบยืมให้ผู้ยืมเห็นวงเงินชดใช้
- borrow_seq: ตัวนับคำขอต่อผู้ใช้ ใช้ออกเลขคำขอแบบนับต่อเนื่อง (REQ-ปี-รหัส-0001)
  กันชนด้วยการ UPDATE ... RETURNING (row lock) แทน count+1
"""
import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("equipment", sa.Column("unit_value", sa.Numeric(12, 2), nullable=True))
    op.add_column(
        "users",
        sa.Column("borrow_seq", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("users", "borrow_seq")
    op.drop_column("equipment", "unit_value")
