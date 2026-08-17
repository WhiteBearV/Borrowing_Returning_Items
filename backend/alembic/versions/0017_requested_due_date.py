"""เพิ่ม requested_due_date — นักศึกษาระบุวันคืนเองตอนยื่นคำขอ แทนระบบคำนวณอัตโนมัติ

ยกเลิกการคำนวณ due_date จาก setting max_loan_days_durable ตอนอนุมัติ
(ดู CLAUDE.md/feedback แอดมิน 17 ส.ค. 2026) — คอลัมน์ due_date เดิมยังอยู่
ความหมายเหมือนเดิม (วันครบกำหนดที่เป็นทางการ ตั้งตอนอนุมัติ) แค่เปลี่ยนแหล่งที่มา
เป็นคัดลอกจาก requested_due_date แทนการคำนวณ

Revision ID: 0017
Revises: 0016
"""
from alembic import op
import sqlalchemy as sa

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("borrow_requests", sa.Column("requested_due_date", sa.Date(), nullable=True))
    # backfill แถวเดิม: ใช้ due_date ถ้ามี (คำขอที่อนุมัติไปแล้ว) ไม่งั้นประมาณ +7 วันจากวันยื่น
    op.execute(
        "UPDATE borrow_requests SET requested_due_date = "
        "COALESCE(due_date, (requested_at AT TIME ZONE 'UTC')::date + INTERVAL '7 days')"
    )
    op.alter_column("borrow_requests", "requested_due_date", nullable=False)


def downgrade() -> None:
    op.drop_column("borrow_requests", "requested_due_date")
