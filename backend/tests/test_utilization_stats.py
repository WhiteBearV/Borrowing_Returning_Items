"""สถิติความคุ้มค่า (GET /dashboard/utilization) + แอดมินเลือกหน่วยจ่ายเอง (เฟส 5 ข้อ 11, 9)

สถิติคำนวณสดจาก borrow_items ไม่มีคอลัมน์เก็บเพิ่ม — เทสจึงสร้างการยืมจริงแล้วเช็คตัวเลขที่ออกมา
ตัวเลขชุดนี้ใช้ประกอบการตัดสินใจจัดซื้อเท่านั้น ไม่ใช่ฐานคิดค่าปรับ
"""
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.borrow_item import BorrowItem
from app.models.borrow_request import BorrowRequest
from app.models.equipment import Equipment
from app.models.notification import Notification
from app.models.user import User
from app.schemas.borrow import ApproveItemDecision, ApproveRequest
from app.services import borrow_service, equipment_service
from tests.conftest import auth

GROUP_NAME = "อุปกรณ์ทดสอบสถิติความคุ้มค่า"


@pytest_asyncio.fixture(loop_scope="session")
async def util_group():
    """2 หน่วยรุ่นเดียวกัน ราคา 1,000 ได้มา+เข้าระบบเมื่อ 100 วันก่อน (ช่วงวัดผล = 100 วัน)"""
    tag = uuid.uuid4().hex[:6].upper()
    eq_ids = [uuid.uuid4() for _ in range(2)]
    async with AsyncSessionLocal() as db:
        for i, eq_id in enumerate(eq_ids, start=1):
            db.add(Equipment(
                id=eq_id, code=f"UTIL-{tag}-{i:03d}", name=GROUP_NAME, item_type="durable",
                quantity_total=1, quantity_available=1, status="available",
                unit_value=1000, acquired_at=date.today() - timedelta(days=100),
                created_at=datetime.now(timezone.utc) - timedelta(days=100),
            ))
        await db.commit()
    yield eq_ids
    async with AsyncSessionLocal() as db:
        req_ids = (await db.execute(
            select(BorrowItem.borrow_request_id).where(BorrowItem.equipment_id.in_(eq_ids))
        )).scalars().all()
        if req_ids:
            await db.execute(delete(Notification).where(Notification.borrow_request_id.in_(req_ids)))
        await db.execute(delete(BorrowItem).where(BorrowItem.equipment_id.in_(eq_ids)))
        if req_ids:
            await db.execute(delete(BorrowRequest).where(BorrowRequest.id.in_(req_ids)))
        await db.execute(delete(Equipment).where(Equipment.id.in_(eq_ids)))
        await db.commit()


async def _make_pending_request(student: User, eq_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    req_id, item_id = uuid.uuid4(), uuid.uuid4()
    async with AsyncSessionLocal() as db:
        db.add(BorrowRequest(
            id=req_id, request_code=f"REQ-UTIL-{req_id.hex[:6]}", student_id=student.id,
            status="pending", purpose="ทดสอบสถิติ", requested_due_date=date(2099, 1, 1),
        ))
        db.add(BorrowItem(id=item_id, borrow_request_id=req_id, equipment_id=eq_id,
                          item_type_snapshot="durable", quantity=1))
        await db.commit()
    return req_id, item_id


@pytest.mark.asyncio(loop_scope="session")
async def test_utilization_counts_days_and_flags_never_borrowed(
    client: AsyncClient, admin_token: str, test_admin: User, test_student: User, util_group,
):
    u1, u2 = util_group
    req_id, item_id = await _make_pending_request(test_student, u1)
    async with AsyncSessionLocal() as db:
        admin = await db.get(User, test_admin.id)
        await borrow_service.approve_request(db, admin, req_id)
    # ย้อนวันอนุมัติไป 10 วัน แล้วปิดรายการวันนี้ = ของออกจากคลัง 10 วัน
    async with AsyncSessionLocal() as db:
        req = await db.get(BorrowRequest, req_id)
        req.approved_at = datetime.now(timezone.utc) - timedelta(days=10)
        item = await db.get(BorrowItem, item_id)
        item.returned = True
        item.returned_at = datetime.now(timezone.utc)
        item.condition_on_return = "ok"
        await db.commit()

    r = await client.get("/dashboard/utilization", headers=auth(admin_token))
    assert r.status_code == 200, r.text
    rows = {row["equipment_id"]: row for row in r.json()["rows"]}

    used = rows[str(u1)]
    assert used["borrow_count"] == 1
    assert used["days_borrowed"] == 10
    assert used["tracked_days"] == 100
    assert used["utilization_rate"] == pytest.approx(0.1, abs=0.01)
    # ค่าเสื่อมต่อวัน = (1,000 − ซาก) ÷ อายุ · ต้นทุนต่อวันใช้งาน = ค่าเสื่อม 100 วันในช่วงวัด ÷ ยืม 10 วัน
    # (ไม่ใช่ 1,000 ÷ 10 = 100 บ. แบบเดิมที่เอามูลค่าตลอดอายุมาหารการใช้ไม่กี่วัน)
    async with AsyncSessionLocal() as db:
        years, salvage = await equipment_service._depreciation_settings(db)
    daily = (1000 - salvage) / (years * 365.25)
    assert used["daily_depreciation"] == pytest.approx(daily, abs=0.01)
    assert used["cost_per_use_day"] == pytest.approx(daily * 100 / 10, abs=0.01)
    assert used["rating"] == "fair"

    idle = rows[str(u2)]
    assert idle["borrow_count"] == 0 and idle["days_borrowed"] == 0
    assert idle["cost_per_use_day"] is None
    assert idle["daily_depreciation"] == pytest.approx(daily, abs=0.01)  # ไม่เคยยืมก็ยังเสื่อมทุกวัน
    assert idle["rating"] == "idle"


def test_rating_separates_low_use_from_never_borrowed():
    """เคยถูกยืมแต่อัตราต่ำ = "ใช้งานน้อย" ต้องไม่ปนกับ "ไม่เคยถูกยืม" (เดิมขึ้น idle เหมือนกัน)"""
    from app.services.dashboard_service import _rate_label
    assert _rate_label(0.01, days_borrowed=2) == "low"
    assert _rate_label(0.0, days_borrowed=0) == "idle"
    assert _rate_label(0.10, days_borrowed=1) == "fair"
    assert _rate_label(0.50, days_borrowed=9) == "good"


@pytest.mark.asyncio(loop_scope="session")
async def test_utilization_requires_admin(client: AsyncClient, student_token: str):
    assert (await client.get("/dashboard/utilization", headers=auth(student_token))).status_code == 403


@pytest.mark.asyncio(loop_scope="session")
async def test_admin_can_force_specific_unit_on_approve(test_admin: User, test_student: User, util_group):
    """แอดมินระบุหน่วยเองได้ ทับกฎ "ถูกใช้น้อยสุดก่อน" — เคสจริงคือจ่ายเครื่องที่วางอยู่ตรงหน้า"""
    u1, u2 = util_group
    # ปกติระบบจะเลือก u1 (รหัสต่ำสุด ยังไม่เคยถูกใช้เท่ากัน) — สั่งให้จ่าย u2 แทน
    req_id, item_id = await _make_pending_request(test_student, u1)
    async with AsyncSessionLocal() as db:
        admin = await db.get(User, test_admin.id)
        await borrow_service.approve_request(db, admin, req_id, ApproveRequest(
            items=[ApproveItemDecision(item_id=item_id, approved=True, equipment_id=u2)],
        ))
    async with AsyncSessionLocal() as db:
        item = await db.get(BorrowItem, item_id)
        assert item.equipment_id == u2, "ต้องจ่ายหน่วยที่แอดมินเลือก ไม่ใช่หน่วยที่ระบบเลือกให้"


@pytest.mark.asyncio(loop_scope="session")
async def test_dashboard_borrowed_value_counts_all_types_at_approval(
    client: AsyncClient, admin_token: str, test_admin: User, test_student: User, util_group,
):
    """การ์ด "มูลค่าอุปกรณ์ที่ถูกยืมออก" นับทุกประเภททันทีที่อนุมัติ (ราคา ณ วันอนุมัติ) ไม่ต้องรอสรุปผลคืน
    — เทียบก่อน/หลังแทนค่าสัมบูรณ์ เพราะ DB dev มีการยืมจริงของคนอื่นปนอยู่"""
    async def summary() -> dict:
        r = await client.get("/dashboard/summary", headers=auth(admin_token))
        assert r.status_code == 200, r.text
        return r.json()

    before = await summary()
    req_id, _ = await _make_pending_request(test_student, util_group[0])   # ครุภัณฑ์ราคา 1,000
    async with AsyncSessionLocal() as db:
        await borrow_service.approve_request(db, await db.get(User, test_admin.id), req_id)
    after = await summary()
    assert after["borrowed_value_this_month"] - before["borrowed_value_this_month"] == pytest.approx(1000)
    assert after["borrowed_value_this_year"] - before["borrowed_value_this_year"] == pytest.approx(1000)


@pytest.mark.asyncio(loop_scope="session")
async def test_utilization_period_clips_days_and_monthly_matches_dashboard(
    client: AsyncClient, admin_token: str, test_admin: User, test_student: User, util_group,
):
    """เลือกช่วงเวลา: นับเฉพาะวันที่คาบเกี่ยวช่วง + สรุปรายเดือนเดือนนี้ = การ์ด Dashboard เดือนนี้"""
    from app.core.config import TZ
    u1, _ = util_group
    req_id, item_id = await _make_pending_request(test_student, u1)
    async with AsyncSessionLocal() as db:
        await borrow_service.approve_request(db, await db.get(User, test_admin.id), req_id)
    today = datetime.now(TZ).date()
    at_6am = lambda d: datetime.combine(d, datetime.min.time(), TZ).replace(hour=6)  # noqa: E731
    async with AsyncSessionLocal() as db:   # ยืมออก 40 วันก่อน คืน 30 วันก่อน (10 วัน)
        (await db.get(BorrowRequest, req_id)).approved_at = at_6am(today - timedelta(days=40))
        item = await db.get(BorrowItem, item_id)
        item.returned, item.returned_at, item.condition_on_return = True, at_6am(today - timedelta(days=30)), "ok"
        await db.commit()

    async def row(date_from: date, date_to: date) -> dict:
        r = await client.get("/dashboard/utilization", headers=auth(admin_token),
                             params={"date_from": date_from.isoformat(), "date_to": date_to.isoformat()})
        assert r.status_code == 200, r.text
        return next(x for x in r.json()["rows"] if x["equipment_id"] == str(u1))

    last35 = await row(today - timedelta(days=35), today)
    assert last35["days_borrowed"] == 5          # ตัดเหลือเฉพาะวันที่ −35 ถึง −30
    assert last35["borrow_count"] == 0           # ยืมก่อนช่วง = ไม่ใช่ "ยืมใหม่ในช่วงนี้"
    assert last35["tracked_days"] == 36          # −35 ถึงวันนี้ รวมทั้งสองวัน
    assert last35["rating"] != "idle"            # แต่ของถูกใช้อยู่ในช่วงนั้นจริง
    last20 = await row(today - timedelta(days=20), today)
    assert last20["days_borrowed"] == 0 and last20["rating"] == "idle"

    bad = await client.get("/dashboard/utilization", headers=auth(admin_token),
                           params={"date_from": today.isoformat()})
    assert bad.status_code == 400

    util = (await client.get("/dashboard/utilization", headers=auth(admin_token),
                             params={"item_type": "all"})).json()
    summary = (await client.get("/dashboard/summary", headers=auth(admin_token))).json()
    assert util["monthly"][-1]["month"] == today.strftime("%Y-%m")
    assert util["monthly"][-1]["borrowed_value"] == pytest.approx(summary["borrowed_value_this_month"])
