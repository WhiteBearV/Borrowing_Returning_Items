"""เก็บ snapshot ชื่อ/รหัส/หน่วยอุปกรณ์ไว้ใน borrow_items + เปลี่ยน FK equipment_id เป็น SET NULL

อุปกรณ์ที่ปลดระวางแล้วและไม่มีการยืมค้าง (pending/approved) ต้องลบออกจากทะเบียนถาวรได้ — เพื่อเปิดช่อง
ให้ใช้รหัสเดิมกับของทดแทนได้ แต่ห้ามทำให้ประวัติการยืมเก่าของนักศึกษาพัง (equipment_name/code/unit เดิมเป็น
@property ที่ join สดผ่าน equipment_id พอแถว equipment หายไปประวัติจะกลายเป็น None)

แนวทางเดียวกับ 0008 (audit_logs.actor_id): snapshot คอลัมน์จริง + FK เปลี่ยนเป็น nullable + ON DELETE SET NULL

Revision ID: 0020
Revises: 0019
"""
from alembic import op
import sqlalchemy as sa

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("borrow_items", sa.Column("equipment_name", sa.String(255), nullable=True))
    op.add_column("borrow_items", sa.Column("equipment_code", sa.String(50), nullable=True))
    op.add_column("borrow_items", sa.Column("equipment_unit", sa.String(50), nullable=True))
    op.execute(
        "UPDATE borrow_items b SET equipment_name = e.name, equipment_code = e.code, "
        "equipment_unit = e.unit FROM equipment e WHERE b.equipment_id = e.id"
    )
    op.alter_column("borrow_items", "equipment_id", existing_type=sa.dialects.postgresql.UUID(), nullable=True)
    op.drop_constraint("borrow_items_equipment_id_fkey", "borrow_items", type_="foreignkey")
    op.create_foreign_key(
        "borrow_items_equipment_id_fkey", "borrow_items", "equipment",
        ["equipment_id"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("borrow_items_equipment_id_fkey", "borrow_items", type_="foreignkey")
    op.create_foreign_key("borrow_items_equipment_id_fkey", "borrow_items", "equipment", ["equipment_id"], ["id"])
    op.alter_column("borrow_items", "equipment_id", existing_type=sa.dialects.postgresql.UUID(), nullable=False)
    op.drop_column("borrow_items", "equipment_unit")
    op.drop_column("borrow_items", "equipment_code")
    op.drop_column("borrow_items", "equipment_name")
