"""อัปโหลดใบยืมที่เซ็นแล้ว (feedback 7 ก.ย. 69)

ผู้ยืมต้องปริ้นใบยืมไปเซ็นแล้วเอามาแสดงตอนรับของ — เพิ่มทางเลือกให้ส่งไฟล์ที่เซ็นแล้วเข้าระบบแทน
เก็บ path เดียวต่อคำขอ (อัปโหลดใหม่ = ทับของเดิม) ตัวไฟล์อยู่ใน /uploads เหมือนรูปอื่น ๆ

Revision ID: 0033
Revises: 0032
"""
import sqlalchemy as sa
from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("borrow_requests", sa.Column("signed_form_url", sa.String(500), nullable=True))
    op.add_column("borrow_requests", sa.Column("signed_form_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("borrow_requests", "signed_form_at")
    op.drop_column("borrow_requests", "signed_form_url")
