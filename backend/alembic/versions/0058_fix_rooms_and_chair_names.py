"""แก้ข้อมูลห้อง/ชื่อเก้าอี้ที่เจอตอน QA 24 พ.ย. 69 (ผู้ใช้ตัดสิน)

1. ห้องชื่อยาว 4 ค่าที่ 0053 แยกออกมา — ช่องตำแหน่งในห้องได้คำอธิบายอาคารแทนตู้/ชั้น และเขียนไม่เหมือนกัน
   → ปล่อยว่าง (เลขห้องบอกที่อยู่พอแล้ว · ของเป็นโต๊ะ/เก้าอี้ ไม่ได้อยู่ในตู้)
2. "604" เป็นเลขอาคาร ไม่ใช่ห้อง → ห้อง "ห้อง Data center"
   (เลขห้องของคณะ: 15xxx = ตึก 615 · 5xxx = ตึก 605 · 4xxx = ตึก 604)
3. เก้าอี้รุ่นเดียวกันชื่อต่างกันเพราะเลขท้ายขนาดไหลตามลำดับ (ลากเติมใน Excel: 50x46x80, x81, x82 …
   ตรงกับเลขลำดับท้ายเลขครุภัณฑ์) → ระบบนับเป็นคนละรุ่น 48 รุ่นจาก 64 ตัว
   ใช้ขนาดของตัวแรกในชุด (ค่าน้อยสุด) เป็นชื่อรุ่น → เหลือ 4 รุ่น
4. ห้อง "15399" ไม่มีจริง พิมพ์ผิดจาก "15309" (คอมพิวเตอร์ Dell Optiplex 7040 รุ่นเดียวกันอยู่ 15309 อีก 3 เครื่อง)

ข้อมูลอย่างเดียว ไม่แตะโครงสร้าง · downgrade ไม่คืนค่า (ค่าเดิมผิดอยู่แล้ว ไม่มีเหตุให้ย้อน)

Revision ID: 0058
Revises: 0057
"""
import sqlalchemy as sa
from alembic import op

revision = "0058"
down_revision = "0057"
branch_labels = None
depends_on = None

# ค่าตำแหน่งที่ 0053 ใส่ไว้ (ห้อง, ตำแหน่ง) — แก้เฉพาะคู่นี้ ตำแหน่งที่เจ้าหน้าที่กรอกเองหลังจากนั้นไม่แตะ
_DETAILS = [
    ("5304", "ห้องเรียนชั่วคราว คณะเทคโนโลยีดิจิทัล"),
    ("5324", "ชั้น 3 ห้องเรียนชั่วคราว คณะเทคโนโลยีดิจิทัล"),
    ("5423", "ห้องพักครูชั้น 4 ห้องชั่วคราวคณะเทคโนโลยีดิจิทัล"),
    ("604", "ห้อง Data center ชั้น 3"),
]


def upgrade() -> None:
    conn = op.get_bind()
    conn.exec_driver_sql(
        "UPDATE equipment SET location = 'ห้อง Data center' "
        "WHERE location = '604' AND location_detail = 'ห้อง Data center ชั้น 3'")
    for room, detail in _DETAILS:
        room = "ห้อง Data center" if room == "604" else room
        conn.execute(sa.text(
            "UPDATE equipment SET location_detail = NULL WHERE location = :room AND location_detail = :detail"),
            {"room": room, "detail": detail})
    conn.exec_driver_sql("UPDATE equipment SET location = '15309' WHERE location = '15399'")
    # ponytail: จำกัดที่ "เก้าอี้นั่ง…" — รุ่นอื่นที่มิติท้ายต่างกันจริงต้องไม่ถูกรวม
    conn.exec_driver_sql(r"""
        UPDATE equipment e SET name = s.base || s.first_size
        FROM (
            SELECT id, regexp_replace(name, '\d+$', '') AS base,
                   min(substring(name from '(\d+)$')::int) OVER (PARTITION BY regexp_replace(name, '\d+$', '')) AS first_size
            FROM equipment
            WHERE name ~ '^เก้าอี้นั่ง.*ขนาด \d+x\d+x\d+$'
        ) s
        WHERE e.id = s.id AND e.name <> s.base || s.first_size
    """)


def downgrade() -> None:
    pass
