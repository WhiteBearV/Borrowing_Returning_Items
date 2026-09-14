"""ตารางชิ้นส่วนอุปกรณ์ (equipment_parts) — รองรับการอัพเกรดบนครุภัณฑ์เลขเดิม

โจทย์จากอาจารย์: อัพเกรด RAM 8→16GB บนโน้ตบุ๊คเลขครุภัณฑ์เดิม ต้องเก็บว่าเปลี่ยนอะไรเมื่อไร
และ "อายุของเครื่องหลักกับของที่อัพเกรดต้องแยกจากกัน" เพื่อใช้ตัดสินใจเรื่องการให้ยืม

ชิ้นส่วนถอดออกแล้วไม่ลบแถว (ตั้ง removed_at แทน) เพราะประวัติการอัพเกรดคือหลักฐาน
ชื่อคอลัมน์ unit_value/acquired_at/useful_life_years ตรงกับตาราง equipment โดยตั้งใจ —
equipment_service.book_value() ใช้กับทั้งสองตารางได้ด้วยฟังก์ชันเดียว

หมายเหตุ: ห้ามแก้ไฟล์นี้หลัง apply ลง prod แล้ว (บทเรียนจาก 0021 ที่ต้องเขียน 0023 มาลบทีหลัง)
ถ้าต้องเปลี่ยนให้เขียน migration ใหม่ต่อท้ายเสมอ

Revision ID: 0027
Revises: 0026
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "equipment_parts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("equipment_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("equipment.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("serial_number", sa.String(255), nullable=True),
        sa.Column("unit_value", sa.Numeric(12, 2), nullable=True),
        sa.Column("acquired_at", sa.Date(), nullable=True),
        sa.Column("useful_life_years", sa.Integer(), nullable=True),
        sa.Column("removed_at", sa.Date(), nullable=True),
        sa.Column("removed_reason", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_equipment_parts_equipment_id", "equipment_parts", ["equipment_id"])


def downgrade() -> None:
    op.drop_index("ix_equipment_parts_equipment_id", table_name="equipment_parts")
    op.drop_table("equipment_parts")
