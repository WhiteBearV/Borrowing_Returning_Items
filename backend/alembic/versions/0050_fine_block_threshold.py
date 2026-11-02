"""ระงับการยืมเมื่อค่าปรับค้างชำระถึงเกณฑ์ (2 พ.ย. 69)

ค่าเริ่มต้น 200 บาท (ผู้ใช้กำหนด) · 0 = ไม่ระงับ · superadmin เท่านั้น (ไม่อยู่ใน ADMIN_EDITABLE_KEYS)

Revision ID: 0050
Revises: 0049
"""
import sqlalchemy as sa
from alembic import op

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(
        "INSERT INTO settings (key, value, description) VALUES (:k, :v, :d) ON CONFLICT (key) DO NOTHING"
    ).bindparams(k="fine_block_threshold", v="200",
                 d="ระงับการยืมเมื่อค่าปรับค้างชำระรวมถึงยอดนี้ (บาท) จนกว่าจะชำระหรือได้รับการยกเว้น · 0 = ไม่ระงับ"))


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM settings WHERE key = 'fine_block_threshold'"))
