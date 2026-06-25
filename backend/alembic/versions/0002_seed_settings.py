"""seed default settings

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-23
"""

from alembic import op
from sqlalchemy.sql import table, column
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

settings_table = table(
    "settings",
    column("key", sa.String),
    column("value", sa.String),
    column("description", sa.String),
)

DEFAULTS = [
    ("max_items_per_request", "5", "จำนวนรายการสูงสุดในคำขอยืมหนึ่งใบ"),
    ("max_active_requests_per_student", "2", "จำนวนคำขอที่ยังไม่คืนพร้อมกันสูงสุดต่อนักศึกษา"),
    ("max_loan_days_durable", "7", "จำนวนวันยืมสูงสุดสำหรับครุภัณฑ์"),
    ("max_renew_count", "1", "จำนวนครั้งสูงสุดที่ต่อเวลาได้ต่อรายการ"),
    ("max_renew_days", "7", "จำนวนวันที่เพิ่มเมื่อต่อเวลา"),
    ("due_soon_notify_days_before", "2", "แจ้งเตือนล่วงหน้ากี่วันก่อนครบกำหนด"),
]


def upgrade() -> None:
    op.bulk_insert(settings_table, [{"key": k, "value": v, "description": d} for k, v, d in DEFAULTS])


def downgrade() -> None:
    op.execute("DELETE FROM settings WHERE key IN (%s)" % ",".join(f"'{k}'" for k, _, _ in DEFAULTS))
