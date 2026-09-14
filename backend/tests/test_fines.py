"""ค่าปรับล่าช้า + ค่าเสียหาย (เฟส 6 — feedback อาจารย์ 5 ก.ย. 69 ข้อ 7)

จุดที่ต้องไม่พังเด็ดขาด:
- ยอดถูก freeze ตอนรับคืน — แก้อัตราใน settings ทีหลังแล้วยอดของเคสเก่า **ต้องไม่ขยับ**
- ค่าเสียหายคิดจาก book_value_snapshot (มูลค่าตามบัญชี ณ วันอนุมัติ) ไม่ใช่ราคาที่ซื้อ
- ยกเว้นค่าปรับได้เฉพาะ superadmin (เกี่ยวกับเงิน) ส่วนแอดมินคลังบันทึกชำระ/แก้ยอดได้
"""
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.borrow_item import BorrowItem
from app.models.borrow_request import BorrowRequest
from app.models.equipment import Equipment
from app.models.notification import Notification
from app.models.setting import Setting
from app.models.user import User
from app.services import borrow_service
from tests.conftest import auth

FINE_SETTINGS = {"fine_per_day_per_item": "10", "fine_grace_days": "0", "fine_max_per_item": "0"}


@pytest_asyncio.fixture(loop_scope="session")
async def fine_equipment():
    """ครุภัณฑ์ราคา 1,000 ได้มาวันนี้ (ยังไม่เสื่อม) → มูลค่าตามบัญชี = 1,000 เต็ม"""
    eq_id = uuid.uuid4()
    async with AsyncSessionLocal() as db:
        db.add(Equipment(
            id=eq_id, code=f"TEST-FINE-{eq_id.hex[:6].upper()}", name="อุปกรณ์ทดสอบค่าปรับ",
            item_type="durable", quantity_total=1, quantity_available=1, status="available",
            unit_value=1000, acquired_at=date.today(), useful_life_years=5,
        ))
        await db.commit()
    yield eq_id
    async with AsyncSessionLocal() as db:
        req_ids = (await db.execute(
            select(BorrowItem.borrow_request_id).where(BorrowItem.equipment_id == eq_id)
        )).scalars().all()
        item_ids = (await db.execute(
            select(BorrowItem.id).where(BorrowItem.equipment_id == eq_id)
        )).scalars().all()
        # audit_logs ของเทสต้องเก็บกวาดเอง — ลบ user ไม่ลบ log ตาม (ตั้งใจ) แล้ว actor_id กลาย NULL
        # ตามเก็บทีหลังไม่ได้ ขยะจะค้างถาวรใน DB dev ที่มีคนอื่นใช้ร่วม
        for ids in (req_ids, item_ids):
            if ids:
                await db.execute(delete(AuditLog).where(AuditLog.target_id.in_(ids)))
        if req_ids:
            await db.execute(delete(Notification).where(Notification.borrow_request_id.in_(req_ids)))
        await db.execute(delete(BorrowItem).where(BorrowItem.equipment_id == eq_id))
        if req_ids:
            await db.execute(delete(BorrowRequest).where(BorrowRequest.id.in_(req_ids)))
        await db.execute(delete(Equipment).where(Equipment.id == eq_id))
        await db.commit()


@pytest_asyncio.fixture(loop_scope="session", autouse=True)
async def reset_fine_settings():
    """คืนอัตราค่าปรับกลับค่ามาตรฐานทุกครั้ง — เทสข้อ "แก้อัตราแล้วยอดเก่าไม่ขยับ" แก้ค่าจริงใน DB"""
    yield
    async with AsyncSessionLocal() as db:
        for key, value in FINE_SETTINGS.items():
            row = (await db.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
            if row:
                row.value = value
        await db.commit()


async def _set_setting(key: str, value: str) -> None:
    async with AsyncSessionLocal() as db:
        row = (await db.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
        if row:
            row.value = value
        else:
            db.add(Setting(key=key, value=value))
        await db.commit()


async def _borrowed_item(student: User, admin: User, eq_id: uuid.UUID,
                         days_late: int) -> tuple[uuid.UUID, uuid.UUID]:
    """สร้างคำขอที่อนุมัติแล้ว 1 ชิ้น โดยกำหนดคืนอยู่ในอดีต `days_late` วัน (0 = ครบกำหนดวันนี้)"""
    req_id, item_id = uuid.uuid4(), uuid.uuid4()
    async with AsyncSessionLocal() as db:
        db.add(BorrowRequest(
            id=req_id, request_code=f"REQ-FINE-{req_id.hex[:6]}", student_id=student.id,
            status="pending", purpose="ทดสอบค่าปรับ", requested_due_date=date(2099, 1, 1),
        ))
        db.add(BorrowItem(id=item_id, borrow_request_id=req_id, equipment_id=eq_id,
                          item_type_snapshot="durable", quantity=1))
        await db.commit()
    async with AsyncSessionLocal() as db:
        await borrow_service.approve_request(db, await db.get(User, admin.id), req_id)
    async with AsyncSessionLocal() as db:
        item = await db.get(BorrowItem, item_id)
        item.due_date = date.today() - timedelta(days=days_late)
        await db.commit()
    return req_id, item_id


@pytest.mark.asyncio(loop_scope="session")
async def test_late_return_records_fine_and_freezes_it(
    client: AsyncClient, admin_token: str, test_admin: User, test_student: User, fine_equipment,
):
    """คืนช้า 5 วัน → 50 บาท และยอดต้องไม่ขยับเมื่อแอดมินแก้อัตราค่าปรับทีหลัง"""
    req_id, item_id = await _borrowed_item(test_student, test_admin, fine_equipment, days_late=5)

    r = await client.post(f"/borrow-requests/{req_id}/items/{item_id}/return",
                          json={"condition_on_return": "ok"}, headers=auth(admin_token))
    assert r.status_code == 200, r.text

    async with AsyncSessionLocal() as db:
        item = await db.get(BorrowItem, item_id)
        assert item.fine_days_late == 5
        assert float(item.fine_late_amount) == 50.0
        assert float(item.fine_damage_amount) == 0.0
        assert item.fine_status == "unpaid"
        assert item.fine_basis["rate_per_day"] == 10.0

    # อัตราขึ้นเป็น 100 บาท/วัน — ยอดของเคสที่ปิดไปแล้วต้องคงเดิม ไม่งั้นเถียงกับผู้ถูกปรับไม่ได้
    await _set_setting("fine_per_day_per_item", "100")
    async with AsyncSessionLocal() as db:
        item = await db.get(BorrowItem, item_id)
        assert float(item.fine_late_amount) == 50.0, "ยอดที่ freeze ไว้ต้องไม่ขยับตาม settings"


@pytest.mark.asyncio(loop_scope="session")
async def test_on_time_return_has_no_fine(
    client: AsyncClient, admin_token: str, test_admin: User, test_student: User, fine_equipment,
):
    req_id, item_id = await _borrowed_item(test_student, test_admin, fine_equipment, days_late=0)
    r = await client.post(f"/borrow-requests/{req_id}/items/{item_id}/return",
                          json={"condition_on_return": "ok"}, headers=auth(admin_token))
    assert r.status_code == 200, r.text
    async with AsyncSessionLocal() as db:
        item = await db.get(BorrowItem, item_id)
        assert item.fine_days_late == 0 and item.fine_status == "none"


@pytest.mark.asyncio(loop_scope="session")
async def test_grace_days_and_cap(
    client: AsyncClient, admin_token: str, test_admin: User, test_student: User, fine_equipment,
):
    """ผ่อนผัน 3 วัน + เพดาน 15 บาท → ช้า 10 วัน คิด 7 วัน = 70 แต่ถูกตัดเหลือ 15"""
    await _set_setting("fine_grace_days", "3")
    await _set_setting("fine_max_per_item", "15")
    req_id, item_id = await _borrowed_item(test_student, test_admin, fine_equipment, days_late=10)

    r = await client.post(f"/borrow-requests/{req_id}/items/{item_id}/return",
                          json={"condition_on_return": "ok"}, headers=auth(admin_token))
    assert r.status_code == 200, r.text
    async with AsyncSessionLocal() as db:
        item = await db.get(BorrowItem, item_id)
        assert item.fine_days_late == 7
        assert float(item.fine_late_amount) == 15.0


@pytest.mark.asyncio(loop_scope="session")
async def test_damaged_item_charges_book_value(
    client: AsyncClient, admin_token: str, test_admin: User, test_student: User, fine_equipment,
):
    """ของเสียหาย → คิดจากมูลค่าตามบัญชี ณ วันอนุมัติ (ของใหม่วันนี้ = ราคาเต็ม 1,000)"""
    req_id, item_id = await _borrowed_item(test_student, test_admin, fine_equipment, days_late=2)

    r = await client.post(
        f"/borrow-requests/{req_id}/items/{item_id}/return",
        json={"condition_on_return": "damaged", "damage_photo_urls": ["/uploads/x.jpg"]},
        headers=auth(admin_token),
    )
    assert r.status_code == 200, r.text
    async with AsyncSessionLocal() as db:
        item = await db.get(BorrowItem, item_id)
        assert float(item.fine_damage_amount) == 1000.0
        assert float(item.fine_late_amount) == 20.0
        assert item.fine_basis["book_value_used"] == 1000.0


@pytest.mark.asyncio(loop_scope="session")
async def test_admin_can_override_amount_on_return(
    client: AsyncClient, admin_token: str, test_admin: User, test_student: User, fine_equipment,
):
    """แอดมินกรอกยอดทับตอนรับคืนได้ (ของเสียหายบางส่วน) แต่ยอดที่ระบบคิดต้องยังอยู่ใน basis"""
    req_id, item_id = await _borrowed_item(test_student, test_admin, fine_equipment, days_late=3)

    r = await client.post(
        f"/borrow-requests/{req_id}/items/{item_id}/return",
        json={"condition_on_return": "damaged", "damage_photo_urls": ["/uploads/x.jpg"],
              "fine_damage_amount_override": 250},
        headers=auth(admin_token),
    )
    assert r.status_code == 200, r.text
    async with AsyncSessionLocal() as db:
        item = await db.get(BorrowItem, item_id)
        assert float(item.fine_damage_amount) == 250.0
        assert item.fine_basis["computed_damage_amount"] == 1000.0


@pytest.mark.asyncio(loop_scope="session")
async def test_pay_edit_and_waive_permissions(
    client: AsyncClient, admin_token: str, superadmin_token: str, student_token: str,
    test_admin: User, test_student: User, fine_equipment,
):
    """แก้ยอด/บันทึกชำระ = เจ้าหน้าที่ · ยกเว้น = superadmin เท่านั้น · ปิดงานแล้วแก้ต่อไม่ได้"""
    req_id, item_id = await _borrowed_item(test_student, test_admin, fine_equipment, days_late=4)
    await client.post(f"/borrow-requests/{req_id}/items/{item_id}/return",
                      json={"condition_on_return": "ok"}, headers=auth(admin_token))
    base = f"/borrow-requests/{req_id}/items/{item_id}/fine"

    assert (await client.patch(base, json={"late_amount": 1, "damage_amount": 0, "reason": "x"},
                               headers=auth(student_token))).status_code == 403
    # แก้ยอดต้องมีเหตุผลเสมอ (ตัวเลขที่เรียกเงิน ต้องตรวจย้อนหลังได้)
    assert (await client.patch(base, json={"late_amount": 20, "damage_amount": 0},
                               headers=auth(admin_token))).status_code == 422

    r = await client.patch(base, json={"late_amount": 20, "damage_amount": 0, "reason": "เจรจาลดหย่อน"},
                           headers=auth(admin_token))
    assert r.status_code == 200, r.text

    # ยกเว้น: แอดมินคลังทำไม่ได้ ต้องเป็น superadmin
    assert (await client.patch(f"{base}/waive", json={"reason": "อาจารย์อนุมัติ"},
                               headers=auth(admin_token))).status_code == 403
    r = await client.patch(f"{base}/waive", json={"reason": "อาจารย์อนุมัติ"},
                           headers=auth(superadmin_token))
    assert r.status_code == 200, r.text

    async with AsyncSessionLocal() as db:
        item = await db.get(BorrowItem, item_id)
        assert item.fine_status == "waived"
        assert float(item.fine_late_amount) == 20.0, "ยกเว้นแล้วยอดเดิมต้องยังอยู่ (รายงานต้องรู้ว่ายกไปเท่าไหร่)"
        assert item.fine_waived_reason == "อาจารย์อนุมัติ"

    # ยกเว้นแล้วเป็นสถานะปลายทาง — จะมาแก้ยอดหรือบันทึกชำระต่อไม่ได้
    assert (await client.patch(f"{base}/pay", headers=auth(admin_token))).status_code == 400
    assert (await client.patch(base, json={"late_amount": 5, "damage_amount": 0, "reason": "y"},
                               headers=auth(admin_token))).status_code == 400


@pytest.mark.asyncio(loop_scope="session")
async def test_fines_page_lists_rows_and_totals(
    client: AsyncClient, admin_token: str, student_token: str,
    test_admin: User, test_student: User, fine_equipment,
):
    req_id, item_id = await _borrowed_item(test_student, test_admin, fine_equipment, days_late=6)
    await client.post(f"/borrow-requests/{req_id}/items/{item_id}/return",
                      json={"condition_on_return": "ok"}, headers=auth(admin_token))

    assert (await client.get("/dashboard/fines", headers=auth(student_token))).status_code == 403

    r = await client.get("/dashboard/fines", headers=auth(admin_token))
    assert r.status_code == 200, r.text
    data = r.json()
    row = next(x for x in data["rows"] if x["item_id"] == str(item_id))
    assert row["days_late"] == 6 and row["total"] == 60.0 and row["status"] == "unpaid"
    assert data["unpaid_total"] >= 60.0 and data["unpaid_count"] >= 1

    # บันทึกชำระแล้วต้องย้ายฝั่งยอดรวม
    assert (await client.patch(f"/borrow-requests/{req_id}/items/{item_id}/fine/pay",
                               headers=auth(admin_token))).status_code == 200
    after = (await client.get("/dashboard/fines", headers=auth(admin_token))).json()
    assert next(x for x in after["rows"] if x["item_id"] == str(item_id))["status"] == "paid"

    export = await client.get("/dashboard/fines/export", headers=auth(admin_token))
    assert export.status_code == 200 and "text/csv" in export.headers["content-type"]
    assert "REQ-FINE" in export.text


@pytest.mark.asyncio(loop_scope="session")
async def test_student_sees_own_fine_in_request(
    client: AsyncClient, admin_token: str, student_token: str,
    test_admin: User, test_student: User, fine_equipment,
):
    """ผู้ยืมต้องเห็นค่าปรับของตัวเองพร้อมที่มา ไม่ใช่รู้ตอนมาถึงเคาน์เตอร์"""
    req_id, item_id = await _borrowed_item(test_student, test_admin, fine_equipment, days_late=2)
    await client.post(f"/borrow-requests/{req_id}/items/{item_id}/return",
                      json={"condition_on_return": "ok"}, headers=auth(admin_token))

    r = await client.get(f"/borrow-requests/{req_id}", headers=auth(student_token))
    assert r.status_code == 200, r.text
    item = next(i for i in r.json()["items"] if i["id"] == str(item_id))
    assert item["fine_total"] == 20.0 and item["fine_status"] == "unpaid"
    assert item["fine_basis"]["rate_per_day"] == 10.0
