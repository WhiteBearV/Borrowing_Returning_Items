"""ป้ายอัตราค่าปรับคืนเกินกำหนดรายรุ่น (23 พ.ย. 69)

สร้างป้าย 5 / 10 / 20 / 30 บาทต่อวัน (10 = ค่าเริ่มต้น) แล้วตั้งอุปกรณ์ทุกชิ้นเป็น 10 บาท ตามที่ผู้ใช้สั่ง
— ยอดค่าปรับเท่าเดิมทุกกรณี (อัตรากลางเดิมก็ 10 บาท) จนกว่าเจ้าหน้าที่จะเปลี่ยนป้ายรายรุ่น
รายการที่อนุมัติไปก่อนนี้ไม่มี fine_rate_snapshot → ตอนคืนใช้ setting fine_per_day_per_item เหมือนเดิม

Revision ID: 0056
Revises: 0055
"""
import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None

SEED = [(5, False), (10, True), (20, False), (30, False)]


def upgrade() -> None:
    rates = op.create_table(
        "fine_rates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("amount_per_day", sa.Numeric(10, 2), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("amount_per_day >= 0", name="ck_fine_rates_amount_nonneg"),
    )
    # ป้ายค่าเริ่มต้นมีได้ป้ายเดียว
    op.create_index("uq_fine_rates_default", "fine_rates", ["is_default"], unique=True,
                    postgresql_where=sa.text("is_default"))
    ids = {amount: uuid.uuid4() for amount, _ in SEED}
    op.bulk_insert(rates, [{"id": ids[a], "name": f"{a} บาท/วัน", "amount_per_day": a, "is_default": d} for a, d in SEED])

    op.add_column("equipment", sa.Column("fine_rate_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_equipment_fine_rate", "equipment", "fine_rates", ["fine_rate_id"], ["id"], ondelete="RESTRICT")
    op.execute(sa.text("UPDATE equipment SET fine_rate_id = :id").bindparams(id=ids[10]))

    op.add_column("borrow_items", sa.Column("fine_rate_snapshot", sa.Numeric(10, 2), nullable=True))
    # อัตรากลางเดิมเหลือใช้แค่กับรายการที่อนุมัติก่อนมีป้าย — เปลี่ยนคำอธิบายให้ไม่มีใครเข้าใจผิดว่าเป็นอัตราของทุกชิ้น
    op.execute(sa.text("UPDATE settings SET description = :d WHERE key = 'fine_per_day_per_item'").bindparams(
        d="อัตราค่าปรับของรายการที่ยืมก่อนมีป้ายอัตรา (บาท/วัน) — ของใหม่ใช้ป้ายอัตรารายรุ่นด้านล่าง"))


def downgrade() -> None:
    op.execute(sa.text("UPDATE settings SET description = 'ค่าปรับคืนช้า (บาท/วัน/รายการ)' WHERE key = 'fine_per_day_per_item'"))
    op.drop_column("borrow_items", "fine_rate_snapshot")
    op.drop_constraint("fk_equipment_fine_rate", "equipment", type_="foreignkey")
    op.drop_column("equipment", "fine_rate_id")
    op.drop_index("uq_fine_rates_default", table_name="fine_rates")
    op.drop_table("fine_rates")
