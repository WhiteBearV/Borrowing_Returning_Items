"""แยกเลขครุภัณฑ์ (asset_number) ออกจากรหัสอุปกรณ์ (code) + ออกรหัสระบบใหม่ DT-D-xxxxx ให้ครุภัณฑ์ (24 ก.ย. 69)

เดิมครุภัณฑ์ใช้เลขทะเบียนราชการเป็น code ตรง ๆ — ผู้ใช้ขอให้เลขครุภัณฑ์เป็นช่องแยก และให้ระบบออกรหัสเอง
1. equipment.asset_number (partial unique แบบ serial_number ใน 0019) + borrow_items.equipment_asset_number (snapshot)
2. ครุภัณฑ์เดิม: asset_number ← code แล้ว code ← DT-D-00001… เรียงตามเลขครุภัณฑ์
3. snapshot ใน borrow_items ของหน่วยเหล่านั้นย้ายตาม (equipment_asset_number ← รหัสเดิม, equipment_code ← รหัสใหม่)
   ค้นประวัติด้วยรหัสใหม่ได้ และเลขเดิมไม่หาย (อยู่ในช่องเลขครุภัณฑ์)
QR ไม่กระทบ (encode /equipment/{id}) แต่ป้ายที่พิมพ์รหัสเป็นตัวหนังสือจะไม่ตรงกับรหัสใหม่

Revision ID: 0048
Revises: 0047
"""
import sqlalchemy as sa
from alembic import op

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("equipment", sa.Column("asset_number", sa.String(length=50), nullable=True))
    op.create_index("ix_equipment_asset_number_unique", "equipment", ["asset_number"], unique=True,
                    postgresql_where=sa.text("asset_number IS NOT NULL"))
    op.add_column("borrow_items", sa.Column("equipment_asset_number", sa.String(length=50), nullable=True))
    # ถอยแล้วขึ้นซ้ำ (QA-03): downgrade เก็บรหัส DT-D เดิมไว้ใน equipment_dt_code_backup → เอากลับมาใช้ให้ได้รหัสเดิม
    # ทุกตัว · หน่วยที่ไม่มีในตารางสำรองได้เลขต่อจากเลขสูงสุดที่เคยออก · หน่วยที่ยังเป็น DT-D อยู่ (สร้างหลัง 0048
    # ไม่มีเลขครุภัณฑ์) ไม่แตะ — ไม่งั้น "DT-D-…" ถูกย้ายไปเป็นเลขครุภัณฑ์ · ฐานที่ไม่เคยผ่าน 0048 ได้ 00001… ตามเดิม
    has_backup = op.get_bind().execute(sa.text("SELECT to_regclass('equipment_dt_code_backup')")).scalar() is not None
    kept = "b.code" if has_backup else "NULL::text"
    join = "LEFT JOIN equipment_dt_code_backup b ON b.id = e.id" if has_backup else ""
    backup_max = ("(SELECT coalesce(max(substring(code from 6)::int), 0) FROM equipment_dt_code_backup)"
                  if has_backup else "0")
    op.execute(f"""
        WITH base AS (
            SELECT e.id, e.code AS old_code, {kept} AS kept
            FROM equipment e {join}
            WHERE e.item_type = 'durable' AND e.code NOT LIKE 'DT-D-%'
        ), mx AS (
            SELECT greatest(
                (SELECT coalesce(max(substring(code from 6)::int), 0) FROM equipment WHERE code ~ '^DT-D-[0-9]+$'),
                {backup_max}) AS m
        ), renum AS (
            SELECT id, old_code, coalesce(kept, 'DT-D-' || lpad((
                row_number() OVER (PARTITION BY (kept IS NULL) ORDER BY old_code) + (SELECT m FROM mx)
            )::text, 5, '0')) AS new_code
            FROM base
        ), eq AS (
            UPDATE equipment e SET asset_number = r.old_code, code = r.new_code
            FROM renum r WHERE e.id = r.id
            RETURNING e.id
        )
        UPDATE borrow_items bi SET equipment_asset_number = r.old_code, equipment_code = r.new_code
        FROM renum r WHERE bi.equipment_id = r.id
    """)
    op.execute("DROP TABLE IF EXISTS equipment_dt_code_backup")


def downgrade() -> None:
    # เก็บรหัส DT-D ที่กำลังจะถูกแทนด้วยเลขครุภัณฑ์ไว้ ให้ upgrade รอบถัดไปออกรหัสเดิม (ป้าย/เอกสารที่พิมพ์ไปแล้วยังตรง)
    op.execute("DROP TABLE IF EXISTS equipment_dt_code_backup")
    op.execute("""
        CREATE TABLE equipment_dt_code_backup AS
        SELECT id, code FROM equipment WHERE asset_number IS NOT NULL AND code LIKE 'DT-D-%'
    """)
    op.execute("""
        UPDATE borrow_items SET equipment_code = equipment_asset_number
        WHERE equipment_asset_number IS NOT NULL AND equipment_code LIKE 'DT-D-%'
    """)
    op.execute("""
        UPDATE equipment SET code = asset_number
        WHERE asset_number IS NOT NULL AND code LIKE 'DT-D-%'
    """)
    op.drop_column("borrow_items", "equipment_asset_number")
    op.drop_index("ix_equipment_asset_number_unique", table_name="equipment")
    op.drop_column("equipment", "asset_number")
