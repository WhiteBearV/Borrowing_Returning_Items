"""สร้างอุปกรณ์ต่อพ่วงที่ขาด + ชุด "คอมพิวเตอร์ตั้งโต๊ะ Dell Optiplex 7040" (ต่อพ่วง)

คลังมีคอมตั้งโต๊ะ 40 เครื่อง (ครุภัณฑ์แยกยูนิต) ตัวเครื่องลงทะเบียน "พร้อมอุปกรณ์" อยู่แล้ว
แต่ไม่มี เมาส์/คีย์บอร์ด/สายไฟ แยกชิ้นให้เบิกเป็นของสำรอง สคริปต์นี้เพิ่มให้ + ผูกเป็นชุด
ตัวกระตุ้น (trigger) จับคู่ตามชื่อรุ่น จึงครอบทั้ง 40 เครื่องด้วยชุดเดียว

รันซ้ำได้ (มีแล้วข้าม):
    python -m scripts.seed_desktop_bundle
"""

import asyncio

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.bundle import Bundle, BundleItem
from app.models.equipment import Equipment

DESKTOP_NAME = "คอมพิวเตอร์ตั้งโต๊ะ Dell Optiplex 7040 SFF (ST) พร้อมอุปกรณ์ (เมาส์/สายAV,VGA/คีย์บอร์ด/มอนิเตอร์)"
BUNDLE_NAME = "ชุดคอมพิวเตอร์ตั้งโต๊ะ Dell Optiplex 7040 (อุปกรณ์ต่อพ่วง)"

# อุปกรณ์ต่อพ่วงที่ขาด — material (ยืมแบบจำนวน คืนแบบ ok/damaged/lost). จำนวนตั้งใกล้จำนวนคอม
ACCESSORIES = [
    {"code": "ACC-MOUSE-001",    "name": "เมาส์ USB (ต่อพ่วงชุดคอมตั้งโต๊ะ)",       "unit": "ตัว", "qty": 40},
    {"code": "ACC-KEYBOARD-001", "name": "คีย์บอร์ด USB (ต่อพ่วงชุดคอมตั้งโต๊ะ)",    "unit": "ตัว", "qty": 40},
    {"code": "ACC-PWR-001",      "name": "สายไฟ AC คอมพิวเตอร์ (Power Cord)",       "unit": "เส้น", "qty": 40},
]


async def main() -> None:
    async with AsyncSessionLocal() as db:
        # 1) อุปกรณ์ต่อพ่วง — สร้างถ้ายังไม่มี (เช็คด้วย code)
        acc_map: dict[str, Equipment] = {}
        for a in ACCESSORIES:
            eq = (await db.execute(select(Equipment).where(Equipment.code == a["code"]))).scalar_one_or_none()
            if eq:
                print(f"  มีแล้ว: {a['code']} {a['name']}")
            else:
                eq = Equipment(
                    code=a["code"], name=a["name"], item_type="material",
                    description="อุปกรณ์ต่อพ่วงสำรองสำหรับชุดคอมพิวเตอร์ตั้งโต๊ะ",
                    unit=a["unit"], quantity_total=a["qty"], quantity_available=a["qty"],
                    low_stock_threshold=5, status="available", is_borrowable=True,
                )
                db.add(eq)
                await db.flush()
                print(f"  + สร้าง: {a['code']} {a['name']} (x{a['qty']} {a['unit']})")
            acc_map[a["code"]] = eq

        # 2) หาคอมตั้งโต๊ะไว้เป็น trigger (ยูนิตไหนก็ได้ — จับคู่ตามชื่อครอบทั้ง 40 เครื่อง)
        desktop = (await db.execute(
            select(Equipment).where(Equipment.name == DESKTOP_NAME).order_by(Equipment.code).limit(1)
        )).scalar_one_or_none()
        if not desktop:
            raise SystemExit(f"ไม่พบคอมตั้งโต๊ะชื่อ: {DESKTOP_NAME}")

        # 3) ชุด — สร้างถ้ายังไม่มี (เช็คด้วยชื่อชุด)
        bundle = (await db.execute(select(Bundle).where(Bundle.name == BUNDLE_NAME))).scalar_one_or_none()
        if bundle:
            print(f"  มีชุดแล้ว: {BUNDLE_NAME} — อัปเดต trigger/items")
            bundle.items.clear()
            await db.flush()
        else:
            bundle = Bundle(name=BUNDLE_NAME, description="กดเพิ่มคอมตั้งโต๊ะแล้วได้เมาส์/คีย์บอร์ด/สายไฟ อัตโนมัติ",
                            is_active=True)
            db.add(bundle)
            print(f"  + สร้างชุด: {BUNDLE_NAME}")

        bundle.trigger_equipment_id = desktop.id
        for a in ACCESSORIES:
            bundle.items.append(BundleItem(equipment_id=acc_map[a["code"]].id, quantity=1))

        await db.commit()
        print(f"เสร็จ — trigger = {desktop.code} ({desktop.name[:30]}…), ต่อพ่วง {len(ACCESSORIES)} รายการ")


if __name__ == "__main__":
    asyncio.run(main())
