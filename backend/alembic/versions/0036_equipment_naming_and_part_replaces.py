"""มาตรฐานการตั้งชื่ออุปกรณ์ + ไทม์ไลน์การอัพเกรด (เฟส 8 — feedback อาจารย์ 5 ก.ย. 69 ข้อ 18, 17)

**ผู้ผลิต/รุ่น:** ต้นตอของ "DHT11 คืออะไร" คือเอา *ชื่อรุ่น* มาเป็น *ชื่อสินค้า* แล้วค้นคำว่า
"เซ็นเซอร์ความชื้น" ไม่เจอ มาตรฐานสากล (FTMaintenance / Tractian / eCl@ss) แยก 3 อย่างออกจากกัน:
  ชื่อ (ป้ายให้คนอ่าน) ≠ รุ่น (เหมือนกันทุกชิ้น) ≠ ซีเรียล (ไม่ซ้ำรายชิ้น) ≠ รหัสทะเบียน (ระบบออกให้)
ระบบมี name / serial_number / code อยู่แล้ว ขาด manufacturer + model_number ซึ่งเพิ่มตรงนี้

**replaces_part_id:** ชิ้นส่วนใหม่มาแทนชิ้นไหน — ได้ไทม์ไลน์ "SSD 256 → 512 → 1TB" ต่อเนื่อง
แทนที่จะเห็นเป็นรายการชิ้นส่วนกองรวมกันโดยไม่รู้ว่าอันไหนแทนอันไหน
ON DELETE SET NULL: ประวัติการอัพเกรดต้องไม่หายทั้งสายเพราะแถวต้นสายถูกลบ

Revision ID: 0036
Revises: 0035
"""
import sqlalchemy as sa
from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("equipment", sa.Column("manufacturer", sa.String(255), nullable=True))
    op.add_column("equipment", sa.Column("model_number", sa.String(100), nullable=True))
    # ค้นหา "DHT11" ต้องเจอทั้งจากชื่อและจากช่องรุ่น — index ช่วยตอนคลังโตขึ้น (ตอนนี้ ~1,500 แถว)
    op.create_index("ix_equipment_model_number", "equipment", ["model_number"])
    op.add_column("equipment_parts", sa.Column(
        "replaces_part_id", sa.UUID(as_uuid=True),
        sa.ForeignKey("equipment_parts.id", ondelete="SET NULL"), nullable=True))


def downgrade() -> None:
    op.drop_column("equipment_parts", "replaces_part_id")
    op.drop_index("ix_equipment_model_number", table_name="equipment")
    op.drop_column("equipment", "model_number")
    op.drop_column("equipment", "manufacturer")
