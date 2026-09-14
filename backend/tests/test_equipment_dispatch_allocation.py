"""ลำดับจ่ายของ — หน่วยที่ถูกใช้มาน้อยสุดถูกยืมออกก่อน แล้วค่อยเก่าสุดก่อน

feedback อาจารย์ 5 ก.ย. 69 ข้อ 9: กฎเดิม (FIFO ตาม acquired_at ล้วน ๆ) ทำให้ของเก่าที่โทรมอยู่แล้ว
ถูกจ่ายซ้ำทุกครั้งจนพังอยู่ชิ้นเดียว เกณฑ์ใหม่กระจายการสึกหรอตาม "วันที่เคยถูกยืมจริง"
อายุของ (acquired_at) ลดบทบาทเหลือแค่ tie-break ของหน่วยที่ถูกใช้มาเท่ากัน

ทุกเคสจงใจตั้งให้ลำดับ code สวนทางกับลำดับที่คาดหวัง เพื่อพิสูจน์ว่าเปลี่ยนพฤติกรรมจริง
ไม่ใช่ผ่านเพราะบังเอิญเรียงตรงกัน

หมายเหตุ: conftest.py มี PYTEST_ALLOW_DB=1 รันใส่ DB dev จริง — ทุกเทสต้อง cleanup ใน fixture teardown
"""
import uuid
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.borrow_item import BorrowItem
from app.models.borrow_request import BorrowRequest
from app.models.equipment import Equipment
from app.models.notification import Notification
from app.models.user import User
from app.services import borrow_service, equipment_service

GROUP_NAME = "อุปกรณ์ทดสอบลำดับจ่ายของ"

# code เรียง 001 → 004 แต่อายุสวนทาง: 001 ใหม่สุด, 003 เก่าสุด, 004 ไม่รู้วันที่
UNITS = [("001", date(2024, 1, 10)), ("002", date(2022, 5, 1)), ("003", date(2020, 6, 5)), ("004", None)]


@pytest_asyncio.fixture(loop_scope="session")
async def aged_group():
    tag = uuid.uuid4().hex[:6].upper()
    eq_ids = []
    async with AsyncSessionLocal() as db:
        for seq, acquired in UNITS:
            eq_id = uuid.uuid4()
            eq_ids.append(eq_id)
            db.add(Equipment(
                id=eq_id, code=f"DISP-{tag}-{seq}", name=GROUP_NAME, item_type="durable",
                quantity_total=1, quantity_available=1, status="available",
                unit_value=1000, acquired_at=acquired,
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


async def _make_pending_request(student: User, eq_id: uuid.UUID) -> uuid.UUID:
    req_id = uuid.uuid4()
    async with AsyncSessionLocal() as db:
        db.add(BorrowRequest(
            id=req_id, request_code=f"REQ-DISP-{req_id.hex[:6]}", student_id=student.id,
            status="pending", purpose="ทดสอบลำดับจ่ายของ", requested_due_date=date(2099, 1, 1),
        ))
        db.add(BorrowItem(
            id=uuid.uuid4(), borrow_request_id=req_id, equipment_id=eq_id,
            item_type_snapshot="durable", quantity=1,
        ))
        await db.commit()
    return req_id


class _E:
    """หน่วยจำลองสำหรับเทสเรียงลำดับล้วน ๆ (dispatch_key อ่านแค่ id/code/acquired_at)"""
    def __init__(self, code, acquired=None):
        self.id = uuid.uuid4()
        self.code = code
        self.acquired_at = acquired


def test_dispatch_key_puts_least_used_unit_first():
    """หน่วยที่ถูกใช้มาน้อยสุดต้องมาก่อนเสมอ แม้จะเป็นของที่ได้มาใหม่กว่า"""
    new_unused = _E("A-001", date(2024, 1, 10))   # ใหม่สุด แต่ไม่เคยถูกใช้
    old_heavy = _E("A-003", date(2020, 6, 5))     # เก่าสุด แต่ถูกใช้ไป 40 วัน
    mid_light = _E("A-002", date(2022, 5, 1))     # กลาง ๆ ถูกใช้ไป 5 วัน
    usage = {old_heavy.id: 40, mid_light.id: 5}

    ordered = sorted([old_heavy, mid_light, new_unused],
                     key=lambda e: equipment_service.dispatch_key(e, usage))
    assert [e.code for e in ordered] == ["A-001", "A-002", "A-003"]


def test_dispatch_key_falls_back_to_age_then_code():
    """ถูกใช้มาเท่ากัน → เก่าสุดก่อน · ไม่รู้วันที่ได้มา → ท้ายแถว แล้ว tie-break ด้วย code"""
    rows = [_E("B-001", date(2024, 1, 10)), _E("B-002", date(2022, 5, 1)),
            _E("B-003", date(2020, 6, 5)), _E("B-004", None)]
    assert [e.code for e in sorted(rows, key=equipment_service.dispatch_key)] == \
        ["B-003", "B-002", "B-001", "B-004"]

    no_dates = [_E("C-003"), _E("C-001"), _E("C-002")]
    assert [e.code for e in sorted(no_dates, key=equipment_service.dispatch_key)] == \
        ["C-001", "C-002", "C-003"]


@pytest.mark.asyncio(loop_scope="session")
async def test_approve_hands_out_oldest_unit_first_when_none_used_yet(test_admin, test_student, aged_group):
    """ยังไม่มีหน่วยไหนเคยถูกใช้ → ทุกหน่วยเสมอกันที่ 0 วัน ตกลงไปที่ tie-break คืออายุ
    อนุมัติ 4 ใบติดกัน → ต้องได้ 003 (2020) → 002 (2022) → 001 (2024) → 004 (ไม่รู้วันที่) ตามลำดับ"""
    u001, u002, u003, u004 = aged_group
    expected = [u003, u002, u001, u004]
    got = []
    for _ in range(4):
        # ทุกใบผูกไว้กับ u001 ตอนยื่น — การจัดสรรจริงเกิดตอนอนุมัติ ต้องไม่ยึดหน่วยที่ผูกไว้
        req_id = await _make_pending_request(test_student, u001)
        async with AsyncSessionLocal() as db:
            admin = await db.get(User, test_admin.id)
            await borrow_service.approve_request(db, admin, req_id)
        async with AsyncSessionLocal() as db:
            item = (await db.execute(
                select(BorrowItem).where(BorrowItem.borrow_request_id == req_id)
            )).scalar_one()
            got.append(item.equipment_id)

    assert got == expected, "ต้องจ่ายของเก่าสุดก่อน และของที่ไม่รู้วันที่ท้ายสุด"


@pytest.mark.asyncio(loop_scope="session")
async def test_returned_unit_goes_to_back_of_queue(test_admin, test_student, aged_group):
    """คืนหน่วยเก่าสุดแล้ว รอบหน้าต้อง **ไม่** ได้หน่วยเดิมอีก เพราะมันมีวันใช้งานสะสมแล้ว
    ต้องไปหยิบหน่วยที่ยังไม่เคยถูกใช้เลยแทน — นี่คือหัวใจของการเปลี่ยนกฎข้อ 9"""
    u001, u002, u003, _u004 = aged_group
    req_1 = await _make_pending_request(test_student, u001)
    async with AsyncSessionLocal() as db:
        admin = await db.get(User, test_admin.id)
        await borrow_service.approve_request(db, admin, req_1)
    async with AsyncSessionLocal() as db:
        item = (await db.execute(select(BorrowItem).where(BorrowItem.borrow_request_id == req_1))).scalar_one()
        assert item.equipment_id == u003
        # คืนเข้าคลังตรง ๆ (ไม่ผ่าน endpoint คืน — เทสนี้สนใจแค่ลำดับการจ่ายของ)
        eq = await db.get(Equipment, u003)
        eq.quantity_available = 1
        await db.commit()

    req_2 = await _make_pending_request(test_student, u002)
    async with AsyncSessionLocal() as db:
        admin = await db.get(User, test_admin.id)
        await borrow_service.approve_request(db, admin, req_2)
    async with AsyncSessionLocal() as db:
        item = (await db.execute(select(BorrowItem).where(BorrowItem.borrow_request_id == req_2))).scalar_one()
        assert item.equipment_id == u002, "u003 เพิ่งถูกใช้ไป ต้องได้ u002 ที่ยังไม่เคยถูกใช้ (เก่าสุดในกลุ่มที่เหลือ)"
