"""เหตุผลตอนผู้ยืมยกเลิกคำขอ + เวลาใช้งานล่าสุดของผู้ใช้ (feedback ผู้ใช้ 8 ก.ย. 69)

- `borrow_requests.cancel_reason` แยกจาก `rejection_reason` — คนละคนพูด (ผู้ยืมยกเลิกเอง vs แอดมินปฏิเสธ)
  ใช้ช่องเดียวกันแล้วอ่านประวัติไม่ออกว่าใครเป็นคนตัดสินใจ
- `users.last_seen_at` — หน้าตรวจสอบระบบต้องตอบได้ว่า "ตอนนี้มีคนใช้งานอยู่กี่คน"
  อัปเดตแบบ throttle (ดู dependencies.get_current_user) ไม่ใช่ทุก request เพื่อไม่ให้เขียน DB ถี่เกินจำเป็น

Revision ID: 0038
Revises: 0037
"""
import sqlalchemy as sa
from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("borrow_requests", sa.Column("cancel_reason", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "last_seen_at")
    op.drop_column("borrow_requests", "cancel_reason")
