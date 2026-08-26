"""borrow_items.renew_requested* — นักศึกษาขอต่อเวลาเอง (วันที่+เหตุผล) ก่อน admin อนุมัติจริง

mirror pattern เดียวกับ 0015_return_requested.py — แค่ตั้งธง ยังไม่แตะ extended_due_date/renewed_count
จนกว่า admin จะอนุมัติ (ดู borrow_service.approve_renew_item/reject_renew_item)

max_renew_days เปลี่ยนความหมายจาก "จำนวนวันที่บวกอัตโนมัติตอนกดต่อเวลา" (พฤติกรรมเดิม, กดปุ่มเดียวต่อทันที)
เป็น "เพดานวันล่วงหน้าสูงสุดที่ขอเลื่อนกำหนดคืนได้" (นักศึกษาเลือกวันเอง แค่ต้องไม่ไกลเกินเพดานนี้)

Revision ID: 0022
Revises: 0021
"""
from alembic import op
import sqlalchemy as sa

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("borrow_items", sa.Column("renew_requested", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("borrow_items", sa.Column("renew_requested_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("borrow_items", sa.Column("renew_requested_date", sa.Date(), nullable=True))
    op.add_column("borrow_items", sa.Column("renew_reason", sa.Text(), nullable=True))
    op.add_column("borrow_items", sa.Column("renew_rejected_reason", sa.Text(), nullable=True))
    op.execute(
        "UPDATE settings SET description = "
        "'จำนวนวันสูงสุดที่นักศึกษาขอเลื่อนกำหนดคืนล่วงหน้าได้ (นับจากวันนี้)' "
        "WHERE key = 'max_renew_days'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE settings SET description = 'จำนวนวันที่เพิ่มเมื่อต่อเวลา' WHERE key = 'max_renew_days'"
    )
    op.drop_column("borrow_items", "renew_rejected_reason")
    op.drop_column("borrow_items", "renew_reason")
    op.drop_column("borrow_items", "renew_requested_date")
    op.drop_column("borrow_items", "renew_requested_at")
    op.drop_column("borrow_items", "renew_requested")
