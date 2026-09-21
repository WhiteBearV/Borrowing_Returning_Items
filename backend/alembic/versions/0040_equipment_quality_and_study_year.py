"""ค่าคุณภาพอุปกรณ์ + ชั้นปีนักศึกษา (เฟส 10 — 15 ก.ย. 69)

ผู้ใช้/อาจารย์อยากให้ระบบรู้สภาพจริงของอุปกรณ์แต่ละหน่วย (ค่าคุณภาพ %) ที่ลดลงตามอายุและการใช้งาน
และรู้ชั้นปีของนักศึกษา (รวมตกค้าง/เทียบโอน) เพื่อจ่ายเครื่องที่อายุเหลือพอดีกับเวลาเรียนที่เหลือ

equipment: quality_tracked (เปิดทีละรุ่น, เริ่มต้น false) · quality_life_years (ว่าง = ใช้ค่ากลาง) ·
quality_baseline (numeric 5,2 — ว่าง = "ยังไม่ประเมิน" ห้ามใช้ 0 แทน) · quality_baseline_at

users: enrollment_year (พ.ศ., backfill จาก 2 หลักแรกของรหัสนักศึกษา 10 หลัก) · study_years (เริ่มต้น 4) ·
is_transfer (เริ่มต้น false)

ของเดิมในระบบตอนนี้ (722 ครุภัณฑ์ + 775 วัสดุใช้ซ้ำ) ไม่มีวันที่ได้มา/อายุการใช้งานอยู่แล้ว — เปิดติดตาม
คุณภาพเป็น opt-in ทีละรุ่น จึงไม่กระทบของเดิมที่ยังไม่พร้อม (quality_baseline ว่าง = ยังไม่ประเมิน ยืมได้ปกติ)

settings ใหม่ 5 คีย์ (ดู CLAUDE.md หมวดค่าคุณภาพ + ชั้นปี สำหรับสิทธิ์แก้ไขรายคีย์)

Revision ID: 0040
Revises: 0039
"""
import sqlalchemy as sa
from alembic import op

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None

_SETTINGS = [
    ("quality_age_weight", "50",
     "น้ำหนักผลของ 'อายุ' เทียบกับ 'การใช้งาน' ในการคิดค่าคุณภาพอุปกรณ์ (0-100, ที่เหลือเป็นน้ำหนักการใช้งาน)"),
    ("quality_life_years_default", "4",
     "อายุการใช้งานกลาง (ปี) สำหรับคิดค่าคุณภาพ เมื่ออุปกรณ์ไม่ได้ตั้งค่าเฉพาะของตัวเอง"),
    ("quality_repair_default_drop", "2",
     "ค่าคุณภาพที่ระบบเสนอให้หักเมื่อซ่อม/เปลี่ยนอะไหล่ (จุดเปอร์เซ็นต์) — แอดมินแก้เป็นค่าอื่นได้เสมอ"),
    ("quality_low_threshold", "10",
     "เกณฑ์ค่าคุณภาพต่ำ (%) ที่ขึ้นป้ายเตือนให้เจ้าหน้าที่ตรวจสภาพ — อุปกรณ์ยังยืมได้ตามปกติ"),
    ("academic_year_start", "06-01",
     "วันที่เริ่มปีการศึกษาใหม่ (MM-DD) — ใช้เลื่อนชั้นปีนักศึกษาอัตโนมัติทุกปี"),
]


def upgrade() -> None:
    op.add_column("equipment", sa.Column(
        "quality_tracked", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("equipment", sa.Column("quality_life_years", sa.Integer(), nullable=True))
    op.add_column("equipment", sa.Column("quality_baseline", sa.Numeric(5, 2), nullable=True))
    op.add_column("equipment", sa.Column("quality_baseline_at", sa.DateTime(timezone=True), nullable=True))

    op.add_column("users", sa.Column("enrollment_year", sa.Integer(), nullable=True))
    op.add_column("users", sa.Column(
        "study_years", sa.Integer(), nullable=False, server_default="4"))
    op.add_column("users", sa.Column(
        "is_transfer", sa.Boolean(), nullable=False, server_default="false"))

    # backfill enrollment_year = 2500 + สองหลักแรกของรหัสนักศึกษา (เฉพาะรหัส 10 หลักพอดี — ตรงกับ
    # app.utils.study_year.enrollment_year_from_student_id ห้ามให้สูตรสองที่นี้เพี้ยนจากกัน)
    op.execute("""
        UPDATE users
        SET enrollment_year = 2500 + CAST(SUBSTRING(student_id FROM 1 FOR 2) AS INTEGER)
        WHERE student_id ~ '^[0-9]{10}$'
    """)

    for key, value, desc in _SETTINGS:
        op.execute(sa.text(
            "INSERT INTO settings (key, value, description) VALUES (:k, :v, :d) "
            "ON CONFLICT (key) DO NOTHING"
        ).bindparams(k=key, v=value, d=desc))


def downgrade() -> None:
    for key, _, _ in _SETTINGS:
        op.execute(sa.text("DELETE FROM settings WHERE key = :k").bindparams(k=key))
    op.drop_column("users", "is_transfer")
    op.drop_column("users", "study_years")
    op.drop_column("users", "enrollment_year")
    op.drop_column("equipment", "quality_baseline_at")
    op.drop_column("equipment", "quality_baseline")
    op.drop_column("equipment", "quality_life_years")
    op.drop_column("equipment", "quality_tracked")
