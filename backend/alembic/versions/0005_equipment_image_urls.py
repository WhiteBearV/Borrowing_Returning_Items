"""add image_urls (gallery) to equipment

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("equipment", sa.Column("image_urls", sa.JSON(), nullable=True))
    # backfill: รูปเดิม (image_url) กลายเป็นรูปแรกใน gallery, ที่เหลือเป็น []
    op.execute(
        "UPDATE equipment SET image_urls = "
        "CASE WHEN image_url IS NULL THEN '[]'::json "
        "ELSE json_build_array(image_url) END"
    )
    op.alter_column("equipment", "image_urls", nullable=False)


def downgrade() -> None:
    op.drop_column("equipment", "image_urls")
