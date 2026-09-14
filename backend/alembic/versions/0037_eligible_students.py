"""รายชื่อนักศึกษาที่มีสิทธิ์สมัคร + คิวอนุมัติผู้สมัคร (เฟส 9 — feedback อาจารย์ 5 ก.ย. 69 ข้อ 3)

อาจารย์: "ตอนนี้กันได้แค่โดเมนอีเมล ใครมีเมล cdti ก็เลือกสาขามั่วได้"
ทางแก้: whitelist รายชื่อจากสาขา (ไฟล์ report ที่ปรึกษาจากสำนักทะเบียน) แล้วให้
**สาขา/ชื่อ มาจากรายชื่อ ไม่ใช่จากที่ผู้สมัครพิมพ์เอง**

`users.approval_status` แยกจาก `is_active` โดยตั้งใจ — สองอย่างนี้คนละความหมาย:
  is_active=False       = แอดมินปิดบัญชีที่เคยใช้งานได้ (ลาออก/พักการเรียน)
  approval_status=pending = สมัครเข้ามาแต่ยังไม่มีใครรับรอง (ยังไม่เคยใช้งานได้เลย)
ถ้ายัดรวมเป็น is_active อย่างเดียว หน้าจอล็อกอินจะบอกว่า "บัญชีถูกปิด" ทั้งที่ความจริงคือรออนุมัติ
และแอดมินจะแยกคิว "ใครรอรับรอง" ออกจาก "ใครโดนปิด" ไม่ได้

**ไม่ปิดตายคนที่ไม่อยู่ในรายชื่อ** (นศ. ใหม่/ตกหล่น/ย้ายสาขา มีจริง) — เข้าคิวรออนุมัติแทน

Revision ID: 0037
Revises: 0036
"""
import sqlalchemy as sa
from alembic import op

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "eligible_students",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        # รหัสนักศึกษาเป็นตัวชี้เดียวที่เชื่อถือได้ — นำเข้าไฟล์ซ้ำ = อัปเดตทับรายคน ไม่ใช่เพิ่มแถวซ้ำ
        sa.Column("student_id", sa.String(20), nullable=False, unique=True, index=True),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("major", sa.String(50), nullable=True),        # comp_eng / digital_design
        sa.Column("faculty", sa.String(255), nullable=True),
        sa.Column("generation", sa.String(100), nullable=True),  # "รุ่น 631 หมู่เรียน วค."
        sa.Column("advisor", sa.String(255), nullable=True),
        # รหัสสถานะจากสำนักทะเบียน (11/12/…) — เก็บดิบไว้ ยังไม่รู้ความหมายครบ ห้ามเอามาตัดสินสิทธิ์เอง
        sa.Column("status_code", sa.String(20), nullable=True),
        sa.Column("source_file", sa.String(255), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("imported_by", sa.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    op.add_column("users", sa.Column(
        "approval_status", sa.String(20), nullable=False, server_default="approved"))
    op.add_column("users", sa.Column("approval_note", sa.Text(), nullable=True))
    op.create_index("ix_users_approval_status", "users", ["approval_status"])


def downgrade() -> None:
    op.drop_index("ix_users_approval_status", table_name="users")
    op.drop_column("users", "approval_note")
    op.drop_column("users", "approval_status")
    op.drop_table("eligible_students")
