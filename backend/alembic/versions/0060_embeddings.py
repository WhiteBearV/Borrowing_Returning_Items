"""แคชเวกเตอร์สำหรับค้นหาอุปกรณ์ด้วยรูป (SigLIP2) — 25 พ.ย. 69

คีย์ด้วย hash ของเนื้อหา ไม่ผูก equipment (ดู app/models/embedding.py) · ไม่ใช้ pgvector: ~150 รุ่นเทียบใน Python พอ

Revision ID: 0060
Revises: 0059
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0060"
down_revision = "0059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "embeddings",
        sa.Column("kind", sa.String(10), primary_key=True),
        sa.Column("source_hash", sa.String(64), primary_key=True),
        sa.Column("model", sa.String(100), primary_key=True),
        sa.Column("vector", postgresql.ARRAY(sa.REAL()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("embeddings")
