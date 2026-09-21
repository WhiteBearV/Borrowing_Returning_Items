"""เวลาส่งแจ้งเตือนรายวัน (setting notify_time — 21 ก.ย. 69)

job "ใกล้ครบกำหนด" + "เกินกำหนด" เดิมยิงตายตัวตอนเที่ยงคืน นักศึกษาได้อีเมลทวงตอนตี 0 — ให้ superadmin
เลือกเวลาเองได้ (ไม่อยู่ใน ADMIN_EDITABLE_KEYS) แก้แล้ว scheduler เลื่อนเวลาให้ทันทีไม่ต้องรีสตาร์ต
ค่าเริ่มต้น 08:00 ต้องตรงกับ scheduler.DEFAULT_NOTIFY_TIME

Revision ID: 0041
Revises: 0040
"""
import sqlalchemy as sa
from alembic import op

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(
        "INSERT INTO settings (key, value, description) VALUES (:k, :v, :d) ON CONFLICT (key) DO NOTHING"
    ).bindparams(k="notify_time", v="08:00",
                 d="เวลาที่ระบบส่งแจ้งเตือน/อีเมลอัตโนมัติทุกวัน (ใกล้ครบกำหนด · เกินกำหนด) รูปแบบ HH:MM เวลาไทย"))


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM settings WHERE key = 'notify_time'"))
