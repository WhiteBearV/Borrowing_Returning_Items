"""ค่าปรับล่าช้า + ค่าเสียหาย (เฟส 6 — feedback อาจารย์ 5 ก.ย. 69 ข้อ 7)

ขอบเขตที่ตกลงกันไว้: **คิดและเก็บประวัติเท่านั้น ยังไม่บล็อกการยืมครั้งต่อไป**
วันที่จะบังคับจริงคือเพิ่มเงื่อนไขใน borrow_service.create_request จุดเดียว ไม่ต้องรื้อ schema นี้

ยอดถูก freeze ลงแถวตอนปิดรายการ ไม่คำนวณสดทุกครั้งที่อ่าน — อัตราใน settings แก้ได้ตลอด
ถ้าคำนวณสดยอดของเคสที่คืนไปแล้วจะขยับตามทุกครั้งที่แอดมินปรับอัตรา = เถียงกับผู้ถูกปรับไม่ได้
(หลักการเดียวกับ unit_value_snapshot / book_value_snapshot ที่ใช้อยู่แล้ว)

ของที่คืนไปก่อน migration นี้ไม่คิดย้อนหลัง — fine_status = 'none' ทั้งหมด

Revision ID: 0034
Revises: 0033
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None

_SETTINGS = [
    ("fine_per_day_per_item", "10", "ค่าปรับคืนช้า (บาท/วัน/รายการ)"),
    ("fine_grace_days", "0", "ผ่อนผันกี่วันก่อนเริ่มคิดค่าปรับ (0 = คิดตั้งแต่วันแรกที่เกินกำหนด)"),
    ("fine_max_per_item", "0", "เพดานค่าปรับล่าช้าต่อรายการ (บาท, 0 = ไม่จำกัด)"),
]


def upgrade() -> None:
    op.add_column("borrow_items", sa.Column("fine_days_late", sa.Integer(), nullable=True))
    op.add_column("borrow_items", sa.Column("fine_late_amount", sa.Numeric(12, 2), nullable=True))
    op.add_column("borrow_items", sa.Column("fine_damage_amount", sa.Numeric(12, 2), nullable=True))
    # อัตรา/เพดาน/มูลค่าที่ใช้คำนวณ ณ วันนั้น — ต้องอธิบายที่มาของตัวเลขให้ผู้ถูกปรับได้
    op.add_column("borrow_items", sa.Column("fine_basis", JSONB(), nullable=True))
    op.add_column("borrow_items", sa.Column(
        "fine_status", sa.String(20), nullable=False, server_default="none"))
    op.add_column("borrow_items", sa.Column(
        "fine_waived_by", sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True))
    op.add_column("borrow_items", sa.Column("fine_waived_reason", sa.Text(), nullable=True))
    op.add_column("borrow_items", sa.Column("fine_waived_at", sa.DateTime(timezone=True), nullable=True))
    # หน้า /admin/fines กรองด้วยสถานะเป็นหลัก (ค้างชำระ/ชำระแล้ว/ยกเว้น)
    op.create_index("ix_borrow_items_fine_status", "borrow_items", ["fine_status"])

    for key, value, desc in _SETTINGS:
        op.execute(sa.text(
            "INSERT INTO settings (key, value, description) VALUES (:k, :v, :d) "
            "ON CONFLICT (key) DO NOTHING"
        ).bindparams(k=key, v=value, d=desc))


def downgrade() -> None:
    for key, _, _ in _SETTINGS:
        op.execute(sa.text("DELETE FROM settings WHERE key = :k").bindparams(k=key))
    op.drop_index("ix_borrow_items_fine_status", table_name="borrow_items")
    op.drop_column("borrow_items", "fine_waived_at")
    op.drop_column("borrow_items", "fine_waived_reason")
    op.drop_column("borrow_items", "fine_waived_by")
    op.drop_column("borrow_items", "fine_status")
    op.drop_column("borrow_items", "fine_basis")
    op.drop_column("borrow_items", "fine_damage_amount")
    op.drop_column("borrow_items", "fine_late_amount")
    op.drop_column("borrow_items", "fine_days_late")
