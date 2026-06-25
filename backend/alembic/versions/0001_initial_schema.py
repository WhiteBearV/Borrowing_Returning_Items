
"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-06-23
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("student_id", sa.String(20), unique=True, nullable=True),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), unique=True, nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="student"),
        sa.Column("major", sa.String(50), nullable=True),
        sa.Column("email_verified", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("line_user_id", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_users_email", "users", ["email"])
    op.create_index("ix_users_role", "users", ["role"])

    op.create_table(
        "auth_tokens",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token", sa.String(255), unique=True, nullable=False),
        sa.Column("token_type", sa.String(30), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_auth_tokens_user_id", "auth_tokens", ["user_id"])
    op.create_index("ix_auth_tokens_token", "auth_tokens", ["token"])

    op.create_table(
        "equipment_categories",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), unique=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "equipment",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(50), unique=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("category_id", UUID(as_uuid=True), sa.ForeignKey("equipment_categories.id"), nullable=False),
        sa.Column("item_type", sa.String(20), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("image_url", sa.String(500), nullable=True),
        sa.Column("location", sa.String(255), nullable=True),
        sa.Column("unit", sa.String(50), nullable=True),
        sa.Column("quantity_total", sa.Integer, nullable=False, server_default="1"),
        sa.Column("quantity_available", sa.Integer, nullable=False, server_default="1"),
        sa.Column("low_stock_threshold", sa.Integer, nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="available"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_equipment_code", "equipment", ["code"])
    op.create_index("ix_equipment_category_id", "equipment", ["category_id"])
    op.create_index("ix_equipment_item_type", "equipment", ["item_type"])
    op.create_index("ix_equipment_status", "equipment", ["status"])

    op.create_table(
        "borrow_requests",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("request_code", sa.String(30), unique=True, nullable=False),
        sa.Column("student_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("purpose", sa.Text, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("approved_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text, nullable=True),
        sa.Column("due_date", sa.Date, nullable=True),
        sa.Column("is_overdue", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("returned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pdf_url", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_borrow_requests_student_id", "borrow_requests", ["student_id"])
    op.create_index("ix_borrow_requests_status", "borrow_requests", ["status"])
    op.create_index("ix_borrow_requests_due_date", "borrow_requests", ["due_date"])

    op.create_table(
        "borrow_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("borrow_request_id", UUID(as_uuid=True), sa.ForeignKey("borrow_requests.id"), nullable=False),
        sa.Column("equipment_id", UUID(as_uuid=True), sa.ForeignKey("equipment.id"), nullable=False),
        sa.Column("item_type_snapshot", sa.String(20), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False, server_default="1"),
        sa.Column("returned", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("returned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("condition_on_return", sa.String(20), nullable=True),
        sa.Column("damage_note", sa.Text, nullable=True),
        sa.Column("damage_photo_urls", JSONB, nullable=True),
        sa.Column("renewed_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("extended_due_date", sa.Date, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_borrow_items_borrow_request_id", "borrow_items", ["borrow_request_id"])
    op.create_index("ix_borrow_items_equipment_id", "borrow_items", ["equipment_id"])

    op.create_table(
        "notifications",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("borrow_request_id", UUID(as_uuid=True), sa.ForeignKey("borrow_requests.id"), nullable=True),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_read", sa.Boolean, nullable=False, server_default="false"),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])

    op.create_table(
        "audit_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("actor_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("target_table", sa.String(100), nullable=False),
        sa.Column("target_id", UUID(as_uuid=True), nullable=False),
        sa.Column("detail", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_audit_logs_actor_id", "audit_logs", ["actor_id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])

    op.create_table(
        "settings",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", sa.String(500), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("settings")
    op.drop_table("audit_logs")
    op.drop_table("notifications")
    op.drop_table("borrow_items")
    op.drop_table("borrow_requests")
    op.drop_table("equipment")
    op.drop_table("equipment_categories")
    op.drop_table("auth_tokens")
    op.drop_table("users")
