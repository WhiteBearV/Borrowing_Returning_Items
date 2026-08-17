"""เพิ่ม setting low_stock_threshold_default — เกณฑ์สต็อกต่ำกลาง ใช้เมื่ออุปกรณ์ไม่ได้ตั้งค่าเฉพาะ

เดิม dashboard นับ "สต็อกต่ำ" เฉพาะชิ้นที่แอดมินตั้ง low_stock_threshold รายชิ้นเอาไว้เท่านั้น
ชิ้นที่ไม่ได้ตั้งจะไม่ถูกนับเลยไม่ว่าจะเหลือน้อยแค่ไหน — เพิ่มค่ากลางให้ครอบทุกชิ้น
ค่าต่อชิ้นที่ตั้งไว้แล้วยังใช้ override ได้ตามปกติ (ดู dashboard_service.get_summary)

Revision ID: 0018
Revises: 0017
"""
from alembic import op
from sqlalchemy.sql import table, column
import sqlalchemy as sa

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

settings_table = table(
    "settings",
    column("key", sa.String),
    column("value", sa.String),
    column("description", sa.String),
)


def upgrade() -> None:
    op.bulk_insert(settings_table, [{
        "key": "low_stock_threshold_default",
        "value": "5",
        "description": "เกณฑ์แจ้งเตือนสต็อกต่ำเริ่มต้น (ใช้เมื่ออุปกรณ์ไม่ได้ตั้งค่าเฉพาะ)",
    }])


def downgrade() -> None:
    op.execute("DELETE FROM settings WHERE key = 'low_stock_threshold_default'")
