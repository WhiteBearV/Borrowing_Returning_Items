"""เก็บคำอธิบาย setting ให้เป็นภาษาคน ไม่มีชื่อค่าดิบ (feedback ผู้ใช้ 8 ก.ย. 69)

หน้าเว็บเลิกโชว์ชื่อ key ดิบแล้ว และช่อง pdf_value_source กลายเป็นดรอปดาวน์ คำอธิบายที่ยังเขียนว่า
"acquisition (…) หรือ book (…)" จึงเหลือแค่ศัพท์ที่ผู้ใช้ไม่ต้องรู้ — เขียนใหม่ให้อ่านแล้วเข้าใจทันที

Revision ID: 0039
Revises: 0038
"""
import sqlalchemy as sa
from alembic import op

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None

_NEW = {
    "pdf_value_source": "มูลค่าที่พิมพ์ลงในใบยืม/ใบคืน",
    "default_pickup_location": "สถานที่นัดรับของเริ่มต้น (เติมให้อัตโนมัติในหน้าอนุมัติ)",
    "default_pickup_time": "เวลานัดรับของเริ่มต้น (เติมให้อัตโนมัติในหน้าอนุมัติ)",
}


def upgrade() -> None:
    for key, desc in _NEW.items():
        op.execute(sa.text("UPDATE settings SET description = :d WHERE key = :k")
                   .bindparams(d=desc, k=key))


def downgrade() -> None:
    # คำอธิบายเป็นข้อความช่วยอ่านเท่านั้น ไม่ต้องย้อน (ค่าเดิมไม่มีผลต่อการทำงาน)
    pass
