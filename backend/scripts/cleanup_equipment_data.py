"""
Data cleanup / re-categorization ของคลังอุปกรณ์ (ทำครั้งเดียวหลัง import จาก Snipe-IT)

สคริปต์นี้ reproduce การแก้ข้อมูลที่เคยทำมือไว้เมื่อ 7 ก.ค. 2026 ให้รันซ้ำได้ (idempotent)
หลัง reset DB + import ใหม่ ให้รัน:

    cd backend && python -m scripts.cleanup_equipment_data

สิ่งที่ทำ:
1. ลบ test junk ที่ integration test เคยทิ้งไว้ (categories cat_*, equipment MULTI-*)
2. ตะกั่ว + Soldering paste → วัสดุสิ้นเปลือง, รวมเหลือชนิดละ 1 รายการ (qty รวม), หมวด "วัสดุ"
3. ชุดทดลอง Sensor (515xxx) + ชุดสมองกลฝังตัว (121xxx) → หมวด embedded
4. สร้างหมวด "TV" + ย้ายโทรทัศน์/Apple TV (351/370/352) เข้าไป
"""
import asyncio

from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.borrow_item import BorrowItem
from app.models.equipment import Equipment, equipment_category_links as L
from app.models.equipment_category import EquipmentCategory


async def _get_or_create_category(db, name: str) -> EquipmentCategory:
    cat = (await db.execute(select(EquipmentCategory).where(EquipmentCategory.name == name))).scalar_one_or_none()
    if not cat:
        cat = EquipmentCategory(name=name)
        db.add(cat)
        await db.flush()
    return cat


async def _set_only_category(db, equipment_ids: list, category_id) -> None:
    """ตั้งให้อุปกรณ์เหล่านี้อยู่ในหมวดเดียว (ลบหมวดเดิมทั้งหมดก่อน)"""
    for eid in equipment_ids:
        await db.execute(delete(L).where(L.c.equipment_id == eid))
        await db.execute(L.insert().values(equipment_id=eid, category_id=category_id))


async def delete_test_junk(db) -> None:
    cat_ids = (await db.execute(select(EquipmentCategory.id).where(EquipmentCategory.name.like("cat_%")))).scalars().all()
    eq_ids = (await db.execute(select(Equipment.id).where(Equipment.code.like("MULTI-%")))).scalars().all()
    for cid in cat_ids:
        await db.execute(delete(L).where(L.c.category_id == cid))
    for eid in eq_ids:
        await db.execute(delete(L).where(L.c.equipment_id == eid))
    await db.execute(delete(Equipment).where(Equipment.code.like("MULTI-%")))
    await db.execute(delete(EquipmentCategory).where(EquipmentCategory.name.like("cat_%")))
    print(f"1) ลบ test junk: {len(cat_ids)} categories, {len(eq_ids)} equipment")


async def merge_consumable(db, name: str, unit: str, category_id) -> None:
    """รวมอุปกรณ์ชื่อเดียวกันเป็น 1 รายการ (qty รวม), เปลี่ยนเป็น consumable + ตั้งหมวด"""
    items = (await db.execute(select(Equipment).where(Equipment.name == name).order_by(Equipment.code))).scalars().all()
    if not items:
        print(f"2) {name}: ไม่พบ (ข้าม)")
        return
    ids = [e.id for e in items]
    # ตัวหลัก = ชิ้นที่มีประวัติการยืม (กันประวัติหาย) ไม่งั้นชิ้นแรก
    with_hist = set((await db.execute(select(BorrowItem.equipment_id).where(BorrowItem.equipment_id.in_(ids)))).scalars().all())
    master = next((e for e in items if e.id in with_hist), items[0])
    others = [e for e in items if e.id != master.id]
    # ใช้ผลรวม quantity เพื่อให้ idempotent: import ใหม่ 12×1=12, รันซ้ำบนที่ merge แล้ว 1×12=12
    # (quantity_available หักของที่ยืมไปแล้วในตัวมันเอง จึงรวมตรง ๆ ได้)
    master.item_type = "consumable"
    master.unit = unit
    master.quantity_total = sum(e.quantity_total for e in items)
    master.quantity_available = sum(e.quantity_available for e in items)
    await _set_only_category(db, [master.id], category_id)
    for e in others:
        await db.execute(delete(L).where(L.c.equipment_id == e.id))
    await db.execute(delete(Equipment).where(Equipment.id.in_([e.id for e in others])))
    print(f"2) {name}: master={master.code} qty={master.quantity_total} unit={unit}, รวม/ลบ {len(others)} ชิ้น")


async def move_by_code_prefix(db, prefixes: list[str], category_id, label: str) -> None:
    ids = []
    for p in prefixes:
        ids += (await db.execute(select(Equipment.id).where(Equipment.code.like(p)))).scalars().all()
    await _set_only_category(db, ids, category_id)
    print(f"{label}: ย้าย {len(ids)} ชิ้น")


async def main() -> None:
    async with AsyncSessionLocal() as db:
        vasadu = await _get_or_create_category(db, "วัสดุ")
        embedded = await _get_or_create_category(db, "embedded")
        tv = await _get_or_create_category(db, "TV")

        await delete_test_junk(db)
        await merge_consumable(db, "ตะกั่ว", "ม้วน", vasadu.id)
        await merge_consumable(db, "Soldering paste", "กระปุก", vasadu.id)
        await move_by_code_prefix(db, ["515%"], embedded.id, "3) Sensor kit → embedded")
        await move_by_code_prefix(db, ["121%"], embedded.id, "3) Embedded kit → embedded")
        await move_by_code_prefix(db, ["351%", "370%", "352%"], tv.id, "4) TV/Apple TV → หมวด TV")

        await db.commit()
        print("เสร็จสิ้น cleanup")


if __name__ == "__main__":
    asyncio.run(main())
