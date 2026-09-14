"""คิวคำขอแก้ไขข้อมูล — ผู้ดูแลคลังยื่นเรื่องให้ผู้ดูแลระบบสูงสุดทำให้ โดยมีหลักฐานเป็นลายลักษณ์อักษร

feedback อาจารย์ 5 ก.ย. 69: "AdminStore ไม่ควรแก้ฐานข้อมูลได้โดยตรง แต่ควรมีทางร้องขอที่ง่ายและมีบันทึก
เป็นหลักฐาน" — เดิมเรื่องแบบนี้คุยกันทางไลน์ ไม่เหลือร่องรอยว่าใครขออะไร ใครอนุมัติ เพราะอะไร

**payload เป็นข้อความอธิบาย ไม่ใช่คำสั่งที่ระบบเอาไปรันเอง** — ระบบรัน mutation จาก payload ได้เมื่อไหร่
ก็เท่ากับมีช่องรัน SQL ทางอ้อม ซึ่งเป็นสิ่งที่ตกลงกันแล้วว่าจะไม่ทำ ผู้ดูแลระบบสูงสุดอ่านคำขอแล้วไปกดทำเอง
ผ่านหน้าจอปกติ (ซึ่งมี audit log ของตัวเองอยู่แล้ว) จากนั้นค่อยกลับมาปิดงาน

Revision ID: 0030
Revises: 0029
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "change_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        # ON DELETE SET NULL + snapshot ชื่อ — หลักการเดียวกับ audit_logs: ลบบัญชีแล้วประวัติต้องไม่หาย
        sa.Column("requester_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("requester_name", sa.String(255), nullable=True),
        sa.Column("target_table", sa.String(100), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("target_label", sa.String(255), nullable=True),  # ชื่อที่คนอ่านรู้เรื่อง เช่น "NB-001 โน้ตบุ๊ค Dell"
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("detail", sa.Text, nullable=True),               # สิ่งที่อยากให้แก้ (ข้อความล้วน)
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("decided_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("decided_by_name", sa.String(255), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index("ix_change_requests_status", "change_requests", ["status"])


def downgrade() -> None:
    op.drop_index("ix_change_requests_status", table_name="change_requests")
    op.drop_table("change_requests")
