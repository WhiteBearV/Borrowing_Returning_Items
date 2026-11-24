"""แยก "ห้อง" กับ "ตำแหน่งในห้อง" (23 พ.ย. 69)

equipment.location = ห้องเท่านั้น (ใช้กรอง/ตรวจครุภัณฑ์/QR ห้อง) · equipment.location_detail = ตำแหน่งในห้อง (ตู้/ชั้น)
พร้อมแยกชื่อห้องยาว 4 ค่าที่มีอยู่จริงตามที่ผู้ใช้กำหนด — ไม่งั้นห้องเดียวกันแตกเป็นหลายห้อง (5304 กับ "ชั้น 3 ห้อง 5304 …")

Revision ID: 0053
Revises: 0052
"""
import sqlalchemy as sa
from alembic import op

revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None

# ค่าเดิม → (ห้อง, ตำแหน่งในห้อง) — ผู้ใช้ระบุเอง 23 พ.ย. 69
SPLITS = [
    ("ชั้น 3 ห้อง 5304 ห้องเรียนชั่วคราว คณะเทคโนโลยีดิจิทัล", "5304", "ห้องเรียนชั่วคราว คณะเทคโนโลยีดิจิทัล"),
    ("ชั้น 3 ห้อง 5324 ห้องเรียนชั่วคราว คณะเทคโนโลยีดิจิทัล", "5324", "ชั้น 3 ห้องเรียนชั่วคราว คณะเทคโนโลยีดิจิทัล"),
    ("ห้อง Data center อาคาร 604 ชั้น 3", "604", "ห้อง Data center ชั้น 3"),
    ("ห้องพักครูชั้น 4 ห้อง 5423 ชั่วคราวคณะเทคโนโลยีดิจิทัล", "5423", "ห้องพักครูชั้น 4 ห้องชั่วคราวคณะเทคโนโลยีดิจิทัล"),
]


def upgrade() -> None:
    op.add_column("equipment", sa.Column("location_detail", sa.String(255), nullable=True))
    eq = sa.table("equipment", sa.column("location", sa.String), sa.column("location_detail", sa.String))
    for old, room, detail in SPLITS:
        op.execute(eq.update().where(eq.c.location == old).values(location=room, location_detail=detail))


def downgrade() -> None:
    eq = sa.table("equipment", sa.column("location", sa.String), sa.column("location_detail", sa.String))
    for old, room, detail in SPLITS:
        op.execute(eq.update().where(eq.c.location == room, eq.c.location_detail == detail).values(location=old))
    op.drop_column("equipment", "location_detail")
