"""Patch Note ที่ผู้ใช้กดรับทราบล่าสุด (23 พ.ย. 69)

จำ "อ่านแล้ว" ต่อบัญชี ไม่ใช่ต่อเบราว์เซอร์ — เปลี่ยนเครื่องแล้วไม่เด้งซ้ำ
NULL = ยังไม่เคยกดรับทราบเวอร์ชันไหนเลย

Revision ID: 0057
Revises: 0056
"""
import sqlalchemy as sa
from alembic import op

revision = "0057"
down_revision = "0056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("seen_patch", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "seen_patch")
