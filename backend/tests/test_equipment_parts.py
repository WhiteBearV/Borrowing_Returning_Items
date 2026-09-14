"""ชิ้นส่วน/การอัพเกรด — อายุของเครื่องหลักกับของชิ้นส่วนต้องแยกจากกัน

โจทย์จากอาจารย์: อัพเกรด RAM 8→16GB บนครุภัณฑ์เลขเดิม ต้องเก็บการเปลี่ยนแปลงนั้นไว้
และตัดสินใจเรื่องการให้ยืมจากอายุที่แยกกันได้

หมายเหตุ: conftest.py มี PYTEST_ALLOW_DB=1 รันใส่ DB dev จริง — ทุกเทสต้อง cleanup ใน finally เสมอ
"""
import uuid
from datetime import date, timedelta

from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.equipment import Equipment
from app.models.equipment_part import EquipmentPart
from tests.conftest import auth

OLD_DATE = "2020-06-05"


async def _make(client: AsyncClient, h: dict, name: str) -> dict:
    r = await client.post("/equipment", json={
        "code": f"{uuid.uuid4().int % 10**15:015d}", "name": name,
        "category_ids": [], "item_type": "durable", "quantity_total": 1,
        "image_urls": ["/uploads/test.jpg"], "unit_value": 25000, "acquired_at": OLD_DATE,
    }, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


async def _cleanup(name: str) -> None:
    async with AsyncSessionLocal() as db:
        eq_ids = (await db.execute(select(Equipment.id).where(Equipment.name == name))).scalars().all()
        if eq_ids:
            await db.execute(delete(EquipmentPart).where(EquipmentPart.equipment_id.in_(eq_ids)))
            await db.execute(delete(AuditLog).where(AuditLog.target_id.in_(eq_ids)))
            await db.execute(delete(Equipment).where(Equipment.id.in_(eq_ids)))
        await db.commit()


async def test_install_part_keeps_main_equipment_age_and_value_untouched(client: AsyncClient, admin_token: str):
    """หัวใจของฟีเจอร์นี้ — ติดตั้ง RAM ใหม่ต้องไม่ทำให้เครื่องหลักดูเหมือนเพิ่งได้มาหรือราคาเปลี่ยน"""
    h = auth(admin_token)
    name = f"โน้ตบุ๊คทดสอบชิ้นส่วน {uuid.uuid4().hex[:6]}"
    try:
        eq = await _make(client, h, name)
        installed = date.today().isoformat()
        r = await client.post(f"/equipment/{eq['id']}/parts", json={
            "name": "RAM DDR4 16GB", "unit_value": 1800, "acquired_at": installed,
        }, headers=h)
        assert r.status_code == 201, r.text
        part = r.json()
        assert part["is_installed"] is True
        assert part["acquired_at"] == installed
        # ชิ้นส่วนเพิ่งติดตั้ง → มูลค่าตามบัญชียังเต็ม, เครื่องหลักอายุ 5 ปีกว่า → เหลือมูลค่าซาก
        assert part["book_value"] == 1800.0

        after = (await client.get(f"/equipment/{eq['id']}", headers=h)).json()
        assert after["acquired_at"] == OLD_DATE, "อายุเครื่องหลักต้องไม่ถูกแตะ"
        assert after["unit_value"] == 25000, "ราคาเครื่องหลักต้องไม่ถูกแตะ"
        assert after["book_value"] != part["book_value"], "อายุ/มูลค่าของสองอย่างต้องคิดแยกกัน"
    finally:
        await _cleanup(name)


async def test_remove_part_keeps_history_and_blocks_double_removal(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    name = f"โน้ตบุ๊คทดสอบถอดชิ้นส่วน {uuid.uuid4().hex[:6]}"
    try:
        eq = await _make(client, h, name)
        part = (await client.post(f"/equipment/{eq['id']}/parts", json={
            "name": "RAM DDR4 8GB (เดิม)", "unit_value": 900, "acquired_at": OLD_DATE,
        }, headers=h)).json()

        r = await client.post(f"/equipment/{eq['id']}/parts/{part['id']}/remove",
                              json={"reason": "อัพเกรดเป็น 16GB"}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["is_installed"] is False
        assert r.json()["removed_reason"] == "อัพเกรดเป็น 16GB"
        assert r.json()["removed_at"] == date.today().isoformat()

        # ถอดซ้ำไม่ได้
        r2 = await client.post(f"/equipment/{eq['id']}/parts/{part['id']}/remove",
                               json={"reason": "ถอดซ้ำ"}, headers=h)
        assert r2.status_code == 400, r2.text

        # แถวยังอยู่เป็นประวัติ ไม่ถูกลบทิ้ง
        listed = (await client.get(f"/equipment/{eq['id']}/parts", headers=h)).json()
        assert [p["id"] for p in listed] == [part["id"]]
        active = (await client.get(f"/equipment/{eq['id']}/parts",
                                   params={"include_removed": False}, headers=h)).json()
        assert active == []
    finally:
        await _cleanup(name)


async def test_part_history_shows_up_in_equipment_timeline(client: AsyncClient, admin_token: str):
    """ติดตั้ง/ถอดชิ้นส่วนต้องโผล่ในประวัติของ "เครื่องหลัก" ไม่ใช่ผูกกับ id ของชิ้นส่วนจนหาไม่เจอ"""
    h = auth(admin_token)
    name = f"โน้ตบุ๊คทดสอบประวัติชิ้นส่วน {uuid.uuid4().hex[:6]}"
    try:
        eq = await _make(client, h, name)
        part = (await client.post(f"/equipment/{eq['id']}/parts", json={
            "name": "SSD NVMe 512GB", "unit_value": 2400, "acquired_at": OLD_DATE,
        }, headers=h)).json()
        await client.post(f"/equipment/{eq['id']}/parts/{part['id']}/remove",
                          json={"reason": "เปลี่ยนเป็น 1TB"}, headers=h)

        logs = (await client.get("/audit-logs", params={"target_id": eq["id"], "page_size": 50}, headers=h)).json()
        actions = [l["action"] for l in logs["items"]]
        assert "install_part" in actions and "remove_part" in actions
        install = next(l for l in logs["items"] if l["action"] == "install_part")
        assert install["detail"]["part_name"] == "SSD NVMe 512GB"
    finally:
        await _cleanup(name)


async def test_update_part_records_diff(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    name = f"โน้ตบุ๊คทดสอบแก้ชิ้นส่วน {uuid.uuid4().hex[:6]}"
    try:
        eq = await _make(client, h, name)
        part = (await client.post(f"/equipment/{eq['id']}/parts", json={
            "name": "RAM 16GB", "unit_value": 1800, "acquired_at": OLD_DATE,
        }, headers=h)).json()
        r = await client.patch(f"/equipment/{eq['id']}/parts/{part['id']}",
                               json={"unit_value": 2000}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["unit_value"] == 2000

        logs = (await client.get("/audit-logs",
                                 params={"target_id": eq["id"], "action": "update_part"}, headers=h)).json()
        assert logs["items"][0]["detail"]["changes"]["unit_value"] == [1800.0, 2000.0]
    finally:
        await _cleanup(name)


async def test_part_of_another_equipment_is_not_reachable(client: AsyncClient, admin_token: str):
    """แก้ชิ้นส่วนข้ามเครื่องผ่าน URL ที่เดาเอาไม่ได้"""
    h = auth(admin_token)
    n1 = f"เครื่อง A ชิ้นส่วน {uuid.uuid4().hex[:6]}"
    n2 = f"เครื่อง B ชิ้นส่วน {uuid.uuid4().hex[:6]}"
    try:
        a = await _make(client, h, n1)
        b = await _make(client, h, n2)
        part = (await client.post(f"/equipment/{a['id']}/parts", json={
            "name": "RAM 16GB", "acquired_at": OLD_DATE,
        }, headers=h)).json()
        r = await client.patch(f"/equipment/{b['id']}/parts/{part['id']}", json={"name": "แอบแก้"}, headers=h)
        assert r.status_code == 404, r.text
    finally:
        await _cleanup(n1)
        await _cleanup(n2)


async def test_students_cannot_change_parts(client: AsyncClient, admin_token: str, student_token: str):
    h, hs = auth(admin_token), auth(student_token)
    name = f"เครื่องทดสอบสิทธิ์ชิ้นส่วน {uuid.uuid4().hex[:6]}"
    try:
        eq = await _make(client, h, name)
        r = await client.post(f"/equipment/{eq['id']}/parts",
                              json={"name": "RAM", "acquired_at": OLD_DATE}, headers=hs)
        assert r.status_code == 403, r.text
        # แต่ดูได้ (หน้ารายละเอียดอุปกรณ์ฝั่งนักศึกษาแสดงสเปกได้)
        assert (await client.get(f"/equipment/{eq['id']}/parts", headers=hs)).status_code == 200
    finally:
        await _cleanup(name)
