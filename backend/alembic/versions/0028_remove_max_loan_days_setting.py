"""ลบ setting max_loan_days_durable — ไม่มีผลจริงมาตั้งแต่ migration 0017 (เลิกคำนวณ due_date จากมันแล้ว
เปลี่ยนไปใช้ requested_due_date ที่นักศึกษาเลือกเอง แคปด้วย MAX_REQUESTED_DUE_DATE_YEARS ในโค้ดแทน)
แต่แถวยังค้างอยู่ในตาราง settings ทำให้หน้า Settings ของแอดมินหลอกว่าแก้ค่านี้แล้วมีผล — เอาออกให้ตรงกับ
พฤติกรรมจริง (ยืนยันกับผู้ใช้แล้วว่าจะใช้แบบที่เป็นอยู่ตอนนี้ ไม่บังคับจำนวนวันยืมสูงสุดแยกจาก 3 ปี)

Revision ID: 0028
Revises: 0027
"""
from alembic import op
from sqlalchemy.sql import table, column
import sqlalchemy as sa

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None

settings_table = table(
    "settings",
    column("key", sa.String),
    column("value", sa.String),
    column("description", sa.String),
)


def upgrade() -> None:
    op.execute("DELETE FROM settings WHERE key = 'max_loan_days_durable'")


def downgrade() -> None:
    op.bulk_insert(settings_table, [{
        "key": "max_loan_days_durable",
        "value": "7",
        "description": "จำนวนวันยืมสูงสุดสำหรับครุภัณฑ์",
    }])
