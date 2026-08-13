"""เพิ่ม CHECK constraint กันสต็อกติดลบ/เกินจำนวนรวม

ตาข่ายชั้นสุดท้ายของสต็อก — design doc §2.3 กำหนดไว้ตั้งแต่แรกแต่ 0001 ไม่ได้ใส่มา

จุดหักสต็อกใน borrow_service.approve_request อ่านค่ามาคิดใน Python แล้วค่อยเขียนกลับ
ถึงจะใส่ SELECT ... FOR UPDATE ไปแล้ว constraint นี้ก็ยังจำเป็น เพราะถ้าวันหน้ามีใคร
เพิ่มเส้นทางแก้สต็อกใหม่แล้วลืมล็อก ผลลัพธ์จะเป็น error ที่เห็นทันที
แทนที่จะเป็นสต็อกติดลบเงียบ ๆ ที่ไม่มีใครรู้จนกว่าจะนับของจริง

Revision ID: 0016
Revises: 0015
"""
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ปรับข้อมูลเดิมให้เข้าเงื่อนไขก่อน ไม่งั้น ADD CONSTRAINT จะล้ม
    # (ตรวจ DB ปัจจุบันแล้วไม่มีแถวไหนผิด แต่ environment อื่นอาจไม่เหมือนกัน)
    op.execute("UPDATE equipment SET quantity_available = 0 WHERE quantity_available < 0")
    op.execute(
        "UPDATE equipment SET quantity_available = quantity_total "
        "WHERE quantity_available > quantity_total"
    )
    op.create_check_constraint(
        "ck_equipment_quantity_available_range",
        "equipment",
        "quantity_available >= 0 AND quantity_available <= quantity_total",
    )


def downgrade() -> None:
    op.drop_constraint("ck_equipment_quantity_available_range", "equipment", type_="check")
