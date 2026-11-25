"""ชื่อครุภัณฑ์ตามบัญชี (asset_name) แยกจากชื่อในระบบ (name) — 25 พ.ย. 69

ชื่อในทะเบียนราชการเป็นคำบรรยายยาว ("เครื่องคอมพิวเตอร์สำหรับประมวลผลแบบที่ 2 จอขนาดไม่น้อยกว่า 19 นิ้ว")
ค้นหายาก และนำเข้าไฟล์ทะเบียนทุกรอบทับชื่อสั้นที่ตั้งไว้ → แยกเก็บ name ใช้ค้น/จับกลุ่มรุ่นเหมือนเดิม

- equipment.asset_name: ครุภัณฑ์เดิมคัดลอกจาก name (ผู้ใช้เลือก — แก้ทีหลังได้)
- borrow_items.equipment_asset_name: snapshot ณ วันยืม ไม่ backfill (ใบเก่าพิมพ์เหมือนเดิม)
- stocktake_items.asset_name: backfill = equipment_name ใบตรวจรอบเก่าไม่เปลี่ยน

Revision ID: 0059
Revises: 0058
"""
import sqlalchemy as sa
from alembic import op

revision = "0059"
down_revision = "0058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("equipment", sa.Column("asset_name", sa.String(255), nullable=True))
    op.add_column("borrow_items", sa.Column("equipment_asset_name", sa.String(255), nullable=True))
    op.add_column("stocktake_items", sa.Column("asset_name", sa.String(255), nullable=True))
    op.execute("UPDATE equipment SET asset_name = name WHERE item_type = 'durable'")
    op.execute("UPDATE stocktake_items SET asset_name = equipment_name")


def downgrade() -> None:
    op.drop_column("stocktake_items", "asset_name")
    op.drop_column("borrow_items", "equipment_asset_name")
    op.drop_column("equipment", "asset_name")
