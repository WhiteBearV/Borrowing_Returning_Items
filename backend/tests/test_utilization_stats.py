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
from app.services import borrow_service
from tests.conftest import auth

GROUP_NAME = "อุปกรณ์ทดสอบสถิติความคุ้มค่า"


@pytest_asyncio.fixture(loop_scope="session")
async def util_group():
    """2 หน่วยรุ่นเดียวกัน ราคา 1,000 ได้มาเมื่อ 100 วันก่อน (คิดอัตราการใช้งานได้)"""
    tag = uuid.uuid4().hex[:6].upper()
    eq_ids = [uuid.uuid4() for _ in range(2)]
    async with AsyncSessionLocal() as db:
        for i, eq_id in enumerate(eq_ids, start=1):
            db.add(Equipment(
                id=eq_id, code=f"UTIL-{tag}-{i:03d}", name=GROUP_NAME, item_type="durable",
                quantity_total=1, quantity_available=1, status="available",
                unit_value=1000, acquired_at=date.today() - timedelta(days=100),
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
    assert used["owned_days"] == 100
    assert used["utilization_rate"] == pytest.approx(0.1, abs=0.01)
    assert used["cost_per_day"] == pytest.approx(100.0)   # 1,000 ÷ 10 วัน
    assert used["rating"] == "fair"

    idle = rows[str(u2)]
    assert idle["borrow_count"] == 0 and idle["days_borrowed"] == 0
    assert idle["cost_per_day"] is None
    assert idle["rating"] == "idle"


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
