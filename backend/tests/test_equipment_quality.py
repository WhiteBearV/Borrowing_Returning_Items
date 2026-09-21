"""ค่าคุณภาพอุปกรณ์ (เฟส 10 — feedback 15 ก.ย. 69)

จุดที่ต้องไม่พังเด็ดขาด:
- สูตรมีจุดเดียวที่ equipment_service.current_quality() — baseline=None ต้องคืน None เสมอ (ไม่ใช่ 0)
- นับวันถูกยืม "หลังวันประเมิน" เท่านั้น (quality_usage_days_map / borrowed_days_expr(since=...))
  ช่วงที่คืนไปแล้วก่อนวันประเมินต้องนับ 0 ไม่ใช่ 1 (ต่างจาก usage_days_map ที่มีขั้นต่ำ 1 วัน)
- การประเมิน (เขียน quality_baseline) มีจุดเดียวที่ assess_quality() เรียกจาก 4 จังหวะ + audit ทุกครั้ง
- นักศึกษาต้องไม่เห็นค่าคุณภาพเลยสักฟิลด์เดียว ไม่ว่าจะเข้าทาง endpoint ไหน

หมายเหตุ: conftest.py มี PYTEST_ALLOW_DB=1 รันใส่ DB dev จริง — ทุกเทสต้อง cleanup ใน fixture teardown
รวม audit_logs ของตัวเอง (ตามกฎ CLAUDE.md)
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
from app.models.user import User
from app.services import borrow_service, equipment_service
from tests.conftest import auth


# ── สูตร (ฟังก์ชันบริสุทธิ์ — ไม่แตะ DB) ────────────────────────────────────────

def test_current_quality_not_assessed_is_none_not_zero():
    assert equipment_service.current_quality(None, None, 4, 0, 50, 4) is None
    assert equipment_service.current_quality(None, datetime.now(timezone.utc), 4, 0, 50, 4) is None


def test_current_quality_worked_examples_from_plan():
    """ตัวอย่างจากแผน (อายุ 4 ปี, น้ำหนักอายุ:การใช้งาน = 50:50)
    เครื่องใหม่ 100% วางในคลัง 1 ปี → 87.5% · ถูกยืมตลอด 1 ปี → 75% · เครื่องบริจาค 60% ถูกยืมตลอด 1 ปี → 35%
    · ครบ 4 ปีไม่เคยถูกยืม → 50%
    """
    now = datetime.now(timezone.utc)
    one_year_ago = now - timedelta(days=365)
    four_years_ago = now - timedelta(days=4 * 365)

    # วางในคลัง 1 ปี ไม่เคยถูกยืม
    q = equipment_service.current_quality(100.0, one_year_ago, 4, 0, 50, 4, now=now)
    assert q == 87.5

    # ถูกยืมตลอด 1 ปี (usage_days_since_baseline = 365 พอดีกับที่ผ่านไป)
    q = equipment_service.current_quality(100.0, one_year_ago, 4, 365, 50, 4, now=now)
    assert q == 75.0

    # เครื่องบริจาค 60% ถูกยืมตลอด 1 ปี
    q = equipment_service.current_quality(60.0, one_year_ago, 4, 365, 50, 4, now=now)
    assert q == 35.0

    # ครบ 4 ปีไม่เคยถูกยืมเลย (baseline 100%)
    q = equipment_service.current_quality(100.0, four_years_ago, 4, 0, 50, 4, now=now)
    assert q == 50.0


def test_current_quality_clamps_0_to_100():
    now = datetime.now(timezone.utc)
    far_past = now - timedelta(days=100 * 365)
    # อายุเกินไปมาก ต้องไม่ติดลบ
    assert equipment_service.current_quality(100.0, far_past, 4, 0, 50, 4, now=now) == 0.0
    # baseline ที่ยังไม่ผ่านเวลาเลยต้องไม่เกิน 100
    assert equipment_service.current_quality(100.0, now, 4, 0, 50, 4, now=now) == 100.0


def test_current_quality_uses_default_life_years_when_unit_has_none():
    now = datetime.now(timezone.utc)
    one_year_ago = now - timedelta(days=365)
    # ไม่ตั้ง useful_life_years เฉพาะหน่วย (None) → ใช้ life_years_default (4) เหมือนตัวอย่างข้างบน
    q = equipment_service.current_quality(100.0, one_year_ago, None, 0, 50, 4, now=now)
    assert q == 87.5


# ── นับวันถูกยืมหลังวันประเมิน (quality_usage_days_map) ─────────────────────────

QUALITY_TAG = "QUALTEST"


@pytest_asyncio.fixture(loop_scope="session")
async def tracked_equipment():
    """ครุภัณฑ์ 1 ชิ้น เปิดติดตามคุณภาพ ยังไม่เคยประเมิน"""
    eq_id = uuid.uuid4()
    async with AsyncSessionLocal() as db:
        db.add(Equipment(
            id=eq_id, code=f"TEST-{QUALITY_TAG}-{eq_id.hex[:6].upper()}", name="โน้ตบุ๊กทดสอบคุณภาพ",
            item_type="durable", quantity_total=1, quantity_available=1, status="available",
            unit_value=20000, acquired_at=date(2020, 1, 1),
            quality_tracked=True, quality_life_years=4,
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
        for ids in (req_ids, item_ids, [eq_id]):
            if ids:
                await db.execute(delete(AuditLog).where(AuditLog.target_id.in_(ids)))
        if req_ids:
            await db.execute(delete(Notification).where(Notification.borrow_request_id.in_(req_ids)))
        await db.execute(delete(BorrowItem).where(BorrowItem.equipment_id == eq_id))
        if req_ids:
            await db.execute(delete(BorrowRequest).where(BorrowRequest.id.in_(req_ids)))
        await db.execute(delete(Equipment).where(Equipment.id == eq_id))
        await db.commit()


@pytest.mark.asyncio(loop_scope="session")
async def test_quality_usage_days_map_counts_only_after_baseline(
    test_admin: User, test_student: User, tracked_equipment,
):
    """ยืม-คืนก่อนวันประเมิน → นับ 0 (ไม่ใช่ 1) · ยืมคาบเกี่ยววันประเมิน → นับเฉพาะช่วงหลังวันประเมิน"""
    eq_id = tracked_equipment
    now = datetime.now(timezone.utc)
    baseline_at = now - timedelta(days=10)

    async with AsyncSessionLocal() as db:
        eq = await db.get(Equipment, eq_id)
        eq.quality_baseline = 100.0
        eq.quality_baseline_at = baseline_at
        await db.commit()

    # รายการที่คืนไปแล้ว "ก่อน" วันประเมิน (ทั้งช่วงอยู่ก่อน since) — ต้องนับ 0
    old_req_id, old_item_id = uuid.uuid4(), uuid.uuid4()
    async with AsyncSessionLocal() as db:
        db.add(BorrowRequest(
            id=old_req_id, request_code=f"REQ-{QUALITY_TAG}-OLD-{old_req_id.hex[:6]}",
            student_id=test_student.id, status="completed", purpose="ทดสอบ",
            requested_due_date=date(2099, 1, 1),
            approved_at=baseline_at - timedelta(days=20), approved_by=test_admin.id,
        ))
        db.add(BorrowItem(
            id=old_item_id, borrow_request_id=old_req_id, equipment_id=eq_id,
            item_type_snapshot="durable", quantity=1, item_status="approved",
            returned=True, returned_at=baseline_at - timedelta(days=15),
        ))
        await db.commit()

    async with AsyncSessionLocal() as db:
        usage = await equipment_service.quality_usage_days_map(db, [eq_id])
    assert usage.get(eq_id, 0) == 0, "ยืม-คืนเสร็จก่อนวันประเมินไปแล้วต้องไม่ถูกนับ"

    # รายการที่ยืมมาก่อนวันประเมิน แต่ยังไม่คืนจนหลังวันประเมิน 5 วัน — นับเฉพาะ 5 วันหลัง since
    straddle_req_id, straddle_item_id = uuid.uuid4(), uuid.uuid4()
    async with AsyncSessionLocal() as db:
        db.add(BorrowRequest(
            id=straddle_req_id, request_code=f"REQ-{QUALITY_TAG}-MID-{straddle_req_id.hex[:6]}",
            student_id=test_student.id, status="completed", purpose="ทดสอบ",
            requested_due_date=date(2099, 1, 1),
            approved_at=baseline_at - timedelta(days=3), approved_by=test_admin.id,
        ))
        db.add(BorrowItem(
            id=straddle_item_id, borrow_request_id=straddle_req_id, equipment_id=eq_id,
            item_type_snapshot="durable", quantity=1, item_status="approved",
            returned=True, returned_at=baseline_at + timedelta(days=5),
        ))
        await db.commit()

    async with AsyncSessionLocal() as db:
        usage = await equipment_service.quality_usage_days_map(db, [eq_id])
    assert usage.get(eq_id, 0) == 5, "ต้องนับเฉพาะช่วงหลังวันประเมิน ไม่ใช่ทั้งช่วงที่ยืมจริง"


# ── การประเมิน (assess_quality) + audit ─────────────────────────────────────────

@pytest.mark.asyncio(loop_scope="session")
async def test_manual_assess_endpoint_requires_reason_and_logs_audit(
    client: AsyncClient, admin_token: str, tracked_equipment,
):
    eq_id = tracked_equipment
    # ไม่ส่งเหตุผล → 422 (schema บังคับ min_length=1)
    missing_reason = await client.post(f"/equipment/{eq_id}/quality", headers=auth(admin_token),
                                       json={"quality_after": 90})
    assert missing_reason.status_code == 422

    r = await client.post(f"/equipment/{eq_id}/quality", headers=auth(admin_token),
                          json={"quality_after": 90, "reason": "ประเมินครั้งแรก"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["quality_baseline"] == 90.0
    assert body["current_quality"] == 90.0  # เพิ่งประเมิน ยังไม่มีเวลาผ่านไป

    async with AsyncSessionLocal() as db:
        log = (await db.execute(
            select(AuditLog).where(AuditLog.action == "assess_quality", AuditLog.target_id == eq_id)
            .order_by(AuditLog.created_at.desc())
        )).scalars().first()
        assert log is not None
        assert log.detail["event"] == "manual"
        assert log.detail["after"] == 90.0
        assert log.detail["before"] is None, "ยังไม่เคยประเมินมาก่อน ต้องเป็น None ไม่ใช่ 0"
        assert log.detail["reason"] == "ประเมินครั้งแรก"


@pytest.mark.asyncio(loop_scope="session")
async def test_assess_quality_rejects_untracked_equipment(client: AsyncClient, admin_token: str):
    eq_id = uuid.uuid4()
    async with AsyncSessionLocal() as db:
        db.add(Equipment(
            id=eq_id, code=f"TEST-{QUALITY_TAG}-UNTRACKED-{eq_id.hex[:6]}", name="อุปกรณ์ทดสอบไม่ติดตาม",
            item_type="durable", quantity_total=1, quantity_available=1, status="available",
        ))
        await db.commit()
    try:
        r = await client.post(f"/equipment/{eq_id}/quality", headers=auth(admin_token),
                              json={"quality_after": 50, "reason": "ทดสอบ"})
        assert r.status_code == 400
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(AuditLog).where(AuditLog.target_id == eq_id))
            await db.execute(delete(Equipment).where(Equipment.id == eq_id))
            await db.commit()


@pytest.mark.asyncio(loop_scope="session")
async def test_bulk_update_can_assess_whole_group(client: AsyncClient, admin_token: str):
    """เปิดติดตาม + ประเมินทั้งรุ่นพร้อมกันในคำขอเดียว — ต้องได้ audit assess_quality แยกทีละหน่วย"""
    tag = uuid.uuid4().hex[:6].upper()
    ids = [uuid.uuid4(), uuid.uuid4()]
    async with AsyncSessionLocal() as db:
        for i, eq_id in enumerate(ids):
            db.add(Equipment(
                id=eq_id, code=f"TEST-{QUALITY_TAG}-BULK-{tag}-{i}", name=f"ชุดทดสอบ bulk คุณภาพ {tag}",
                item_type="durable", quantity_total=1, quantity_available=1, status="available",
            ))
        await db.commit()
    try:
        r = await client.patch("/equipment/bulk-update", headers=auth(admin_token), json={
            "equipment_ids": [str(i) for i in ids],
            "update": {"quality_tracked": True, "quality_life_years": 3},
            "quality_baseline": 80, "quality_reason": "ประเมินทั้งรุ่นครั้งแรก",
        })
        assert r.status_code == 200, r.text
        updated = {u["id"]: u for u in r.json()["updated"]}
        for eq_id in ids:
            assert updated[str(eq_id)]["quality_tracked"] is True
            assert updated[str(eq_id)]["quality_baseline"] == 80.0

        async with AsyncSessionLocal() as db:
            logs = (await db.execute(
                select(AuditLog).where(AuditLog.action == "assess_quality", AuditLog.target_id.in_(ids))
            )).scalars().all()
            assert len(logs) == 2, "ต้อง log แยกทีละหน่วย ไม่ใช่รวมเป็น entry เดียว"
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(AuditLog).where(AuditLog.target_id.in_(ids)))
            await db.execute(delete(Equipment).where(Equipment.id.in_(ids)))
            await db.commit()


@pytest.mark.asyncio(loop_scope="session")
async def test_bulk_update_skips_quality_assess_for_untracked_rows_in_same_batch(
    client: AsyncClient, admin_token: str,
):
    """เลือกมาพร้อมกันปนรุ่นที่เปิด/ไม่เปิดติดตามได้ — แถวที่ไม่เปิดติดตามถูกข้ามแบบเงียบ ๆ ไม่ error ทั้ง batch"""
    tracked_id, untracked_id = uuid.uuid4(), uuid.uuid4()
    tag = uuid.uuid4().hex[:6].upper()
    async with AsyncSessionLocal() as db:
        db.add(Equipment(
            id=tracked_id, code=f"TEST-{QUALITY_TAG}-MIX-{tag}-A", name=f"ทดสอบผสม A {tag}",
            item_type="durable", quantity_total=1, quantity_available=1, status="available",
            quality_tracked=True,
        ))
        db.add(Equipment(
            id=untracked_id, code=f"TEST-{QUALITY_TAG}-MIX-{tag}-B", name=f"ทดสอบผสม B {tag}",
            item_type="durable", quantity_total=1, quantity_available=1, status="available",
        ))
        await db.commit()
    try:
        r = await client.patch("/equipment/bulk-update", headers=auth(admin_token), json={
            "equipment_ids": [str(tracked_id), str(untracked_id)],
            "update": {"location": "ตู้ทดสอบ"},
            "quality_baseline": 70, "quality_reason": "ทดสอบข้ามแถวที่ไม่เปิดติดตาม",
        })
        assert r.status_code == 200, r.text
        async with AsyncSessionLocal() as db:
            tracked_eq = await db.get(Equipment, tracked_id)
            untracked_eq = await db.get(Equipment, untracked_id)
            assert float(tracked_eq.quality_baseline) == 70.0
            assert untracked_eq.quality_baseline is None
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(AuditLog).where(AuditLog.target_id.in_([tracked_id, untracked_id])))
            await db.execute(delete(Equipment).where(Equipment.id.in_([tracked_id, untracked_id])))
            await db.commit()


@pytest.mark.asyncio(loop_scope="session")
async def test_install_part_can_assess_quality(client: AsyncClient, admin_token: str, tracked_equipment):
    eq_id = tracked_equipment
    async with AsyncSessionLocal() as db:
        eq = await db.get(Equipment, eq_id)
        eq.quality_baseline = 90.0
        eq.quality_baseline_at = datetime.now(timezone.utc)
        await db.commit()

    r = await client.post(f"/equipment/{eq_id}/parts", headers=auth(admin_token), json={
        "name": "RAM DDR4 16GB (ทดสอบ)", "acquired_at": str(date.today()),
        "quality_after": 88,
    })
    assert r.status_code == 201, r.text

    async with AsyncSessionLocal() as db:
        eq = await db.get(Equipment, eq_id)
        assert float(eq.quality_baseline) == 88.0
        log = (await db.execute(
            select(AuditLog).where(AuditLog.action == "assess_quality", AuditLog.target_id == eq_id)
        )).scalars().first()
        assert log is not None and log.detail["event"] == "install_part"


@pytest.mark.asyncio(loop_scope="session")
async def test_repair_complete_can_assess_quality(client: AsyncClient, admin_token: str, tracked_equipment):
    """สถานะเปลี่ยนจากชำรุดกลับเป็น available (ซ่อมเสร็จ) — ส่ง quality_after มาพร้อมกันได้"""
    eq_id = tracked_equipment
    async with AsyncSessionLocal() as db:
        eq = await db.get(Equipment, eq_id)
        eq.status = "under_repair"
        await db.commit()

    r = await client.patch(f"/equipment/{eq_id}", headers=auth(admin_token), json={
        "status": "available", "status_reason": "ซ่อมเสร็จแล้ว",
        "quality_after": 75, "quality_reason": "ซ่อมเสร็จ เปลี่ยนจอใหม่",
    })
    assert r.status_code == 200, r.text
    assert r.json()["quality_baseline"] == 75.0

    async with AsyncSessionLocal() as db:
        log = (await db.execute(
            select(AuditLog).where(AuditLog.action == "assess_quality", AuditLog.target_id == eq_id)
        )).scalars().first()
        assert log is not None and log.detail["event"] == "repair_complete"


@pytest.mark.asyncio(loop_scope="session")
async def test_return_damaged_can_assess_quality(
    client: AsyncClient, admin_token: str, test_admin: User, test_student: User, tracked_equipment,
):
    eq_id = tracked_equipment
    async with AsyncSessionLocal() as db:
        eq = await db.get(Equipment, eq_id)
        eq.quality_baseline = 90.0
        eq.quality_baseline_at = datetime.now(timezone.utc)
        await db.commit()

    req_id, item_id = uuid.uuid4(), uuid.uuid4()
    async with AsyncSessionLocal() as db:
        db.add(BorrowRequest(
            id=req_id, request_code=f"REQ-{QUALITY_TAG}-DMG-{req_id.hex[:6]}", student_id=test_student.id,
            status="pending", purpose="ทดสอบคืนแบบชำรุด", requested_due_date=date(2099, 1, 1),
        ))
        db.add(BorrowItem(id=item_id, borrow_request_id=req_id, equipment_id=eq_id,
                          item_type_snapshot="durable", quantity=1))
        await db.commit()
    async with AsyncSessionLocal() as db:
        admin = await db.get(User, test_admin.id)
        await borrow_service.approve_request(db, admin, req_id)

    r = await client.post(f"/borrow-requests/{req_id}/items/{item_id}/return", headers=auth(admin_token), json={
        "condition_on_return": "damaged",
        "damage_photo_urls": ["/uploads/fake-damage.jpg"],
        "quality_after": 50,
    })
    assert r.status_code == 200, r.text

    async with AsyncSessionLocal() as db:
        eq = await db.get(Equipment, eq_id)
        assert float(eq.quality_baseline) == 50.0
        log = (await db.execute(
            select(AuditLog).where(AuditLog.action == "assess_quality", AuditLog.target_id == eq_id)
        )).scalars().first()
        assert log is not None and log.detail["event"] == "return_damaged"


# ── นักศึกษาไม่เห็นค่าคุณภาพเลยสักฟิลด์ ──────────────────────────────────────────

@pytest.mark.asyncio(loop_scope="session")
async def test_student_never_sees_quality_fields(
    client: AsyncClient, admin_token: str, student_token: str, tracked_equipment,
):
    eq_id = tracked_equipment
    async with AsyncSessionLocal() as db:
        eq = await db.get(Equipment, eq_id)
        eq.quality_baseline = 90.0
        eq.quality_baseline_at = datetime.now(timezone.utc)
        await db.commit()

    # ต้องตรงกับ QUALITY_FIELDS ทั้งชุดใน equipment_service.py — เดิมขาด quality_life_years/
    # quality_remaining_life_years ไป 2 ตัว ทำให้เทสนี้ไม่เคยยืนยันว่า 2 ฟิลด์นั้นถูกซ่อนจริง
    # (แก้ตามรีวิวรอบ 3, MINOR-11)
    QUALITY_KEYS = (
        "quality_tracked", "quality_life_years", "quality_baseline", "quality_baseline_at",
        "current_quality", "quality_age_drop", "quality_usage_drop", "quality_needs_inspection",
        "quality_remaining_life_years",
    )

    # เจ้าหน้าที่ต้องเห็น
    admin_detail = (await client.get(f"/equipment/{eq_id}", headers=auth(admin_token))).json()
    assert admin_detail["quality_tracked"] is True
    assert admin_detail["current_quality"] == 90.0

    # นักศึกษาต้องไม่เห็นเลยสักฟิลด์
    student_detail = (await client.get(f"/equipment/{eq_id}", headers=auth(student_token))).json()
    for key in QUALITY_KEYS:
        assert student_detail.get(key) is None, f"นักศึกษาไม่ควรเห็น {key}"

    student_list = (await client.get("/equipment", params={"search": "โน้ตบุ๊กทดสอบคุณภาพ"},
                                     headers=auth(student_token))).json()
    matches = [i for i in student_list["items"] if i["id"] == str(eq_id)]
    assert matches, "ต้องเจออุปกรณ์ในผลค้นหา"
    for key in QUALITY_KEYS:
        assert matches[0].get(key) is None

    student_grouped = (await client.get("/equipment/grouped", params={"search": "โน้ตบุ๊กทดสอบคุณภาพ"},
                                        headers=auth(student_token))).json()
    g_matches = [i for i in student_grouped["items"] if i["id"] == str(eq_id)]
    assert g_matches
    for key in QUALITY_KEYS:
        assert g_matches[0].get(key) is None

    student_group_detail = (await client.get(f"/equipment/grouped/{eq_id}", headers=auth(student_token))).json()
    for key in QUALITY_KEYS:
        assert student_group_detail.get(key) is None
    for member in student_group_detail.get("members", []):
        for key in QUALITY_KEYS:
            assert member.get(key) is None


@pytest.mark.asyncio(loop_scope="session")
async def test_not_yet_assessed_shows_none_in_list(client: AsyncClient, admin_token: str, tracked_equipment):
    """เปิดติดตามแล้วแต่ยังไม่เคยประเมิน — เจ้าหน้าที่ต้องเห็น None ไม่ใช่ 0"""
    eq_id = tracked_equipment
    detail = (await client.get(f"/equipment/{eq_id}", headers=auth(admin_token))).json()
    assert detail["quality_tracked"] is True
    assert detail["quality_baseline"] is None
    assert detail["current_quality"] is None
    assert detail["quality_needs_inspection"] is False


# ── M1 (รีวิวรอบ 2): update_equipment propagate ไปทั้งรุ่น — เขียนเฉพาะที่เปลี่ยนจริง + audit แยก ──────────

@pytest_asyncio.fixture(loop_scope="session")
async def sibling_pair(client: AsyncClient, admin_token: str):
    """2 หน่วยชื่อ+ประเภทเดียวกัน (รุ่นเดียวกัน) ยังไม่เปิดติดตามคุณภาพเลยสักหน่วย"""
    tag = uuid.uuid4().hex[:6].upper()
    name = f"ทดสอบ M1 กลุ่มเดียวกัน {tag}"
    ids = []
    for i in range(2):
        r = await client.post("/equipment", headers=auth(admin_token), json={
            "code": f"{uuid.uuid4().int % 10**15:015d}", "name": name, "category_ids": [],
            "item_type": "durable", "quantity_total": 1, "image_urls": ["/uploads/test.jpg"],
            "unit_value": 1000, "acquired_at": "2024-01-15",
        })
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])
    yield ids
    async with AsyncSessionLocal() as db:
        uuids = [uuid.UUID(i) for i in ids]
        await db.execute(delete(AuditLog).where(AuditLog.target_id.in_(uuids)))
        await db.execute(delete(Equipment).where(Equipment.id.in_(uuids)))
        await db.commit()


@pytest.mark.asyncio(loop_scope="session")
async def test_update_equipment_propagates_quality_tracked_to_sibling_with_independent_audit(
    client: AsyncClient, admin_token: str, sibling_pair,
):
    eq_a, eq_b = sibling_pair
    r = await client.patch(f"/equipment/{eq_a}", headers=auth(admin_token), json={
        "quality_tracked": True, "quality_life_years": 3,
    })
    assert r.status_code == 200, r.text
    assert r.json()["quality_tracked"] is True

    async with AsyncSessionLocal() as db:
        sib = await db.get(Equipment, uuid.UUID(eq_b))
        assert sib.quality_tracked is True, "sibling ต้องได้สวิตช์ตามด้วย"
        assert sib.quality_life_years == 3

        logs = (await db.execute(
            select(AuditLog).where(AuditLog.action == "update_equipment", AuditLog.target_id == uuid.UUID(eq_a))
        )).scalars().all()
        group_logs = [l for l in logs if l.detail and "quality_group_change" in l.detail]
        assert len(group_logs) == 1, "ต้องมี audit แยกสำหรับผลกับทั้งรุ่น 1 entry"
        detail = group_logs[0].detail
        assert detail["quality_group_change"]["quality_tracked"] == [False, True]
        assert detail["quality_group_change"]["quality_life_years"] == [None, 3]
        assert sib.code in detail["affected_codes"]


@pytest.mark.asyncio(loop_scope="session")
async def test_update_equipment_resending_same_quality_values_does_not_touch_sibling_again(
    client: AsyncClient, admin_token: str, sibling_pair,
):
    """ส่งค่า quality_tracked/quality_life_years เดิมซ้ำ (เหมือนฟอร์มที่ไม่ได้แตะแท็บคุณภาพเลย แต่ backend
    ยังได้รับ field มาอยู่ดีถ้า frontend ไม่กรอง) ต้องไม่สร้าง audit "ผลกับทั้งรุ่น" ซ้ำอีก เพราะ sibling
    ไม่มีอะไรเปลี่ยนจริง (M1 — เขียนเฉพาะหน่วยที่ค่าจริงต่างเท่านั้น)"""
    eq_a, eq_b = sibling_pair
    first = await client.patch(f"/equipment/{eq_a}", headers=auth(admin_token), json={
        "quality_tracked": True, "quality_life_years": 3,
    })
    assert first.status_code == 200, first.text

    second = await client.patch(f"/equipment/{eq_a}", headers=auth(admin_token), json={
        "quality_tracked": True, "quality_life_years": 3, "location": "ตู้ใหม่ M1",
    })
    assert second.status_code == 200, second.text

    async with AsyncSessionLocal() as db:
        logs = (await db.execute(
            select(AuditLog).where(AuditLog.action == "update_equipment", AuditLog.target_id == uuid.UUID(eq_a))
        )).scalars().all()
        group_logs = [l for l in logs if l.detail and "quality_group_change" in l.detail]
        assert len(group_logs) == 1, \
            "ส่งค่าคุณภาพเดิมซ้ำ (sibling ตรงอยู่แล้ว) ต้องไม่มี audit ผลกับทั้งรุ่นเพิ่มอีก entry"


# ── MAJOR-1 (รีวิวรอบ 3): เปลี่ยนชื่อหน่วยเข้ารุ่นที่ติดตามอยู่แล้ว ─────────────────────────────────────

@pytest.mark.asyncio(loop_scope="session")
async def test_rename_untracked_unit_into_tracked_group_inherits_and_does_not_untrack_siblings(
    client: AsyncClient, admin_token: str,
):
    """เดิมมี 2 บั๊กซ้อนกัน: (a) ฟอร์มแก้ไขหน่วยเดียวส่ง quality_tracked/quality_life_years ติดไปกับทุกการ
    บันทึกเสมอ (`...form` ไม่มีเงื่อนไข) backend เดิมเห็นแค่ "มีอยู่ใน payload" ก็ propagate ค่านั้นทับทั้งรุ่น
    ทันที — หน่วยที่ยังไม่เคยติดตาม (quality_tracked=False) เปลี่ยนชื่อเข้ารุ่นที่ติดตามอยู่แล้วจะ "ลาก" ค่า
    False ไปทับ sibling ที่ติดตามอยู่ทั้งกลุ่มโดยไม่ตั้งใจ (b) หน่วยที่เปลี่ยนชื่อเข้ารุ่นใหม่เองก็ไม่เคยได้
    สวิตช์ตามรุ่นใหม่อัตโนมัติเหมือนตอนสร้างใหม่เลย — เทสนี้ยืนยันว่าทั้งสองจุดแก้แล้ว: หน่วยที่เปลี่ยนชื่อ
    เข้ารุ่นที่ติดตามอยู่แล้วต้องได้สวิตช์ตาม (b) และ sibling เดิมต้องไม่ถูกลากลงมาเป็น False ตามไปด้วย (a)
    """
    tag = uuid.uuid4().hex[:6].upper()
    tracked_name = f"ทดสอบ MAJOR1 รุ่นติดตาม {tag}"
    other_name = f"ทดสอบ MAJOR1 ของเก่ายังไม่ติดตาม {tag}"
    ids: list[str] = []
    try:
        # รุ่นที่เปิดติดตามคุณภาพแล้ว 2 หน่วย (หน่วยแรกเปิดเอง หน่วยที่สองสืบทอดสวิตช์ตอนสร้าง — M6)
        first = await client.post("/equipment", headers=auth(admin_token), json={
            "code": f"{uuid.uuid4().int % 10**15:015d}", "name": tracked_name, "category_ids": [],
            "item_type": "durable", "quantity_total": 1, "image_urls": ["/uploads/test.jpg"],
            "unit_value": 1000, "acquired_at": "2024-01-15",
        })
        assert first.status_code == 201, first.text
        eq_tracked_a = first.json()["id"]
        ids.append(eq_tracked_a)
        r = await client.patch(f"/equipment/{eq_tracked_a}", headers=auth(admin_token),
                               json={"quality_tracked": True, "quality_life_years": 4})
        assert r.status_code == 200, r.text

        second = await client.post("/equipment", headers=auth(admin_token), json={
            "code": f"{uuid.uuid4().int % 10**15:015d}", "name": tracked_name, "category_ids": [],
            "item_type": "durable", "quantity_total": 1, "image_urls": ["/uploads/test.jpg"],
            "unit_value": 1000, "acquired_at": "2024-01-15",
        })
        assert second.status_code == 201, second.text
        eq_tracked_b = second.json()["id"]
        ids.append(eq_tracked_b)
        assert second.json()["quality_tracked"] is True

        # หน่วยแยกต่างหากคนละรุ่น ยังไม่เคยเปิดติดตามคุณภาพเลย
        third = await client.post("/equipment", headers=auth(admin_token), json={
            "code": f"{uuid.uuid4().int % 10**15:015d}", "name": other_name, "category_ids": [],
            "item_type": "durable", "quantity_total": 1, "image_urls": ["/uploads/test.jpg"],
            "unit_value": 1000, "acquired_at": "2024-01-15",
        })
        assert third.status_code == 201, third.text
        eq_old = third.json()["id"]
        ids.append(eq_old)
        assert third.json()["quality_tracked"] is False

        # เปลี่ยนชื่อหน่วยที่ยังไม่ติดตาม ให้เข้ารุ่นที่ติดตามอยู่แล้ว — ไม่ส่ง quality_tracked มาเลย
        # (จำลองฟอร์มที่แก้ตาม MAJOR-1c แล้ว ไม่ spread ค่าเดิมมาด้วยอีกต่อไป)
        renamed = await client.patch(f"/equipment/{eq_old}", headers=auth(admin_token),
                                     json={"name": tracked_name})
        assert renamed.status_code == 200, renamed.text
        assert renamed.json()["quality_tracked"] is True, \
            "หน่วยที่เปลี่ยนชื่อเข้ารุ่นที่ติดตามแล้วต้องได้สวิตช์ตามอัตโนมัติ"
        assert renamed.json()["quality_life_years"] == 4

        async with AsyncSessionLocal() as db:
            sib_a = await db.get(Equipment, uuid.UUID(eq_tracked_a))
            sib_b = await db.get(Equipment, uuid.UUID(eq_tracked_b))
            assert sib_a.quality_tracked is True, "sibling เดิมต้องไม่ถูกลากลงมาเป็น False"
            assert sib_b.quality_tracked is True, "sibling เดิมต้องไม่ถูกลากลงมาเป็น False"
    finally:
        async with AsyncSessionLocal() as db:
            uuids = [uuid.UUID(i) for i in ids]
            await db.execute(delete(AuditLog).where(AuditLog.target_id.in_(uuids)))
            await db.execute(delete(Equipment).where(Equipment.id.in_(uuids)))
            await db.commit()


# ── M-a (รีวิวรอบ 4): inherit ต้องดูสถานะ "ทั้งกลุ่มปลายทาง" ไม่ใช่แค่ "มีใครสักคนติดตาม" ──────────────────
# เดิม _inherit_quality_from_group คืน True แค่เพราะเจอ sibling ที่ tracked=True สักตัว (ไม่ต้องครบกลุ่ม)
# และคืน None เฉย ๆ ตอนกลุ่มปลายทาง "ไม่มีใครติดตามเลย" (หน่วยที่ย้ายเข้ามาเลยคงค่าตัวเองไว้) — หน่วยที่เคย
# ติดตามย้ายเข้ารุ่นที่ปนกัน/ไม่ติดตามเลยจะ "ค้างติดตาม" อยู่คนเดียวในรุ่นใหม่ (กลายเป็นกลุ่มปนกัน — mixed)
# แล้วคนถัดไปที่ย้ายเข้ามาอีกจะ inherit True จากมันซ้ำอีกทอด ลาม tracked ทั้งรุ่นโดยไม่ตั้งใจ

@pytest.mark.asyncio(loop_scope="session")
async def test_rename_tracked_unit_into_untracked_group_becomes_untracked_and_leaves_siblings(
    client: AsyncClient, admin_token: str,
):
    """หน่วยที่เคยติดตาม+ประเมินแล้ว ย้ายชื่อเข้ารุ่นที่ไม่มีใครติดตามเลย (กลุ่มปลายทางมีหน่วยอื่นอยู่จริง
    แค่ไม่มีใครเปิดติดตาม) ต้องได้ False ตามกลุ่มปลายทางอัตโนมัติ (ไม่ใช่ "ไม่มีกลุ่มปลายทางเลยคงค่าเดิม")
    และ sibling ของกลุ่มปลายทางต้องไม่ถูกแตะเลย"""
    tag = uuid.uuid4().hex[:6].upper()
    untracked_name = f"ทดสอบ M-a กลุ่มไม่ติดตาม {tag}"
    tracked_name = f"ทดสอบ M-a หน่วยเดี่ยวติดตาม {tag}"
    ids: list[str] = []
    try:
        # กลุ่มปลายทาง 2 หน่วย ไม่มีใครเปิดติดตามเลยสักตัว
        b1 = await client.post("/equipment", headers=auth(admin_token), json={
            "code": f"{uuid.uuid4().int % 10**15:015d}", "name": untracked_name, "category_ids": [],
            "item_type": "durable", "quantity_total": 1, "image_urls": ["/uploads/test.jpg"],
            "unit_value": 1000, "acquired_at": "2024-01-15",
        })
        assert b1.status_code == 201, b1.text
        ids.append(b1.json()["id"])
        b2 = await client.post("/equipment", headers=auth(admin_token), json={
            "code": f"{uuid.uuid4().int % 10**15:015d}", "name": untracked_name, "category_ids": [],
            "item_type": "durable", "quantity_total": 1, "image_urls": ["/uploads/test.jpg"],
            "unit_value": 1000, "acquired_at": "2024-01-15",
        })
        assert b2.status_code == 201, b2.text
        ids.append(b2.json()["id"])
        assert b1.json()["quality_tracked"] is False and b2.json()["quality_tracked"] is False

        # หน่วยแยกต่างหาก เปิดติดตาม + ประเมินแล้ว
        x = await client.post("/equipment", headers=auth(admin_token), json={
            "code": f"{uuid.uuid4().int % 10**15:015d}", "name": tracked_name, "category_ids": [],
            "item_type": "durable", "quantity_total": 1, "image_urls": ["/uploads/test.jpg"],
            "unit_value": 1000, "acquired_at": "2024-01-15",
        })
        assert x.status_code == 201, x.text
        eq_x = x.json()["id"]
        ids.append(eq_x)
        patched_x = await client.patch(f"/equipment/{eq_x}", headers=auth(admin_token),
                                       json={"quality_tracked": True, "quality_life_years": 4})
        assert patched_x.status_code == 200, patched_x.text

        # ย้าย X เข้ากลุ่มที่ไม่มีใครติดตามเลย — ไม่ส่ง quality_tracked มาเอง
        renamed = await client.patch(f"/equipment/{eq_x}", headers=auth(admin_token),
                                     json={"name": untracked_name})
        assert renamed.status_code == 200, renamed.text
        assert renamed.json()["quality_tracked"] is False, \
            "ย้ายเข้ากลุ่มที่ไม่มีใครติดตามเลยต้องได้ False ตามกลุ่มปลายทาง ไม่ใช่ค้างค่าติดตามเดิม"
        assert renamed.json()["quality_life_years"] is None

        async with AsyncSessionLocal() as db:
            sib1 = await db.get(Equipment, uuid.UUID(b1.json()["id"]))
            sib2 = await db.get(Equipment, uuid.UUID(b2.json()["id"]))
            assert sib1.quality_tracked is False, "sibling ของกลุ่มปลายทางต้องไม่ถูกแตะเลย"
            assert sib2.quality_tracked is False, "sibling ของกลุ่มปลายทางต้องไม่ถูกแตะเลย"
    finally:
        async with AsyncSessionLocal() as db:
            uuids = [uuid.UUID(i) for i in ids]
            await db.execute(delete(AuditLog).where(AuditLog.target_id.in_(uuids)))
            await db.execute(delete(Equipment).where(Equipment.id.in_(uuids)))
            await db.commit()


@pytest.mark.asyncio(loop_scope="session")
async def test_rename_untracked_unit_into_mixed_group_becomes_untracked_no_sibling_changes(
    client: AsyncClient, admin_token: str,
):
    """กลุ่มปลายทาง "ปนกัน" (มีทั้งติดตามและไม่ติดตาม) — หน่วยที่ย้ายเข้ามาต้องได้ False (ไม่ครบทั้งกลุ่ม
    ถือว่ายังไม่ติดตาม) และ sibling ทั้งสองฝั่งในกลุ่มปลายทางต้องไม่ถูกแตะเลย (ไม่ propagate ต่อ)

    สร้างกลุ่มปนกันตรงผ่าน ORM (ข้าม service layer) แทนการเปิด/ปิดผ่าน PATCH ตามลำดับ — ถ้าเปิด/ปิดผ่าน
    PATCH ตรง ๆ (explicit_quality_request) ค่านั้นจะ propagate ทับทั้งกลุ่มเสมอตามที่ตั้งใจไว้ (พฤติกรรมเดิม
    ที่ถูกต้องอยู่แล้ว ไม่เกี่ยวกับ M-a) ทำให้สร้างกลุ่ม "ปนกันจริง" ผ่าน API ไม่ได้เลย — กลุ่มปนกันเกิดได้จริง
    จากข้อมูลเก่า/นำเข้าตรง ๆ ก่อนมีการบังคับ consistency นี้
    """
    tag = uuid.uuid4().hex[:6].upper()
    mixed_name = f"ทดสอบ M-a กลุ่มปนกัน {tag}"
    outside_name = f"ทดสอบ M-a หน่วยนอกกลุ่มยังไม่ติดตาม {tag}"
    eq_m1, eq_m2 = uuid.uuid4(), uuid.uuid4()
    ids: list[str] = [str(eq_m1), str(eq_m2)]
    try:
        async with AsyncSessionLocal() as db:
            db.add(Equipment(
                id=eq_m1, code=f"TEST-{QUALITY_TAG}-MIXED-{tag}-A", name=mixed_name,
                item_type="durable", quantity_total=1, quantity_available=1, status="available",
                quality_tracked=True, quality_life_years=3,
            ))
            db.add(Equipment(
                id=eq_m2, code=f"TEST-{QUALITY_TAG}-MIXED-{tag}-B", name=mixed_name,
                item_type="durable", quantity_total=1, quantity_available=1, status="available",
                quality_tracked=False,
            ))
            await db.commit()

        y = await client.post("/equipment", headers=auth(admin_token), json={
            "code": f"{uuid.uuid4().int % 10**15:015d}", "name": outside_name, "category_ids": [],
            "item_type": "durable", "quantity_total": 1, "image_urls": ["/uploads/test.jpg"],
            "unit_value": 1000, "acquired_at": "2024-01-15",
        })
        assert y.status_code == 201, y.text
        eq_y = y.json()["id"]
        ids.append(eq_y)
        assert y.json()["quality_tracked"] is False

        renamed_y = await client.patch(f"/equipment/{eq_y}", headers=auth(admin_token),
                                       json={"name": mixed_name})
        assert renamed_y.status_code == 200, renamed_y.text
        assert renamed_y.json()["quality_tracked"] is False, \
            "กลุ่มปลายทางปนกัน (ไม่ครบทั้งกลุ่ม) ต้องได้ False"

        async with AsyncSessionLocal() as db:
            sib_m1 = await db.get(Equipment, eq_m1)
            sib_m2 = await db.get(Equipment, eq_m2)
            assert sib_m1.quality_tracked is True and sib_m1.quality_life_years == 3, \
                "sibling ที่เคยติดตามอยู่ก่อนต้องไม่ถูกแตะ"
            assert sib_m2.quality_tracked is False, "sibling ที่ไม่ติดตามอยู่ก่อนต้องไม่ถูกแตะ"
    finally:
        async with AsyncSessionLocal() as db:
            uuids = [uuid.UUID(i) for i in ids]
            await db.execute(delete(AuditLog).where(AuditLog.target_id.in_(uuids)))
            await db.execute(delete(Equipment).where(Equipment.id.in_(uuids)))
            await db.commit()


@pytest.mark.asyncio(loop_scope="session")
async def test_rename_with_explicit_unchanged_false_null_does_not_drag_target_group(
    client: AsyncClient, admin_token: str,
):
    """MAJOR-1a payload shape: เปลี่ยนชื่อเข้ารุ่นที่ติดตามอยู่แล้ว พร้อมส่ง quality_tracked=false,
    quality_life_years=null มาตรง ๆ ในคำขอเดียวกัน (ค่าที่ส่งตรงกับค่าเดิมของหน่วยนี้เป๊ะ — ฟอร์มที่ยังไม่ได้
    แก้ตาม MAJOR-1c ส่งค่าเดิมติดมาด้วยทุกครั้ง) — explicit เสมอชนะ inherit (ไม่ inherit True ตามกลุ่มปลายทาง)
    และเทียบกับค่าเดิมของหน่วยนี้เองแล้วไม่เปลี่ยนจริง จึงต้องไม่ลาก sibling ของกลุ่มปลายทางลงมาเป็น False"""
    tag = uuid.uuid4().hex[:6].upper()
    tracked_name = f"ทดสอบ MAJOR1a กลุ่มติดตาม {tag}"
    outside_name = f"ทดสอบ MAJOR1a หน่วยนอกกลุ่ม {tag}"
    ids: list[str] = []
    try:
        t1 = await client.post("/equipment", headers=auth(admin_token), json={
            "code": f"{uuid.uuid4().int % 10**15:015d}", "name": tracked_name, "category_ids": [],
            "item_type": "durable", "quantity_total": 1, "image_urls": ["/uploads/test.jpg"],
            "unit_value": 1000, "acquired_at": "2024-01-15",
        })
        assert t1.status_code == 201, t1.text
        eq_t1 = t1.json()["id"]
        ids.append(eq_t1)
        patched_t1 = await client.patch(f"/equipment/{eq_t1}", headers=auth(admin_token),
                                        json={"quality_tracked": True, "quality_life_years": 5})
        assert patched_t1.status_code == 200, patched_t1.text

        z = await client.post("/equipment", headers=auth(admin_token), json={
            "code": f"{uuid.uuid4().int % 10**15:015d}", "name": outside_name, "category_ids": [],
            "item_type": "durable", "quantity_total": 1, "image_urls": ["/uploads/test.jpg"],
            "unit_value": 1000, "acquired_at": "2024-01-15",
        })
        assert z.status_code == 201, z.text
        eq_z = z.json()["id"]
        ids.append(eq_z)
        assert z.json()["quality_tracked"] is False

        renamed_z = await client.patch(f"/equipment/{eq_z}", headers=auth(admin_token), json={
            "name": tracked_name, "quality_tracked": False, "quality_life_years": None,
        })
        assert renamed_z.status_code == 200, renamed_z.text
        assert renamed_z.json()["quality_tracked"] is False, \
            "ส่ง quality_tracked=false มาตรง ๆ ต้องชนะ inherit เสมอ ไม่ใช่ True ตามกลุ่มปลายทาง"

        async with AsyncSessionLocal() as db:
            sib_t1 = await db.get(Equipment, uuid.UUID(eq_t1))
            assert sib_t1.quality_tracked is True and sib_t1.quality_life_years == 5, \
                "sibling ของกลุ่มปลายทางต้องไม่ถูกลากลงมาเป็น False"

            logs = (await db.execute(
                select(AuditLog).where(AuditLog.action == "update_equipment", AuditLog.target_id == uuid.UUID(eq_z))
            )).scalars().all()
            group_logs = [l for l in logs if l.detail and "quality_group_change" in l.detail]
            assert not group_logs, "ค่าไม่เปลี่ยนจริง (ตรงกับค่าเดิมของหน่วยนี้) ต้องไม่มี audit ผลกับทั้งรุ่น"
    finally:
        async with AsyncSessionLocal() as db:
            uuids = [uuid.UUID(i) for i in ids]
            await db.execute(delete(AuditLog).where(AuditLog.target_id.in_(uuids)))
            await db.execute(delete(Equipment).where(Equipment.id.in_(uuids)))
            await db.commit()


@pytest.mark.asyncio(loop_scope="session")
async def test_bulk_rename_into_tracked_group_inherits_and_is_audited(
    client: AsyncClient, admin_token: str,
):
    """แก้หลายหน่วยพร้อมกัน (bulk) เปลี่ยนชื่อเข้ารุ่นที่ติดตามอยู่แล้ว โดยไม่ส่ง quality_tracked มาเอง —
    ต้อง inherit ให้หน่วยที่ย้ายเข้ามาเท่านั้น (ไม่ propagate ต่อ sibling ต้นทาง) และต้องโผล่ใน audit
    "bulk_update_equipment" (M-e) ไม่ใช่เงียบหายไปเหมือนเดิม"""
    tag = uuid.uuid4().hex[:6].upper()
    tracked_name = f"ทดสอบ M-a bulk กลุ่มติดตาม {tag}"
    moving_name = f"ทดสอบ M-a bulk หน่วยที่จะย้าย {tag}"
    ids: list[str] = []
    try:
        g1 = await client.post("/equipment", headers=auth(admin_token), json={
            "code": f"{uuid.uuid4().int % 10**15:015d}", "name": tracked_name, "category_ids": [],
            "item_type": "durable", "quantity_total": 1, "image_urls": ["/uploads/test.jpg"],
            "unit_value": 1000, "acquired_at": "2024-01-15",
        })
        assert g1.status_code == 201, g1.text
        eq_g1 = g1.json()["id"]
        ids.append(eq_g1)
        patched_g1 = await client.patch(f"/equipment/{eq_g1}", headers=auth(admin_token),
                                        json={"quality_tracked": True, "quality_life_years": 6})
        assert patched_g1.status_code == 200, patched_g1.text

        movers = []
        for _ in range(2):
            m = await client.post("/equipment", headers=auth(admin_token), json={
                "code": f"{uuid.uuid4().int % 10**15:015d}", "name": moving_name, "category_ids": [],
                "item_type": "durable", "quantity_total": 1, "image_urls": ["/uploads/test.jpg"],
                "unit_value": 1000, "acquired_at": "2024-01-15",
            })
            assert m.status_code == 201, m.text
            movers.append(m.json()["id"])
            ids.append(m.json()["id"])
            assert m.json()["quality_tracked"] is False

        bulk = await client.patch("/equipment/bulk-update", headers=auth(admin_token), json={
            "equipment_ids": movers, "update": {"name": tracked_name},
        })
        assert bulk.status_code == 200, bulk.text
        for u in bulk.json()["updated"]:
            assert u["quality_tracked"] is True, "หน่วยที่ย้ายเข้ารุ่นที่ติดตามอยู่แล้วต้อง inherit True"
            assert u["quality_life_years"] == 6

        async with AsyncSessionLocal() as db:
            sib_g1 = await db.get(Equipment, uuid.UUID(eq_g1))
            assert sib_g1.quality_tracked is True and sib_g1.quality_life_years == 6, \
                "sibling ต้นทางของกลุ่มติดตามต้องไม่ถูกแตะจากการ inherit ของหน่วยที่ย้ายเข้ามา"

            logs = (await db.execute(
                select(AuditLog).where(
                    AuditLog.action == "bulk_update_equipment",
                    AuditLog.target_id == uuid.UUID(movers[0]),
                )
            )).scalars().all()
            assert logs, "ต้องมี audit bulk_update_equipment"
            inherited_logged = logs[-1].detail.get("set", {}).get("quality_inherited")
            assert inherited_logged, "การ inherit อัตโนมัติตอน bulk ต้องโผล่ใน audit (M-e)"
            logged_codes = {row["code"] for row in inherited_logged}
            expected_codes = {(await db.get(Equipment, uuid.UUID(i))).code for i in movers}
            assert logged_codes == expected_codes
            for row in inherited_logged:
                assert row["quality_tracked"] == [False, True]
                assert row["quality_life_years"] == [None, 6]
    finally:
        async with AsyncSessionLocal() as db:
            uuids = [uuid.UUID(i) for i in ids]
            await db.execute(delete(AuditLog).where(AuditLog.target_id.in_(uuids)))
            await db.execute(delete(Equipment).where(Equipment.id.in_(uuids)))
            await db.commit()


async def _mk_durable(client: AsyncClient, token: str, name: str, ids: list[str], **quality) -> str:
    r = await client.post("/equipment", headers=auth(token), json={
        "code": f"{uuid.uuid4().int % 10**15:015d}", "name": name, "category_ids": [],
        "item_type": "durable", "quantity_total": 1, "image_urls": ["/uploads/test.jpg"],
        "unit_value": 1000, "acquired_at": "2024-01-15",
    })
    assert r.status_code == 201, r.text
    ids.append(r.json()["id"])
    if quality:
        p = await client.patch(f"/equipment/{ids[-1]}", headers=auth(token), json=quality)
        assert p.status_code == 200, p.text
    return ids[-1]


async def _cleanup_equipment(ids: list[str]) -> None:
    async with AsyncSessionLocal() as db:
        uuids = [uuid.UUID(i) for i in ids]
        await db.execute(delete(AuditLog).where(AuditLog.target_id.in_(uuids)))
        await db.execute(delete(Equipment).where(Equipment.id.in_(uuids)))
        await db.commit()


@pytest.mark.asyncio(loop_scope="session")
async def test_rename_with_only_life_years_still_inherits_tracked(client: AsyncClient, admin_token: str):
    """เปลี่ยนชื่อเข้ารุ่นที่ติดตามทั้งรุ่น + ส่ง quality_life_years มาเองอย่างเดียว → quality_tracked ยังต้อง
    inherit True (ตัดสินรายฟิลด์) ไม่งั้นเหลือหน่วยไม่ติดตามค้างในรุ่นที่ติดตาม (รีวิวรอบ 4 MINOR ข้อ 2)"""
    tag = uuid.uuid4().hex[:6].upper()
    tracked_name = f"ทดสอบ รายฟิลด์ กลุ่มติดตาม {tag}"
    ids: list[str] = []
    try:
        await _mk_durable(client, admin_token, tracked_name, ids, quality_tracked=True, quality_life_years=5)
        z = await _mk_durable(client, admin_token, f"ทดสอบ รายฟิลด์ นอกกลุ่ม {tag}", ids)
        r = await client.patch(f"/equipment/{z}", headers=auth(admin_token),
                               json={"name": tracked_name, "quality_life_years": 7})
        assert r.status_code == 200, r.text
        assert r.json()["quality_tracked"] is True
        assert r.json()["quality_life_years"] == 7, "ค่าที่ส่งมาเองต้องชนะ inherit"
    finally:
        await _cleanup_equipment(ids)


@pytest.mark.asyncio(loop_scope="session")
async def test_bulk_rename_into_empty_group_does_not_depend_on_row_order(
    client: AsyncClient, admin_token: str,
):
    """bulk เปลี่ยนชื่อ 2 หน่วย (ติดตาม/ไม่ติดตาม) เข้ารุ่นใหม่ที่ยังไม่มีใคร → ต่างคนต่างคงค่าเดิม
    เดิมถามทีละแถวหลัง setattr แถวหลังเลย inherit จากแถวแรกที่เพิ่งย้ายเข้าไป ผลขึ้นกับลำดับ (MINOR ข้อ 1)"""
    tag = uuid.uuid4().hex[:6].upper()
    ids: list[str] = []
    try:
        a = await _mk_durable(client, admin_token, f"ทดสอบ ลำดับ A {tag}", ids,
                              quality_tracked=True, quality_life_years=4)
        b = await _mk_durable(client, admin_token, f"ทดสอบ ลำดับ B {tag}", ids)
        r = await client.patch("/equipment/bulk-update", headers=auth(admin_token), json={
            "equipment_ids": [a, b], "update": {"name": f"ทดสอบ ลำดับ ปลายทาง {tag}"},
        })
        assert r.status_code == 200, r.text
        got = {u["id"]: u["quality_tracked"] for u in r.json()["updated"]}
        assert got == {a: True, b: False}
    finally:
        await _cleanup_equipment(ids)


# ── M-g (รีวิวรอบ 4): quality_tracked ห้ามส่ง null ตรง ๆ (คอลัมน์ NOT NULL — จะได้ 422 ไม่ใช่ 500) ──────────

@pytest.mark.asyncio(loop_scope="session")
async def test_update_equipment_rejects_explicit_null_quality_tracked(
    client: AsyncClient, admin_token: str,
):
    tag = uuid.uuid4().hex[:6].upper()
    created = await client.post("/equipment", headers=auth(admin_token), json={
        "code": f"{uuid.uuid4().int % 10**15:015d}", "name": f"ทดสอบ M-g null คุณภาพ {tag}",
        "category_ids": [], "item_type": "durable", "quantity_total": 1,
        "image_urls": ["/uploads/test.jpg"], "unit_value": 1000, "acquired_at": "2024-01-15",
    })
    assert created.status_code == 201, created.text
    eq_id = created.json()["id"]
    try:
        r = await client.patch(f"/equipment/{eq_id}", headers=auth(admin_token),
                               json={"quality_tracked": None})
        assert r.status_code == 422, r.text
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(AuditLog).where(AuditLog.target_id == uuid.UUID(eq_id)))
            await db.execute(delete(Equipment).where(Equipment.id == uuid.UUID(eq_id)))
            await db.commit()


# ── สืบทอดสวิตช์ติดตามคุณภาพให้หน่วยใหม่ของรุ่นเดิม (M6 — create + split) ────────────────────────────────

@pytest.mark.asyncio(loop_scope="session")
async def test_new_equipment_inherits_quality_tracking_from_tracked_sibling(
    client: AsyncClient, admin_token: str,
):
    tag = uuid.uuid4().hex[:6].upper()
    name = f"ทดสอบสืบทอดคุณภาพตอนสร้าง {tag}"
    first = await client.post("/equipment", headers=auth(admin_token), json={
        "code": f"{uuid.uuid4().int % 10**15:015d}", "name": name, "category_ids": [],
        "item_type": "durable", "quantity_total": 1, "image_urls": ["/uploads/test.jpg"],
        "unit_value": 1000, "acquired_at": "2024-01-15",
    })
    assert first.status_code == 201, first.text
    eq_a = first.json()["id"]
    ids = [eq_a]
    try:
        await client.patch(f"/equipment/{eq_a}", headers=auth(admin_token),
                           json={"quality_tracked": True, "quality_life_years": 5})

        second = await client.post("/equipment", headers=auth(admin_token), json={
            "code": f"{uuid.uuid4().int % 10**15:015d}", "name": name, "category_ids": [],
            "item_type": "durable", "quantity_total": 1, "image_urls": ["/uploads/test.jpg"],
            "unit_value": 1000, "acquired_at": "2024-01-15",
        })
        assert second.status_code == 201, second.text
        ids.append(second.json()["id"])
        assert second.json()["quality_tracked"] is True, "หน่วยใหม่ของรุ่นที่เปิดติดตามแล้วต้องได้สวิตช์ตามอัตโนมัติ"
        assert second.json()["quality_life_years"] == 5
    finally:
        async with AsyncSessionLocal() as db:
            uuids = [uuid.UUID(i) for i in ids]
            await db.execute(delete(AuditLog).where(AuditLog.target_id.in_(uuids)))
            await db.execute(delete(Equipment).where(Equipment.id.in_(uuids)))
            await db.commit()


@pytest.mark.asyncio(loop_scope="session")
async def test_split_equipment_inherits_quality_tracking_but_not_baseline(
    client: AsyncClient, admin_token: str,
):
    tag = uuid.uuid4().hex[:6].upper()
    created = await client.post("/equipment", headers=auth(admin_token), json={
        "code": f"{uuid.uuid4().int % 10**15:015d}", "name": f"ทดสอบแยกรายชิ้นสืบทอดคุณภาพ {tag}",
        "category_ids": [], "item_type": "material", "quantity_total": 3,
        "image_urls": ["/uploads/test.jpg"], "unit_value": 300, "acquired_at": "2024-01-15",
    })
    assert created.status_code == 201, created.text
    eq_id = created.json()["id"]
    ids = [eq_id]
    try:
        patched = await client.patch(f"/equipment/{eq_id}", headers=auth(admin_token), json={
            "quality_tracked": True, "quality_life_years": 2,
        })
        assert patched.status_code == 200, patched.text
        async with AsyncSessionLocal() as db:
            eq = await db.get(Equipment, uuid.UUID(eq_id))
            eq.quality_baseline = 80.0
            eq.quality_baseline_at = datetime.now(timezone.utc)
            await db.commit()

        split = await client.post(f"/equipment/{eq_id}/split", headers=auth(admin_token))
        assert split.status_code == 200, split.text
        units = split.json()
        # เก็บ id ทุกหน่วยไว้ cleanup ก่อนเริ่ม assert — กัน finally เก็บไม่ครบถ้า assert พังกลางลูป
        # (id ตัวไหนซ้ำกับ eq_id เดิมไม่เป็นไร ลบซ้ำได้)
        ids.extend(u["id"] for u in units if u["id"] not in ids)
        assert len(units) == 3
        for u in units:
            assert u["quality_tracked"] is True, "หน่วยที่แยกออกมาต้องได้สวิตช์ตามรุ่นเดิม"
            assert u["quality_life_years"] == 2
            if u["id"] == eq_id:
                # แถวต้นฉบับ (หดเหลือ quantity_total=1 กลายเป็นหน่วยที่ 1) ยังเป็นของจริงชิ้นเดิม —
                # baseline ที่เคยประเมินไว้ต้องไม่หายไป
                assert u["quality_baseline"] == 80.0
            else:
                # หน่วยใหม่ที่ clone ออกมาเป็นของจริงแยกกันแล้ว ต้องประเมินใหม่เอง ไม่ copy baseline ของ
                # แถวต้นฉบับมาด้วย (ดู comment ใน split_equipment_into_units)
                assert u["quality_baseline"] is None, "หน่วยที่ clone ใหม่ไม่ควร copy baseline มา"
    finally:
        async with AsyncSessionLocal() as db:
            uuids = [uuid.UUID(i) for i in ids]
            await db.execute(delete(AuditLog).where(AuditLog.target_id.in_(uuids)))
            await db.execute(delete(Equipment).where(Equipment.id.in_(uuids)))
            await db.commit()


# ── MINOR-8 (รีวิวรอบ 3): เปิดติดตามคุณภาพได้เฉพาะ durable/material เท่านั้น ─────────────────────────────

@pytest.mark.asyncio(loop_scope="session")
async def test_enable_quality_tracking_on_consumable_rejected(client: AsyncClient, admin_token: str):
    """consumable หลายแถวมีชื่อซ้ำกันได้โดยตั้งใจ (คนละล็อต) เปิดติดตามแล้ว propagate ตามชื่อจะไปแตะแถวที่
    ไม่เกี่ยวข้องกันจริง — ต้องถูกปฏิเสธด้วย 400 ตั้งแต่จุดเดียว (`_assert_quality_trackable`)"""
    tag = uuid.uuid4().hex[:6].upper()
    created = await client.post("/equipment", headers=auth(admin_token), json={
        "name": f"ทดสอบ MINOR8 วัสดุสิ้นเปลือง {tag}", "category_ids": [],
        "item_type": "consumable", "quantity_total": 10, "image_urls": ["/uploads/test.jpg"],
        "unit_value": 5, "acquired_at": "2024-01-15", "unit": "ชิ้น",
    })
    assert created.status_code == 201, created.text
    eq_id = created.json()["id"]
    try:
        r = await client.patch(f"/equipment/{eq_id}", headers=auth(admin_token),
                               json={"quality_tracked": True})
        assert r.status_code == 400
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(AuditLog).where(AuditLog.target_id == uuid.UUID(eq_id)))
            await db.execute(delete(Equipment).where(Equipment.id == uuid.UUID(eq_id)))
            await db.commit()


@pytest.mark.asyncio(loop_scope="session")
async def test_converting_tracked_unit_to_consumable_silently_clears_tracking(
    client: AsyncClient, admin_token: str,
):
    """แปลง item_type เป็น consumable เฉย ๆ โดยไม่ได้แตะ quality_tracked ในคำขอเดียวกัน (ค่า True เดิมค้างมา
    จากตอนยังเป็น material) ต้องถูกปิดเงียบ ๆ ไม่ error (ต่างจากเทสข้างบนที่ตั้งใจส่ง True ตรง ๆ ทับ consumable)
    """
    tag = uuid.uuid4().hex[:6].upper()
    created = await client.post("/equipment", headers=auth(admin_token), json={
        "code": f"{uuid.uuid4().int % 10**15:015d}", "name": f"ทดสอบ MINOR8 แปลงเป็นสิ้นเปลือง {tag}",
        "category_ids": [], "item_type": "material", "quantity_total": 1,
        "image_urls": ["/uploads/test.jpg"], "unit_value": 100, "acquired_at": "2024-01-15",
    })
    assert created.status_code == 201, created.text
    eq_id = created.json()["id"]
    try:
        tracked = await client.patch(f"/equipment/{eq_id}", headers=auth(admin_token),
                                     json={"quality_tracked": True, "quality_life_years": 2})
        assert tracked.status_code == 200, tracked.text
        assert tracked.json()["quality_tracked"] is True

        converted = await client.patch(f"/equipment/{eq_id}", headers=auth(admin_token),
                                       json={"item_type": "consumable", "unit": "ชิ้น"})
        assert converted.status_code == 200, converted.text
        async with AsyncSessionLocal() as db:
            eq = await db.get(Equipment, uuid.UUID(eq_id))
            assert eq.item_type == "consumable"
            assert eq.quality_tracked is False, "แปลงเป็นวัสดุสิ้นเปลืองต้องปิดติดตามคุณภาพอัตโนมัติ"
            assert eq.quality_life_years is None
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(AuditLog).where(AuditLog.target_id == uuid.UUID(eq_id)))
            await db.execute(delete(Equipment).where(Equipment.id == uuid.UUID(eq_id)))
            await db.commit()


# ── M3 (รีวิวรอบ 2): ตรวจค่า setting quality_life_years_default ต้องเป็นจำนวนเต็ม + อ่านกันพัง ──────────

@pytest.mark.asyncio(loop_scope="session")
async def test_quality_life_years_default_setting_rejects_non_integer(
    client: AsyncClient, superadmin_token: str, test_superadmin: User,
):
    """แก้ setting จริงของระบบ (quality_life_years_default) — ต้องอ่านค่าเดิมมาก่อนแล้วคืนค่าใน finally
    เสมอ (ตามกฎ CLAUDE.md) เดิมยิง PATCH "4" ทิ้งไว้เฉย ๆ โดยไม่เคยอ่าน/คืนค่าก่อนหน้าเลย ถ้าค่าก่อนเทส
    ไม่ใช่ "4" (เช่นแอดมินเคยปรับไว้) จะเขียนทับเงียบ ๆ (แก้ตามรีวิวรอบ 3, MAJOR-2) — target_id ของ action
    "update_setting" derive จากชื่อ key ด้วย uuid5 คงที่ (ไม่ใช่ของเทสนี้ที่เดียว มีของจริงปนได้) ห้ามใช้
    กรองลบ audit_logs เด็ดขาด ต้อง scope ด้วยเวลาเริ่ม + actor + ชื่อ setting แทน

    finally เดิมยิง PATCH คืนค่าแล้วไม่เคยเช็ค status เลย — ถ้า PATCH คืนค่าพังเงียบ ๆ (เช่น `before` เอง
    ดันไม่ผ่าน validate ด้วยเหตุผลอื่นที่ไม่คาดคิด) setting จริงของระบบจะค้างเป็นค่าที่เทสนี้ตั้งไว้ชั่วคราว
    ต่อไปโดยไม่มีใครรู้ — เขียนกลับตรง ๆ ผ่าน DB (bypass validate) เป็น fallback ก่อนเสมอถ้า API ไม่สำเร็จ
    แล้วค่อย assert status เพื่อให้เทสยัง fail ชัดเจนถ้าเกิดเหตุการณ์นี้จริง (แก้ตามรีวิวรอบ 4, M-i)
    """
    started = datetime.now(timezone.utc)
    h = auth(superadmin_token)
    bad = await client.patch("/settings/quality_life_years_default", headers=h, json={"value": "4.5"})
    assert bad.status_code == 400

    before = next(s for s in (await client.get("/settings", headers=h)).json()
                  if s["key"] == "quality_life_years_default")["value"]
    try:
        ok = await client.patch("/settings/quality_life_years_default", headers=h, json={"value": "4"})
        assert ok.status_code == 200, ok.text
    finally:
        restore = await client.patch("/settings/quality_life_years_default", headers=h, json={"value": before})
        if restore.status_code != 200:
            from app.models.setting import Setting
            async with AsyncSessionLocal() as db:
                setting = (await db.execute(
                    select(Setting).where(Setting.key == "quality_life_years_default"))).scalar_one()
                setting.value = before
                await db.commit()
        assert restore.status_code == 200, f"คืนค่า setting เดิมไม่สำเร็จ (fallback เขียน DB ตรงให้แล้ว): {restore.text}"
        async with AsyncSessionLocal() as db:
            await db.execute(delete(AuditLog).where(
                AuditLog.action == "update_setting",
                AuditLog.created_at >= started,
                AuditLog.actor_id == test_superadmin.id,
                AuditLog.detail["setting"].astext == "quality_life_years_default",
            ))
            await db.commit()


@pytest.mark.asyncio(loop_scope="session")
async def test_quality_settings_reader_falls_back_on_corrupted_stored_value():
    """ค่าที่เสียอยู่ใน DB (ข้าม validate ปกติ เช่นแก้ตรง ๆ ด้วย SQL) ต้องไม่ทำให้คิดคุณภาพ 500 — fallback
    เป็นค่าเริ่มต้นแทน (M3)"""
    from app.models.setting import Setting

    async with AsyncSessionLocal() as db:
        setting = (await db.execute(
            select(Setting).where(Setting.key == "quality_life_years_default"))).scalar_one()
        original_value = setting.value
        setting.value = "4.5"  # ข้าม validate ตรง ๆ ผ่าน ORM — จำลองข้อมูลเสียใน DB
        await db.commit()
    try:
        async with AsyncSessionLocal() as db:
            age_weight, life_default = await equipment_service.quality_settings(db)
        assert life_default == 4, "ค่าเสีย (มีทศนิยม) ต้อง fallback เป็นค่าเริ่มต้น ไม่ใช่โยน exception"
    finally:
        async with AsyncSessionLocal() as db:
            setting = (await db.execute(
                select(Setting).where(Setting.key == "quality_life_years_default"))).scalar_one()
            setting.value = original_value
            await db.commit()
