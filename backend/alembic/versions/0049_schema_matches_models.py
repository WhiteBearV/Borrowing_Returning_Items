"""ทำให้โครงสร้างฐานข้อมูลตรงกับโมเดล — `alembic check` ผ่าน (QA รอบ 2, R2-02 — 1 ต.ค. 69)

เดิมต่างกัน 36 จุด ใครเผลอ `--autogenerate` จะได้สคริปต์ที่ลบ index 3 ตัวและแก้ unique constraint โดยไม่ตั้งใจ
- คอลัมน์เวลา 21 ตัว (created_at/updated_at ฯลฯ): โมเดลเป็น NOT NULL แต่ฐานยอมให้ว่าง → เติมค่าว่าง (ถ้ามี) แล้วตั้ง NOT NULL
- unique 4 ตัว: ฐานมี "unique constraint + index ธรรมดา" ซ้อนกัน โมเดลประกาศ unique index ตัวเดียว → ยุบเหลือ unique index
  (ความหมายเท่าเดิม: ห้ามซ้ำ · ไม่มี FK ไหนอ้างคอลัมน์พวกนี้)
- index 3 ตัวที่มีในฐานแต่ไม่ได้ประกาศในโมเดล แก้ที่โมเดล (index=True) ไม่ต้องแตะฐาน

Revision ID: 0049
Revises: 0048
"""
from alembic import op

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None

TIME_COLUMNS = [
    ("audit_logs", "created_at"), ("auth_tokens", "created_at"), ("borrow_items", "created_at"),
    ("borrow_items", "updated_at"), ("borrow_requests", "created_at"), ("borrow_requests", "requested_at"),
    ("borrow_requests", "updated_at"), ("bundles", "created_at"), ("bundles", "updated_at"),
    ("change_requests", "created_at"), ("change_requests", "updated_at"), ("eligible_students", "imported_at"),
    ("equipment_categories", "created_at"), ("equipment", "created_at"), ("equipment", "updated_at"),
    ("equipment_parts", "created_at"), ("equipment_parts", "updated_at"), ("notifications", "sent_at"),
    ("settings", "updated_at"), ("users", "created_at"), ("users", "updated_at"),
]
# (ตาราง, คอลัมน์, ชื่อ constraint เดิม, ชื่อ index)
UNIQUES = [
    ("auth_tokens", "token", "auth_tokens_token_key", "ix_auth_tokens_token"),
    ("equipment", "code", "equipment_code_key", "ix_equipment_code"),
    ("users", "email", "users_email_key", "ix_users_email"),
    ("users", "username", "uq_users_username", "ix_users_username"),
]


def upgrade() -> None:
    for table, col in TIME_COLUMNS:
        op.execute(f"UPDATE {table} SET {col} = now() WHERE {col} IS NULL")
        op.alter_column(table, col, nullable=False)
    for table, col, constraint, index in UNIQUES:
        # สร้าง unique index ใหม่ก่อนถอดของเดิม — ไม่มีช่วงที่คอลัมน์ไม่มีตัวกันซ้ำ
        op.drop_index(index, table_name=table)
        op.create_index(index, table, [col], unique=True)
        op.drop_constraint(constraint, table, type_="unique")


def downgrade() -> None:
    for table, col, constraint, index in UNIQUES:
        op.create_unique_constraint(constraint, table, [col])
        op.drop_index(index, table_name=table)
        op.create_index(index, table, [col], unique=False)
    for table, col in TIME_COLUMNS:
        op.alter_column(table, col, nullable=True)
