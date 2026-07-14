"""จัดหมวดวัสดุใหม่ตามรหัส 2 หลักแรก (หมวดวัสดุ) — รันครั้งเดียวกับข้อมูลที่ import ไปแล้ว

ของเดิมจัดหมวดจากคีย์เวิร์ดในชื่อ ทำให้วัสดุเกือบทั้งหมดกองอยู่หมวดเดียว
ทะเบียนวัสดุจริงใช้ 2 หลักแรกของรหัสเป็นหมวดอยู่แล้ว (21/22/23=บอร์ด, 34/35/36=อิเล็กทรอนิกส์, ...)

    python -m scripts.recategorize_material          # รันจริง
    python -m scripts.recategorize_material --dry    # ดูก่อนว่าจะเปลี่ยนอะไร
"""

import asyncio
import sys
import uuid

from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.services.import_service import MATERIAL_CAT_BY_PREFIX


async def main(dry: bool) -> None:
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(text(
            "SELECT id, code, name FROM equipment WHERE item_type IN ('material', 'consumable')"
        ))).all()

        cats: dict[str, uuid.UUID] = {
            n: i for i, n in (await db.execute(text("SELECT id, name FROM equipment_categories"))).all()
        }
        changed = 0
        for eq_id, code, name in rows:
            cat_name = MATERIAL_CAT_BY_PREFIX.get((code or "")[:2])
            if not cat_name:
                print(f"  ข้าม (ไม่รู้หมวด): {code} {name}")
                continue
            if cat_name not in cats:
                cid = uuid.uuid4()
                if not dry:
                    await db.execute(text("INSERT INTO equipment_categories (id, name) VALUES (:i, :n)"),
                                     {"i": cid, "n": cat_name})
                cats[cat_name] = cid
            if not dry:
                await db.execute(text("DELETE FROM equipment_category_links WHERE equipment_id = :e"),
                                 {"e": eq_id})
                await db.execute(text(
                    "INSERT INTO equipment_category_links (equipment_id, category_id) VALUES (:e, :c)"
                ), {"e": eq_id, "c": cats[cat_name]})
            changed += 1

        if dry:
            await db.rollback()
        else:
            # ลบหมวดที่ไม่เหลือของอยู่แล้ว ไม่ให้ค้างใน dropdown ตัวกรอง
            await db.execute(text(
                "DELETE FROM equipment_categories c WHERE NOT EXISTS "
                "(SELECT 1 FROM equipment_category_links l WHERE l.category_id = c.id)"
            ))
            await db.commit()
        print(f"{'[dry-run] ' if dry else ''}จัดหมวดใหม่ {changed}/{len(rows)} รายการ")


if __name__ == "__main__":
    asyncio.run(main("--dry" in sys.argv))
