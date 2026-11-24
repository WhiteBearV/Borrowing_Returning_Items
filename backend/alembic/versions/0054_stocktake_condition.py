"""ตรวจครุภัณฑ์: สภาพ + หมายเหตุรายชิ้น ตามแบบรายงานทะเบียนคุมทรัพย์สิน (23 พ.ย. 69)

condition = normal / damaged / deteriorated / lost / wrong_category (ว่าง = ยังไม่ได้ติ๊ก) · ไม่ใช่ normal ต้องมี note

Revision ID: 0054
Revises: 0053
"""
import sqlalchemy as sa
from alembic import op

revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("stocktake_items", sa.Column("condition", sa.String(20), nullable=True))
    op.add_column("stocktake_items", sa.Column("note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("stocktake_items", "note")
    op.drop_column("stocktake_items", "condition")
