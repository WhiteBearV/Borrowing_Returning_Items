"""นัดรับของ / นัดคืนของ (เฟส 4 — feedback อาจารย์ 5 ก.ย. 69 ข้อ 10, 12)

อาจารย์: "อนุมัติแล้วไปรับของที่ไหน เมื่อไหร่" และ "แอดมินไม่รู้ล่วงหน้าว่าวันนี้จะมีใครมาคืนอะไรกี่โมง"
เดิมนัดกันทางไลน์/เจอหน้ากัน ไม่มีร่องรอยในระบบ ผู้ยืมจึงไปถึงแล้วไม่มีคนอยู่ก็มี

- นัดรับอยู่ระดับ "คำขอ" (จ่ายของทั้งใบพร้อมกันในนัดเดียว) เว้นว่างได้ = จ่ายทันทีหน้าเคาน์เตอร์
- นัดคืนอยู่ระดับ "รายชิ้น" เพราะคืนแยกชิ้นได้ตั้งแต่เฟส 3 (คืนโน้ตบุ๊ควันนี้ คืนกล้องอาทิตย์หน้า)

Revision ID: 0032
Revises: 0031
"""
import sqlalchemy as sa
from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None

_SETTINGS = [
    ("default_pickup_location", "ห้องพัสดุ คณะเทคโนโลยีดิจิทัล", "สถานที่นัดรับของเริ่มต้น (เติมให้ในโมดัลอนุมัติ)"),
    ("default_pickup_time", "13:00", "เวลานัดรับของเริ่มต้น รูปแบบ HH:MM"),
]


def upgrade() -> None:
    op.add_column("borrow_requests", sa.Column("pickup_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("borrow_requests", sa.Column("pickup_location", sa.String(255), nullable=True))
    op.add_column("borrow_requests", sa.Column("pickup_note", sa.Text(), nullable=True))
    op.add_column("borrow_items", sa.Column("return_appoint_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("borrow_items", sa.Column("return_appoint_location", sa.String(255), nullable=True))

    for key, value, desc in _SETTINGS:
        op.execute(sa.text(
            "INSERT INTO settings (key, value, description) VALUES (:k, :v, :d) "
            "ON CONFLICT (key) DO NOTHING"
        ).bindparams(k=key, v=value, d=desc))


def downgrade() -> None:
    for key, _, _ in _SETTINGS:
        op.execute(sa.text("DELETE FROM settings WHERE key = :k").bindparams(k=key))
    op.drop_column("borrow_items", "return_appoint_location")
    op.drop_column("borrow_items", "return_appoint_at")
    op.drop_column("borrow_requests", "pickup_note")
    op.drop_column("borrow_requests", "pickup_location")
    op.drop_column("borrow_requests", "pickup_at")
