"""วันครบกำหนดคืนรายชิ้น + สถานะอนุมัติรายชิ้น (เฟส 3 — feedback อาจารย์ 5 ก.ย. 69 ข้อ 6, 8)

อาจารย์: "ของ 3 ชิ้นในใบเดียวกันไม่จำเป็นต้องคืนพร้อมกัน" และ "ถ้าของชิ้นเดียวส่งซ่อมอยู่
ไม่ควรต้องตีกลับทั้งใบให้ยื่นใหม่" — ทั้งสองเรื่องแตะข้อมูลชุดเดียวกัน จึงย้ายวันครบกำหนด
และผลการอนุมัติลงมาอยู่ระดับ borrow_items

`borrow_requests.due_date` ยังอยู่ตามเดิม ความหมายเปลี่ยนเป็น "วันครบกำหนดล่าสุดของทั้งใบ"
(= max ของรายการที่อนุมัติ) ใช้แสดงผลรวมและ index เดิมที่ query อยู่หลายจุด

backfill: คำขอที่อนุมัติ/เสร็จสิ้นไปแล้ว = ทุกชิ้นถูกอนุมัติและใช้วันของทั้งใบ (ตรงกับพฤติกรรมเดิมเป๊ะ)
คำขอสถานะอื่นปล่อยเป็น 'pending' ตาม server_default — ใบที่ถูกปฏิเสธทั้งใบตัดสินที่ระดับใบอยู่แล้ว

Revision ID: 0031
Revises: 0030
"""
import sqlalchemy as sa
from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("borrow_items", sa.Column("requested_due_date", sa.Date(), nullable=True))
    op.add_column("borrow_items", sa.Column("due_date", sa.Date(), nullable=True))
    op.add_column("borrow_items", sa.Column("item_status", sa.String(20), nullable=False,
                                            server_default="pending"))
    op.add_column("borrow_items", sa.Column("rejection_reason", sa.Text(), nullable=True))

    op.execute("""
        UPDATE borrow_items bi
        SET item_status = 'approved',
            due_date = br.due_date,
            requested_due_date = br.requested_due_date
        FROM borrow_requests br
        WHERE bi.borrow_request_id = br.id
          AND br.status IN ('approved', 'completed')
    """)
    # คำขอที่ยังรออนุมัติ — วันที่ขอไว้ยังมีความหมาย (แอดมินจะเห็นตอนกดอนุมัติ) แต่ยังไม่มีวันครบกำหนดจริง
    op.execute("""
        UPDATE borrow_items bi
        SET requested_due_date = br.requested_due_date
        FROM borrow_requests br
        WHERE bi.borrow_request_id = br.id
          AND br.status = 'pending'
    """)


def downgrade() -> None:
    op.drop_column("borrow_items", "rejection_reason")
    op.drop_column("borrow_items", "item_status")
    op.drop_column("borrow_items", "due_date")
    op.drop_column("borrow_items", "requested_due_date")
