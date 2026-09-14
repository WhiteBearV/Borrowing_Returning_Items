"""เก็บระดับสิทธิ์ของผู้ทำลงใน audit_logs (snapshot เหมือน actor_name/actor_identifier)

feedback อาจารย์ 5 ก.ย. 69: log ต้องครบทุกการกระทำและอ่านรู้เรื่องว่า "ใคร" ทำ — พอเริ่มบันทึก
การกระทำฝั่งนักศึกษาด้วย (ยื่นคำขอ/ยกเลิก/ขอคืน/ขอต่อเวลา) การรู้แค่ชื่อไม่พอ ต้องรู้ด้วยว่าคนนั้น
ทำในฐานะอะไร และต้องเป็น snapshot เพราะ role ของบัญชีเปลี่ยนได้ภายหลัง (นศ. → ผู้ดูแลคลัง)
ประวัติต้องบอกสิทธิ์ ณ ตอนที่ทำ ไม่ใช่สิทธิ์ปัจจุบัน

nullable เพราะแถวเก่าก่อน migration นี้ไม่มีข้อมูล — backfill ไม่ได้ด้วย เพราะ role ปัจจุบันของ
บัญชีอาจไม่ใช่ role ตอนนั้น การเดาย้อนหลังจะทำให้ audit log โกหก

Revision ID: 0029
Revises: 0028
"""
import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("audit_logs", sa.Column("actor_role", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("audit_logs", "actor_role")
