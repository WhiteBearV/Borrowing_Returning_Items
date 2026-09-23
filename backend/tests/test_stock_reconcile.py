"""กระทบยอดสต็อกในหน้าตรวจสอบระบบ — จับของที่ยอดคงเหลือไม่ตรงกับประวัติการยืม

แนวคิดมาจากระบบเช่าเครื่องมือเชิงพาณิชย์ (SKGRent) ที่เก็บยอดแยกทุกช่องทาง (มีอยู่/ให้เช่า/ซ่อม/จอง)
แล้วกระทบยอดได้ตลอดเวลา — ของเราคำนวณสดจาก borrow_items แทนการเพิ่มคอลัมน์

ที่ต้องกันให้ได้: บั๊กนำเข้าไฟล์ทะเบียนที่เคยเขียนทับ quantity_available จนของยืมไม่ได้ทั้งที่อยู่บนชั้น
และต้องไม่เตือนผิดกับของที่ส่งซ่อม/สูญหาย ซึ่งถูกกันยอดเป็น 0 โดยตั้งใจ

หมายเหตุ: conftest.py มี PYTEST_ALLOW_DB=1 รันใส่ DB dev จริง — ทุกเทสต้อง cleanup ใน finally เสมอ
"""
import uuid

from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.equipment import Equipment
from app.services.system_check_service import _stock_reconcile


async def _make_equipment(**kw) -> tuple[uuid.UUID, str]:
    eq_id = uuid.uuid4()
    code = f"RECON-{eq_id.hex[:6].upper()}"
    async with AsyncSessionLocal() as db:
        db.add(Equipment(id=eq_id, code=code, name="ของทดสอบกระทบยอด", item_type="material", **kw))
        await db.commit()
    return eq_id, code


async def _cleanup(*ids: uuid.UUID) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Equipment).where(Equipment.id.in_(ids)))
        await db.commit()


async def test_flags_equipment_whose_available_does_not_add_up():
    """ยอดคงเหลือหายไปโดยไม่มีการยืมรองรับ = จำนวนที่ต้องตรวจสอบต้องเพิ่มขึ้น 1

    วัดเป็นส่วนต่างก่อน/หลัง เพราะ DB dev มีของจริงที่ยอดไม่ตรงอยู่ก่อนแล้ว (ตัวเลขคงที่เทียบตรง ๆ ไม่ได้)
    """
    async with AsyncSessionLocal() as db:
        before, _ = await _stock_reconcile(db)
    eq_id, _code = await _make_equipment(quantity_total=10, quantity_available=7, status="available")
    try:
        async with AsyncSessionLocal() as db:
            after, _ = await _stock_reconcile(db)
    finally:
        await _cleanup(eq_id)
    assert after == before + 1


async def test_ignores_equipment_that_is_not_available():
    """ของส่งซ่อม/สูญหายถูกกันยอดเป็น 0 ตั้งใจ (borrow_service.return_item ตั้ง status ให้) — ห้ามเตือน"""
    eq_id, code = await _make_equipment(quantity_total=1, quantity_available=0, status="under_repair")
    try:
        async with AsyncSessionLocal() as db:
            _, sample = await _stock_reconcile(db)
    finally:
        await _cleanup(eq_id)
    assert code not in sample


async def test_balanced_equipment_is_not_flagged():
    """ของที่ยอดตรง (ไม่มีใครยืม คงเหลือเท่าทั้งหมด) ต้องไม่ถูกนับเป็นปัญหา"""
    eq_id, code = await _make_equipment(quantity_total=5, quantity_available=5, status="available")
    try:
        async with AsyncSessionLocal() as db:
            _, sample = await _stock_reconcile(db)
    finally:
        await _cleanup(eq_id)
    assert code not in sample
