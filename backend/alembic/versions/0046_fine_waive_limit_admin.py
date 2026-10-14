"""เพดานยอดที่ผู้ดูแลคลังยกเว้นค่าปรับเองได้ (SKGRent ข้อ 5 — 24 ก.ย. 69)

ค่าเริ่มต้น 0 = พฤติกรรมเดิม (ยกเว้นได้เฉพาะ superadmin) — superadmin ต้องตั้งเองถึงจะเปิด
ไม่อยู่ใน ADMIN_EDITABLE_KEYS (ผู้ดูแลคลังตั้งเพดานให้ตัวเองไม่ได้)

Revision ID: 0046
Revises: 0045
"""
import sqlalchemy as sa
from alembic import op

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(
        "INSERT INTO settings (key, value, description) VALUES (:k, :v, :d) ON CONFLICT (key) DO NOTHING"
    ).bindparams(k="fine_waive_limit_admin", v="0",
                 d="ผู้ดูแลคลังยกเว้นค่าปรับเองได้ถ้ายอดรวมรายการไม่เกิน (บาท) — เกินกว่านี้ต้องเป็นผู้ดูแลระบบสูงสุด · 0 = ไม่อนุญาต"))


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM settings WHERE key = 'fine_waive_limit_admin'"))
