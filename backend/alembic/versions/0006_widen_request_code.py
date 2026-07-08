"""widen borrow_requests.request_code for student-id based codes

Revision ID: 0006
Revises: 0005
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # รหัสคำขอแบบใหม่ REQ-YYYY-<student_id>-<hex6> ยาวกว่าเดิม จึงขยายจาก 30 -> 40
    op.alter_column("borrow_requests", "request_code", type_=sa.String(40))


def downgrade() -> None:
    op.alter_column("borrow_requests", "request_code", type_=sa.String(30))
