"""ตรวจครุภัณฑ์: เก็บตำแหน่งในห้องเดิมตอนสแกนย้ายห้อง — ยกเลิกการสแกนแล้วคืนได้ครบทั้งห้อง+ตู้ (23 พ.ย. 69)

Revision ID: 0055
Revises: 0054
"""
import sqlalchemy as sa
from alembic import op

revision = "0055"
down_revision = "0054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("stocktake_items", sa.Column("from_location_detail", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("stocktake_items", "from_location_detail")
