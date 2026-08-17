"""
ยุบครุภัณฑ์รุ่นเดียวกันหลายหน่วยเป็นกลุ่ม — เลือกหน่วยรหัสต่ำสุดที่ว่างอัตโนมัติ แบบ race-free

สองคำขอ pending ที่ผูกไว้กับหน่วยเดียวกันตอนยื่น (เพราะยังไม่มีการตัดสต็อกจนกว่าจะอนุมัติ ทั้งสองใบ
จึงเห็นหน่วยรหัสต่ำสุดตัวเดียวกัน) ต้องอนุมัติผ่านทั้งคู่โดยได้คนละหน่วย ไม่ error/ไม่ปล่อยของซ้ำ
— การจัดสรรจริงเกิดตอนอนุมัติภายใต้ with_for_update() ที่ล็อกทั้งกลุ่ม ไม่ใช่ตอนยื่น
"""
import asyncio
import uuid
from datetime import date

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import delete, select, update

from app.core.database import AsyncSessionLocal
from app.models.borrow_item import BorrowItem
from app.models.borrow_request import BorrowRequest
from app.models.equipment import Equipment
from app.models.notification import Notification
from app.models.user import User
from app.schemas.borrow import ReturnItemRequest
from app.services import borrow_service

GROUP_NAME = "อุปกรณ์ทดสอบกลุ่ม (race)"


@pytest_asyncio.fixture(loop_scope="session")
async def three_unit_group():
    """3 หน่วยของรุ่นเดียวกัน code GRP-xxx-001/002/003 — ทุกหน่วยว่างพร้อมยืม"""
    tag = uuid.uuid4().hex[:6].upper()
    eq_ids = [uuid.uuid4() for _ in range(3)]
    async with AsyncSessionLocal() as db:
        for i, eq_id in enumerate(eq_ids, start=1):
            db.add(Equipment(
                id=eq_id,
                code=f"GRP-{tag}-{i:03d}",
                name=GROUP_NAME,
                item_type="durable",
                quantity_total=1,
                quantity_available=1,
                status="available",
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
            id=req_id,
            request_code=f"REQ-GRP-{req_id.hex[:6]}",
            student_id=student.id,
            status="pending",
            purpose="ทดสอบยุบกลุ่มอุปกรณ์",
            requested_due_date=date(2099, 1, 1),
        ))
        db.add(BorrowItem(
            id=uuid.uuid4(),
            borrow_request_id=req_id,
            equipment_id=eq_id,
            item_type_snapshot="durable",
            quantity=1,
        ))
        await db.commit()
    return req_id


@pytest.mark.asyncio(loop_scope="session")
async def test_two_pending_requests_pinned_to_same_unit_both_approve_to_different_units(
    test_admin, test_student, three_unit_group,
):
    """2 คำขอที่ผูกไว้กับหน่วยรหัสต่ำสุดตัวเดียวกันตอนยื่น (สถานการณ์จริงเมื่อยื่นพร้อมกัน) —
    อนุมัติทั้งคู่ต้องสำเร็จ ได้คนละหน่วย ไม่ error และสต็อกรวมลดลง 2 พอดี ไม่ใช่ 1"""
    unit_1, unit_2, unit_3 = three_unit_group
    # ทั้งสองใบผูกกับ unit_1 (รหัสต่ำสุด) เหมือนกันตอนยื่น — จำลอง "จอง" แบบ non-binding
    req_a = await _make_pending_request(test_student, unit_1)
    req_b = await _make_pending_request(test_student, unit_1)

    async with AsyncSessionLocal() as db:
        admin = await db.get(User, test_admin.id)
        await borrow_service.approve_request(db, admin, req_a)
    async with AsyncSessionLocal() as db:
        admin = await db.get(User, test_admin.id)
        await borrow_service.approve_request(db, admin, req_b)

    async with AsyncSessionLocal() as db:
        item_a = (await db.execute(select(BorrowItem).where(BorrowItem.borrow_request_id == req_a))).scalar_one()
        item_b = (await db.execute(select(BorrowItem).where(BorrowItem.borrow_request_id == req_b))).scalar_one()
        assert item_a.equipment_id != item_b.equipment_id, "สองคำขอได้หน่วยเดียวกัน = ปล่อยของซ้ำ"
        assert {item_a.equipment_id, item_b.equipment_id} <= {unit_1, unit_2, unit_3}

        rows = (await db.execute(select(Equipment).where(Equipment.id.in_([unit_1, unit_2, unit_3])))).scalars().all()
        total_available = sum(r.quantity_available for r in rows)
        assert total_available == 1, f"เหลือของว่างต้องเป็น 1 จาก 3 (อนุมัติไป 2) แต่ได้ {total_available}"


@pytest.mark.asyncio(loop_scope="session")
async def test_returned_unit_becomes_lowest_available_again(test_admin, test_student, three_unit_group):
    """A ยืม → ได้ unit ต่ำสุด (1) · B ยืม → ได้ unit ถัดไป (2) เพราะ 1 ไม่ว่าง · A คืน 1 ·
    C ยืม → ต้องได้ unit 1 กลับมา (ไม่ใช่ 3) เพราะ 1 เป็นเลขต่ำสุดที่ว่างอยู่ ณ ตอนนั้น"""
    unit_1, unit_2, unit_3 = three_unit_group

    req_a = await _make_pending_request(test_student, unit_1)
    async with AsyncSessionLocal() as db:
        admin = await db.get(User, test_admin.id)
        await borrow_service.approve_request(db, admin, req_a)
    async with AsyncSessionLocal() as db:
        item_a = (await db.execute(select(BorrowItem).where(BorrowItem.borrow_request_id == req_a))).scalar_one()
        assert item_a.equipment_id == unit_1

    req_b = await _make_pending_request(test_student, unit_1)  # ยื่นชื่อ unit_1 เหมือนเดิม (ยังเป็นตัวแทนกลุ่ม)
    async with AsyncSessionLocal() as db:
        admin = await db.get(User, test_admin.id)
        await borrow_service.approve_request(db, admin, req_b)
    async with AsyncSessionLocal() as db:
        item_b = (await db.execute(select(BorrowItem).where(BorrowItem.borrow_request_id == req_b))).scalar_one()
        assert item_b.equipment_id == unit_2, "unit_1 ถูกยืมไปแล้ว ต้องได้ unit_2 (รหัสต่ำสุดที่ว่างถัดไป)"

    # A คืน unit_1
    async with AsyncSessionLocal() as db:
        admin = await db.get(User, test_admin.id)
        await borrow_service.return_item(
            db, admin, req_a, item_a.id,
            body=ReturnItemRequest(condition_on_return="ok"),
        )

    req_c = await _make_pending_request(test_student, unit_1)
    async with AsyncSessionLocal() as db:
        admin = await db.get(User, test_admin.id)
        await borrow_service.approve_request(db, admin, req_c)
    async with AsyncSessionLocal() as db:
        item_c = (await db.execute(select(BorrowItem).where(BorrowItem.borrow_request_id == req_c))).scalar_one()
        assert item_c.equipment_id == unit_1, "unit_1 คืนแล้วต้องเป็นตัวเลือกแรกอีกครั้ง ไม่ใช่ unit_3"


async def _approve_in_own_session(admin_id: uuid.UUID, req_id: uuid.UUID):
    async with AsyncSessionLocal() as db:
        admin = await db.get(User, admin_id)
        try:
            await borrow_service.approve_request(db, admin, req_id)
            return None
        except HTTPException as e:
            return e


@pytest.mark.asyncio(loop_scope="session")
async def test_group_lock_waits_for_concurrent_transaction_not_just_original_unit(
    test_admin, test_student, three_unit_group,
):
    """ล็อกกลุ่มต้องรอ transaction อื่นที่ถือ unit_2 (ไม่ใช่หน่วยที่ผูกไว้ตอนยื่น) อยู่จริง

    ก่อนแก้: ล็อกแค่ Equipment.id.in_([หน่วยที่ผูกไว้ตอนยื่น]) — ถ้ามีคนถือ unit_2 ค้างอยู่
    (คนละหน่วยกับที่ item ผูกไว้) approve จะไม่รอเลย อ่าน unit_2 เก่ามาเลือกซ้ำได้
    ต้องบังคับชนจริงด้วยการถือ lock ยาวเหมือน test_stock_race.py ไม่ใช่แค่เรียงกัน
    """
    unit_1, unit_2, unit_3 = three_unit_group
    req_id = await _make_pending_request(test_student, unit_1)  # ผูกกับ unit_1 ตอนยื่น

    async with AsyncSessionLocal() as locker:
        # ถือ unit_2 ไว้และหักสต็อกจนหมด แต่ยังไม่ commit — unit_1/unit_3 ยังว่างปกติ
        await locker.execute(select(Equipment).where(Equipment.id == unit_2).with_for_update())
        await locker.execute(update(Equipment).where(Equipment.id == unit_2).values(quantity_available=0))

        task = asyncio.create_task(_approve_in_own_session(test_admin.id, req_id))
        await asyncio.sleep(0.3)
        assert not task.done(), "approve ไม่รอ lock ของ unit_2 เลย — แปลว่าล็อกแค่หน่วยที่ผูกไว้ตอนยื่น ไม่ได้ล็อกทั้งกลุ่ม"

        await locker.commit()  # ปล่อย lock ให้ approve เดินต่อ

    result = await asyncio.wait_for(task, timeout=10)
    assert result is None, f"approve ควรสำเร็จ (ยังมี unit_1/unit_3 ว่าง) แต่ได้ {result}"

    async with AsyncSessionLocal() as db:
        item = (await db.execute(select(BorrowItem).where(BorrowItem.borrow_request_id == req_id))).scalar_one()
        assert item.equipment_id in (unit_1, unit_3), "ต้องได้หน่วยที่ยังว่างจริง ไม่ใช่ unit_2 ที่ถูกกันไว้"
