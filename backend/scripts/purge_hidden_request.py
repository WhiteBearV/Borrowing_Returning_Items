"""
ลบประวัติการยืม "ถาวร" — ทางเดียวที่เหลือหลังปุ่มลบบนเว็บเปลี่ยนเป็นซ่อน (24 ก.ย. 69 — SKGRent ข้อ 3)

ลบได้เฉพาะคำขอที่ถูกซ่อนผ่านหน้าเว็บมาก่อนแล้วเท่านั้น (มี audit "hide_request" พร้อมเหตุผลอยู่แล้ว)
ตั้งใจให้ต้องเข้าเครื่องเซิร์ฟเวอร์ ไม่มี endpoint — กันการลบประวัติเพื่อกลบเรื่องจากหน้าเว็บ
audit_logs ไม่ถูกลบ (เลขคำขอยังค้นเจอในหน้า Audit)

    python scripts/purge_hidden_request.py REQ-2026-6610301006-a1b2c3 [REQ-...]

รันใน docker:
    docker compose -f docker-compose.prod.yml exec backend python scripts/purge_hidden_request.py REQ-...
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.borrow_item import BorrowItem
from app.models.borrow_request import BorrowRequest
from app.models.notification import Notification


async def purge(codes: list[str]) -> None:
    async with AsyncSessionLocal() as db:
        for code in codes:
            req = (await db.execute(
                select(BorrowRequest).where(BorrowRequest.request_code == code)
                .execution_options(include_deleted=True)
            )).scalar_one_or_none()
            if not req:
                print(f"ไม่พบ {code}")
                continue
            if req.deleted_at is None:
                print(f"ข้าม {code} — ยังไม่ถูกซ่อน (ต้องกดลบในหน้าเว็บพร้อมเหตุผลก่อน)")
                continue
            await db.execute(delete(Notification).where(Notification.borrow_request_id == req.id))
            await db.execute(delete(BorrowItem).where(BorrowItem.borrow_request_id == req.id))
            await db.execute(delete(BorrowRequest).where(BorrowRequest.id == req.id))
            print(f"ลบถาวร {code} (ซ่อนไว้เมื่อ {req.deleted_at:%Y-%m-%d} เหตุผล: {req.delete_reason})")
        await db.commit()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    asyncio.run(purge(sys.argv[1:]))
