"""เพิ่มเบอร์โทรศัพท์ + เวลายอมรับ PDPA ให้ users — สำหรับฟอร์มสมัครสมาชิกใหม่ (RegisterPage)
บังคับกรอกเฉพาะระดับ schema ของ self-registration endpoint เท่านั้น คอลัมน์ยัง nullable ที่ระดับ DB
เพราะบัญชีที่แอดมินสร้างเอง (UsersPage) ไม่ผ่านฟอร์มนี้ ไม่มีค่าได้

Revision ID: 0025
Revises: 0024
"""
from alembic import op
import sqlalchemy as sa

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("phone", sa.String(20), nullable=True))
    op.add_column("users", sa.Column("pdpa_consent_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "pdpa_consent_at")
    op.drop_column("users", "phone")
