"""ย้ายใบยืมที่เซ็นแล้วไปโฟลเดอร์ที่ตรวจสิทธิ์ (เฟส 7 — feedback อาจารย์ 5 ก.ย. 69 ข้อ 16)

ของเดิม (migration 0033) เก็บไฟล์ไว้ใน /uploads ซึ่ง main.py mount เป็น StaticFiles แบบไม่มี auth
= เอกสารที่มี **ลายเซ็น + ชื่อ + รหัสประจำตัวนักศึกษา** เปิดได้ด้วย URL เปล่าโดยไม่ต้องล็อกอิน (ผิด PDPA)

เปลี่ยนความหมายของคอลัมน์: เดิมเก็บ URL สาธารณะ (`/uploads/xxx.pdf`) → ตอนนี้เก็บ **ชื่อไฟล์เปล่า**
ในโฟลเดอร์ PRIVATE_UPLOAD_DIR ที่เปิดได้ทาง GET /borrow-requests/{id}/signed-form เท่านั้น
จึงเปลี่ยนชื่อคอลัมน์ตามไปด้วย (`signed_form_url` → `signed_form_file`) — คอลัมน์ชื่อ `_url`
ที่ข้างในเป็นชื่อไฟล์คือกับดักที่ทำให้คนถัดไปเอาไปแปะเป็นลิงก์ตรงอีกรอบ

แถวเก่า (ถ้ามี) ตัด prefix `/uploads/` ออกให้ — ไฟล์จริงต้องย้ายด้วยมือถ้าเคยมีคนอัปไว้แล้ว
(ตอนเขียน migration นี้ยังไม่มีแถวไหนในระบบใช้งานจริงเลย ฟีเจอร์เพิ่งลงเมื่อ 7 ก.ย.)

Revision ID: 0035
Revises: 0034
"""
import sqlalchemy as sa
from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("borrow_requests", "signed_form_url", new_column_name="signed_form_file")
    op.execute(
        "UPDATE borrow_requests SET signed_form_file = regexp_replace(signed_form_file, '^.*/', '') "
        "WHERE signed_form_file IS NOT NULL"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE borrow_requests SET signed_form_file = '/uploads/' || signed_form_file "
        "WHERE signed_form_file IS NOT NULL"
    )
    op.alter_column("borrow_requests", "signed_form_file", new_column_name="signed_form_url")
