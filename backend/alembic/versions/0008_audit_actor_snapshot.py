"""preserve audit trail: snapshot actor + SET NULL on user delete

Revision ID: 0008
Revises: 0007
"""
import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # เก็บ snapshot ชื่อ/รหัสผู้ทำไว้ในตัว log เอง เพื่อไม่ให้ประวัติหายเมื่อ user ถูกลบ
    op.add_column("audit_logs", sa.Column("actor_name", sa.String(255), nullable=True))
    op.add_column("audit_logs", sa.Column("actor_identifier", sa.String(255), nullable=True))
    op.execute(
        "UPDATE audit_logs a SET actor_name = u.full_name, "
        "actor_identifier = COALESCE(u.student_id, u.username, u.email) "
        "FROM users u WHERE a.actor_id = u.id"
    )
    # ลบ user แล้วไม่ทำให้ log หาย: actor_id เป็น null ได้ + SET NULL แทนการบล็อก/ลบ
    op.alter_column("audit_logs", "actor_id", existing_type=sa.dialects.postgresql.UUID(), nullable=True)
    op.drop_constraint("audit_logs_actor_id_fkey", "audit_logs", type_="foreignkey")
    op.create_foreign_key(
        "audit_logs_actor_id_fkey", "audit_logs", "users",
        ["actor_id"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("audit_logs_actor_id_fkey", "audit_logs", type_="foreignkey")
    op.create_foreign_key("audit_logs_actor_id_fkey", "audit_logs", "users", ["actor_id"], ["id"])
    op.alter_column("audit_logs", "actor_id", existing_type=sa.dialects.postgresql.UUID(), nullable=False)
    op.drop_column("audit_logs", "actor_identifier")
    op.drop_column("audit_logs", "actor_name")
