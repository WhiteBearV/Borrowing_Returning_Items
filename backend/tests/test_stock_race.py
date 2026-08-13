"""
กันสต็อกรั่วตอนอนุมัติพร้อมกัน

เดิม approve_request อ่าน quantity_available มาเช็คใน Python แล้วค่อยเขียนกลับ
โดยไม่ล็อกแถว แอดมิน 2 คนที่กดอนุมัติของชิ้นสุดท้ายพร้อมกันจะอ่านได้ค่าเดียวกัน
ผ่านเงื่อนไขทั้งคู่ แล้วเขียนทับกัน = ปล่อยของชิ้นเดียวออกไป 2 ใบโดยไม่มี error ใด ๆ
รู้อีกทีตอนนับของจริงแล้วไม่ครบ

เทสต์นี้จำลองสองแอดมินยิงพร้อมกันจริง ๆ (คนละ session) ไม่ใช่เรียงกัน
"""
import asyncio
import uuid

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
from app.services import borrow_service


@pytest_asyncio.fixture(loop_scope="session")
async def last_unit_equipment():
    """อุปกรณ์ที่เหลือของว่างชิ้นเดียว — ตัวตั้งต้นของการแย่งกัน"""
    eq_id = uuid.uuid4()
    async with AsyncSessionLocal() as db:
        db.add(Equipment(
            id=eq_id,
            code=f"RACE-{eq_id.hex[:6].upper()}",
            name="ของชิ้นสุดท้าย (ทดสอบ race)",
            item_type="durable",
            quantity_total=1,
            quantity_available=1,
            status="available",
        ))
        await db.commit()
    yield eq_id
    # เก็บกวาดใน fixture ไม่ใช่ท้ายเทสต์ เพื่อให้ทำงานแม้ assert พัง
    # ไล่ลบตามลำดับ FK: notification → item → request → equipment
    async with AsyncSessionLocal() as db:
        req_ids = (await db.execute(
            select(BorrowItem.borrow_request_id).where(BorrowItem.equipment_id == eq_id)
        )).scalars().all()
        if req_ids:
            await db.execute(delete(Notification).where(Notification.borrow_request_id.in_(req_ids)))
        await db.execute(delete(BorrowItem).where(BorrowItem.equipment_id == eq_id))
        if req_ids:
            await db.execute(delete(BorrowRequest).where(BorrowRequest.id.in_(req_ids)))
        await db.execute(delete(Equipment).where(Equipment.id == eq_id))
        await db.commit()


async def _make_pending_request(student: User, eq_id: uuid.UUID) -> uuid.UUID:
    req_id = uuid.uuid4()
    async with AsyncSessionLocal() as db:
        db.add(BorrowRequest(
            id=req_id,
            request_code=f"REQ-RACE-{req_id.hex[:6]}",
            student_id=student.id,
            status="pending",
            purpose="ทดสอบแย่งของชิ้นสุดท้าย",
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


async def _approve_in_own_session(admin_id: uuid.UUID, req_id: uuid.UUID):
    """อนุมัติใน session ของตัวเอง คืน None ถ้าสำเร็จ คืน exception ถ้าถูกปฏิเสธ"""
    async with AsyncSessionLocal() as db:
        admin = await db.get(User, admin_id)
        try:
            await borrow_service.approve_request(db, admin, req_id)
            return None
        except HTTPException as e:
            return e


@pytest.mark.asyncio(loop_scope="session")
async def test_approve_rereads_stock_after_waiting_for_lock(
    test_admin, test_student, last_unit_equipment
):
    """
    อนุมัติต้องรอ transaction อื่นที่ถือแถวอุปกรณ์อยู่ แล้วอ่านสต็อกใหม่ก่อนตัดสินใจ

    ไม่ยิงสองใบพร้อมกันเฉย ๆ เพราะผลจะขึ้นกับจังหวะ scheduler ของ asyncio
    (ลองแล้ว: ผ่านทั้งที่ยังไม่มี lock) จึงบังคับให้เกิดการชนแน่นอนด้วยการ
    ให้อีก transaction ถือ lock พร้อมหักสต็อกจนหมดค้างไว้ แล้วค่อยปล่อย

    ถ้า approve_request ไม่ล็อกแถว: มันจะอ่านได้ค่าเก่า (ยังเหลือ 1) ผ่านเงื่อนไข
    แล้วเขียนทับผลของอีก transaction = ปล่อยของชิ้นเดียวออกไปสองครั้ง
    """
    eq_id = last_unit_equipment
    req_id = await _make_pending_request(test_student, eq_id)

    async with AsyncSessionLocal() as locker:
        # ถือแถวไว้และหักสต็อกจนหมด แต่ยังไม่ commit
        await locker.execute(select(Equipment).where(Equipment.id == eq_id).with_for_update())
        await locker.execute(
            update(Equipment).where(Equipment.id == eq_id).values(quantity_available=0)
        )

        task = asyncio.create_task(_approve_in_own_session(test_admin.id, req_id))
        await asyncio.sleep(0.3)
        assert not task.done(), "approve ไม่รอ lock เลย — แปลว่าอ่านสต็อกโดยไม่ล็อกแถว"

        await locker.commit()  # ปล่อย lock ให้ approve เดินต่อ

    result = await asyncio.wait_for(task, timeout=10)

    assert isinstance(result, HTTPException), (
        "approve สำเร็จทั้งที่ของหมดแล้ว — อ่านค่าสต็อกเก่ามาตัดสินใจ (สต็อกรั่ว)"
    )
    assert result.status_code == 400

    async with AsyncSessionLocal() as db:
        eq = await db.get(Equipment, eq_id)
        assert eq.quantity_available == 0, f"สต็อกเพี้ยน: {eq.quantity_available}"
        req = await db.get(BorrowRequest, req_id)
        assert req.status == "pending", f"ใบที่อนุมัติไม่สำเร็จต้องคงเป็น pending ไม่ใช่ {req.status}"
