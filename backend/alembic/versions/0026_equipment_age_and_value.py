"""อายุอุปกรณ์ + มูลค่า 2 แบบ (แท้จริง / ตามบัญชี)

เดิมระบบไม่มี "วันที่ได้มา" ของอุปกรณ์เลย — created_at ใช้แทนไม่ได้เพราะ split_equipment/restock_equipment
สร้างแถวใหม่ทำให้วันที่รีเซ็ต และของ 704 แถวที่ seed ครั้งแรกมี created_at เท่ากันหมด
acquired_at จึงเป็นคอลัมน์แยกที่ import ดึงมาจากคอลัมน์ "ว/ด/ป ที่รับ" ในไฟล์ทะเบียนคุมทรัพย์สิน

มูลค่า: unit_value เดิม = "มูลค่าแท้จริง" (ราคาที่ซื้อมา) คงชื่อไว้เพราะถูกอ้างทั้งใน unit_value_snapshot,
pdf.py, dashboard_service และ frontend — เพิ่มแค่ book_value_override (แอดมินกรอกทับ) กับ useful_life_years
ส่วนมูลค่าตามบัญชีคำนวณสดจากสูตรเส้นตรง ไม่เก็บคอลัมน์เพราะค่าเปลี่ยนทุกวัน

Revision ID: 0026
Revises: 0025
"""
from alembic import op
from sqlalchemy.sql import table, column
import sqlalchemy as sa

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None

settings_table = table(
    "settings",
    column("key", sa.String),
    column("value", sa.String),
    column("description", sa.String),
)

NEW_SETTINGS = [
    ("depreciation_years_default", "5",
     "อายุการใช้งานเริ่มต้นสำหรับคำนวณค่าเสื่อม (ปี) ใช้เมื่ออุปกรณ์ไม่ได้ตั้งค่าเฉพาะ"),
    ("depreciation_salvage_value", "1",
     "มูลค่าซากคงเหลือหลังหมดอายุการใช้งาน (บาท) ตามระเบียบพัสดุ"),
    ("pdf_value_source", "acquisition",
     "มูลค่าที่แสดงในใบยืม PDF — acquisition (มูลค่าแท้จริง) หรือ book (มูลค่าตามบัญชี)"),
]


def upgrade() -> None:
    op.add_column("equipment", sa.Column("acquired_at", sa.Date(), nullable=True))
    op.add_column("equipment", sa.Column("useful_life_years", sa.Integer(), nullable=True))
    op.add_column("equipment", sa.Column("book_value_override", sa.Numeric(12, 2), nullable=True))
    op.add_column("borrow_items", sa.Column("book_value_snapshot", sa.Numeric(12, 2), nullable=True))
    op.bulk_insert(settings_table, [{"key": k, "value": v, "description": d} for k, v, d in NEW_SETTINGS])


def downgrade() -> None:
    op.execute("DELETE FROM settings WHERE key IN (%s)" % ",".join(f"'{k}'" for k, _, _ in NEW_SETTINGS))
    op.drop_column("borrow_items", "book_value_snapshot")
    op.drop_column("equipment", "book_value_override")
    op.drop_column("equipment", "useful_life_years")
    op.drop_column("equipment", "acquired_at")
