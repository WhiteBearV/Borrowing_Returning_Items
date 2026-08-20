"""ล้างผลการทดสอบ "นำเข้าจาก Excel" — ดึงคลังกลับให้ตรงทะเบียนจริง

ใช้เมื่อทดสอบนำเข้าด้วยไฟล์ทดสอบแล้วอยากเริ่มใหม่:
  - ลบครุภัณฑ์ที่ไม่มีในทะเบียนจริง (ของปลอมจากไฟล์ทดสอบ) พร้อม audit log ของมัน
  - ดึง status/location ของครุภัณฑ์ที่เหลือกลับไปตามทะเบียนจริง (เช่น ที่ถูก mark ชำรุดตอนทดสอบ)

ไม่แตะวัสดุ (material/consumable) และไม่แตะของที่มีประวัติการยืม

Usage:
    python backend/scripts/reset_test_import.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import delete, select  # noqa: E402

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.models.audit_log import AuditLog  # noqa: E402
from app.models.borrow_item import BorrowItem  # noqa: E402
from app.models.equipment import Equipment  # noqa: E402
from app.services.import_service import parse_workbook  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REGISTER = os.path.join(
    ROOT, "docs",
    "รายงานทะเบียนคุมทรัพย์สิน - คณะเทคโนโลยีดิจิทัล ข้อมูล ณ วันที่ 4 พฤศจิกายน 2568.xlsx",
)


async def main() -> None:
    rows, _, _ = parse_workbook(REGISTER)
    register = {r["code"]: r for r in rows}

    async with AsyncSessionLocal() as db:
        durables = (await db.execute(
            select(Equipment).where(Equipment.item_type == "durable")
        )).scalars().all()

        deleted = restored = 0
        for eq in durables:
            ref = register.get(eq.code)
            if ref is None:
                # ของที่ไม่มีในทะเบียนจริง = ของที่ทดสอบเพิ่มเข้ามา — ลบทิ้ง (ถ้าไม่เคยถูกยืม)
                borrowed = (await db.execute(
                    select(BorrowItem.id).where(BorrowItem.equipment_id == eq.id).limit(1)
                )).scalar_one_or_none()
                if borrowed:
                    print(f"ข้าม {eq.code} — มีประวัติการยืม")
                    continue
                await db.execute(delete(AuditLog).where(AuditLog.target_id == eq.id))
                await db.delete(eq)
                deleted += 1
                continue

            if eq.status != ref["status"] or eq.location != ref["location"]:
                eq.status = ref["status"]
                eq.location = ref["location"]
                eq.quantity_available = ref["quantity_available"]
                restored += 1

        await db.commit()

    print(f"ลบของทดสอบ {deleted} รายการ · ดึงสถานะ/สถานที่กลับตามทะเบียน {restored} รายการ")


if __name__ == "__main__":
    asyncio.run(main())
