"""เซ็นรับของบนหน้าจอ + บันทึกการจ่ายของ (เฟส 11 — 23 ก.ย. 69)

เดิมระบบข้ามจาก "อนุมัติ" ไป "รับคืน" เลย ไม่มีบันทึกว่าของถูกส่งมอบจริงเมื่อไหร่ ใครเป็นคนจ่าย และผู้ยืม
ยืนยันการรับของอย่างไร — ทางเดียวคือปริ้นใบยืมไปเซ็นแล้วถ่ายรูปอัปโหลดกลับ (ช้าและได้ไฟล์ไม่คงที่)

borrow_requests เพิ่ม:
- handover_at / handover_by  : จ่ายของเมื่อไหร่ เจ้าหน้าที่คนไหนเป็นคนจ่าย
- handover_sig_borrower / handover_sig_staff : ชื่อไฟล์ลายเซ็น PNG ใน PRIVATE_UPLOAD_DIR (**ชื่อไฟล์เปล่า
  ไม่ใช่ URL** เหมือน signed_form_file — เปิดได้ทางเดียวคือ endpoint ที่ตรวจสิทธิ์)
- return_sig_borrower / return_sig_staff : ลายเซ็นตอนรับคืน (ผู้คืน / ผู้รับคืน)
- signature_meta (JSONB) : หลักฐานประกอบต่อการเซ็นแต่ละครั้ง — เวลา ผู้ใช้ที่เกี่ยวข้อง user-agent และ
  sha256 ของไฟล์ เพื่อให้พิสูจน์ได้ว่าไฟล์ไม่ถูกสลับภายหลัง

**ไม่แตะสต็อกและไม่เพิ่มค่าใน status** — สต็อกยังตัดตอนอนุมัติตามกฎเดิมใน CLAUDE.md การจ่ายของเป็นเพียง
บันทึกการส่งมอบ ไม่ใช่สถานะใหม่ จึงไม่กระทบ _all_settled / ค่าปรับ / ตัวนับใด ๆ

Revision ID: 0042
Revises: 0041
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None

_SIG_COLUMNS = (
    "handover_sig_borrower",
    "handover_sig_staff",
    "return_sig_borrower",
    "return_sig_staff",
)


def upgrade() -> None:
    op.add_column("borrow_requests", sa.Column("handover_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("borrow_requests", sa.Column("handover_by", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_borrow_requests_handover_by", "borrow_requests", "users",
                          ["handover_by"], ["id"], ondelete="SET NULL")
    for col in _SIG_COLUMNS:
        op.add_column("borrow_requests", sa.Column(col, sa.String(length=500), nullable=True))
    op.add_column("borrow_requests",
                  sa.Column("signature_meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column("borrow_requests", "signature_meta")
    for col in _SIG_COLUMNS:
        op.drop_column("borrow_requests", col)
    op.drop_constraint("fk_borrow_requests_handover_by", "borrow_requests", type_="foreignkey")
    op.drop_column("borrow_requests", "handover_by")
    op.drop_column("borrow_requests", "handover_at")
