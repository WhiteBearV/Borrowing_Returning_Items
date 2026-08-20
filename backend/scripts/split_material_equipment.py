"""แยกวัสดุ (material) ที่ถูกนำเข้าเป็นก้อนเดียว (quantity_total > 1) ให้เป็นรายชิ้นคนละรหัส — รันครั้งเดียว

รากบั๊กที่รายงานมา: วัสดุที่นำเข้าผ่านชีต "วัสดุ" ใน import_service.py เก็บเป็น 1 แถวเดียวที่มี
quantity_total = N ไม่มีรหัสแยกต่อชิ้น (ต่างจากครุภัณฑ์ที่ทะเบียนคณะให้มาเป็น 1 แถวต่อ 1 เลขครุภัณฑ์อยู่แล้ว)
ตัวอย่างจริงที่เจอบั๊ก: รหัส 234001 (Arduino UnoR4) เก็บเป็นแถวเดียว quantity_total=5 ทำให้ยืม 5 ชิ้น
ไม่แยกเป็น 5 รายการ ทั้งที่ borrow_service.create_request แยก BorrowItem ให้อัตโนมัติอยู่แล้วถ้ารุ่นเดียวกัน
มีหลายแถวใน DB (ดู find_group_members) — สคริปต์นี้เรียก equipment_service.split_equipment_into_units()
กับทุกแถววัสดุที่ควรแยก เพื่อให้กลไกที่มีอยู่แล้วทำงานถูกต้องโดยไม่ต้องแก้ borrow_service.py เลย

ข้ามแถวที่มีของถูกยืมอยู่ (quantity_available != quantity_total) พร้อม print รายการที่ข้าม — ไม่มีทางรู้
ย้อนหลังว่า BorrowItem ที่เปิดค้างอยู่ตอนนี้หมายถึงหน่วยไหนใน N หน่วยที่จะแยก ให้แอดมินตามไปจัดการเอง
ทีหลังตอนของคืนครบ (รายการยืมเดิมยังอ้างอิงแถวเดิม/รหัสเดิมต่อไปตามปกติ)

    python -m scripts.split_material_equipment          # รันจริง
    python -m scripts.split_material_equipment --dry    # ดูก่อนว่าจะแยกอะไรบ้าง (ไม่บันทึกอะไรลง DB)
"""
import asyncio
import sys

from fastapi import HTTPException
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.equipment import Equipment
from app.models.user import User
from app.services.equipment_service import split_equipment_into_units


async def main(dry: bool) -> None:
    async with AsyncSessionLocal() as db:
        admin = (await db.execute(
            select(User).where(User.role == "admin").order_by(User.created_at)
        )).scalars().first()
        if admin is None:
            print("ไม่พบผู้ใช้ role=admin ในระบบ — ต้องมีแอดมินอย่างน้อย 1 คนเพื่อบันทึก audit log ของการแยก")
            return

        candidates = list((await db.execute(
            select(Equipment)
            .where(Equipment.item_type == "material", Equipment.quantity_total > 1)
            .order_by(Equipment.code)
        )).scalars().all())

        split_count = skip_count = 0
        for eq in candidates:
            code, name = eq.code, eq.name  # เก็บไว้ก่อนเผื่อ session expire ค่าไปหลัง commit ของรอบก่อนหน้า
            total, available = eq.quantity_total, eq.quantity_available
            if available != total:
                borrowed = total - available
                print(f"  ข้าม {code} ({name}) — มีของถูกยืมอยู่ {borrowed}/{total} ชิ้น (รอคืนครบก่อนค่อยแยก)")
                skip_count += 1
                continue
            # เช็ค available/total ข้างบนเป็นค่าที่ preload มาตอนต้นลูป — ระหว่างวนลูปแถวก่อนหน้าอาจมีคำขอ
            # ยืมถูกอนุมัติแทรกมา (ลด quantity_available ของแถวถัดไปในลิสต์) ตัว split_equipment_into_units
            # เองจะ lock+เช็คซ้ำแบบ fresh อีกที (populate_existing race fix) แล้ว raise 400 ถ้าเจอ stale —
            # ดักไว้ตรงนี้เพื่อข้ามแถวนั้นแล้วไปต่อ ไม่ให้ 1 แถวที่ชนจังหวะทำให้ทั้งสคริปต์ abort กลางทาง
            try:
                rows = await split_equipment_into_units(db, admin, eq.id, dry=dry)
            except HTTPException as e:
                print(f"  ข้าม {code} ({name}) — {e.detail}")
                skip_count += 1
                continue
            codes = [r.code for r in rows]
            tag = "[dry-run] " if dry else ""
            print(f"  {tag}แยก {code} ({name}) x{len(codes)} → {', '.join(codes)}")
            split_count += 1

        if dry:
            await db.rollback()  # ไม่บันทึกอะไรทั้งสิ้น — ให้แอดมินตรวจผลลัพธ์ก่อนรันจริง

        tag = "[dry-run] " if dry else ""
        print(f"\n{tag}สรุป: แยกแล้ว {split_count} รุ่น · ข้าม (มีของยืมอยู่) {skip_count} รุ่น "
              f"จากทั้งหมด {len(candidates)} รุ่นที่ item_type=material และ quantity_total>1")


if __name__ == "__main__":
    asyncio.run(main("--dry" in sys.argv))
