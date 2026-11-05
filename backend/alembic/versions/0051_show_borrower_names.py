"""สวิตช์ให้ผู้ใช้ทั่วไปเห็นรายชื่อผู้ยืม (3 พ.ย. 69 — คำแนะนำเรื่องความเป็นส่วนตัว)

ค่าเริ่มต้น true = พฤติกรรมเดิม · ผู้ดูแลคลังแก้ได้ (ADMIN_EDITABLE_KEYS) · เจ้าหน้าที่เห็นชื่อเสมอ

Revision ID: 0051
Revises: 0050
"""
import sqlalchemy as sa
from alembic import op

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(
        "INSERT INTO settings (key, value, description) VALUES (:k, :v, :d) ON CONFLICT (key) DO NOTHING"
    ).bindparams(k="show_borrower_names_to_users", v="true",
                 d="ให้ผู้ใช้ทั่วไปเห็นชื่อ-รหัสของผู้ที่กำลังยืมอุปกรณ์อยู่ · ปิด = เห็นแค่ว่ามีผู้ยืมอยู่และวันคืน"))


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM settings WHERE key = 'show_borrower_names_to_users'"))
