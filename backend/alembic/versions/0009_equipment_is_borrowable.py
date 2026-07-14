"""equipment.is_borrowable — ของประจำห้อง (โต๊ะ/ตู้/ทีวี) ห้ามยืมออก

Revision ID: 0009
Revises: 0008
"""
import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

# หมวดที่เป็นของประจำห้องตามธรรมชาติ — ตั้งค่าเริ่มต้นให้ห้ามยืม แอดมินเปิดรายชิ้นได้ทีหลัง
FIXED_CATEGORIES = ("โต๊ะ/ตู้/เฟอร์นิเจอร์", "โสตทัศนูปกรณ์", "ซอฟต์แวร์/ลิขสิทธิ์")


def upgrade() -> None:
    op.add_column(
        "equipment",
        sa.Column("is_borrowable", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.execute(
        "UPDATE equipment SET is_borrowable = false WHERE id IN ("
        "  SELECT l.equipment_id FROM equipment_category_links l"
        "  JOIN equipment_categories c ON c.id = l.category_id"
        f"  WHERE c.name IN {FIXED_CATEGORIES}"
        ")"
    )


def downgrade() -> None:
    op.drop_column("equipment", "is_borrowable")
