"""ลำดับจ่ายของ — หน่วยที่ถูกใช้มาน้อยสุดถูกยืมออกก่อน แล้วค่อยเก่าสุดก่อน

feedback อาจารย์ 5 ก.ย. 69 ข้อ 9: กฎเดิม (FIFO ตาม acquired_at ล้วน ๆ) ทำให้ของเก่าที่โทรมอยู่แล้ว
ถูกจ่ายซ้ำทุกครั้งจนพังอยู่ชิ้นเดียว เกณฑ์ใหม่กระจายการสึกหรอตาม "วันที่เคยถูกยืมจริง"
อายุของ (acquired_at) ลดบทบาทเหลือแค่ tie-break ของหน่วยที่ถูกใช้มาเท่ากัน

ทุกเคสจงใจตั้งให้ลำดับ code สวนทางกับลำดับที่คาดหวัง เพื่อพิสูจน์ว่าเปลี่ยนพฤติกรรมจริง
ไม่ใช่ผ่านเพราะบังเอิญเรียงตรงกัน

หมายเหตุ: conftest.py มี PYTEST_ALLOW_DB=1 รันใส่ DB dev จริง — ทุกเทสต้อง cleanup ใน fixture teardown
code ของทุกแถวที่สร้างในไฟล์นี้ขึ้นต้นด้วย "TEST-" เสมอ (แม้จะมี prefix เฉพาะกลุ่มต่อท้าย เช่น
"TEST-QDISP-…"/"TEST-QMIX-…") ให้ sweep_leftover_test_equipment ใน conftest.py (`code like 'TEST-%'`)
กวาดทิ้งได้ถ้ารันค้างกลางคันแล้ว teardown ของตัวเองไม่ทำงาน — ชื่อกลุ่มอย่าง "โน้ตบุ๊กทดสอบ…"/"ผสมทดสอบ…"
ไม่ตรง pattern ชื่อที่ sweeper กรอง ("อุปกรณ์ทดสอบ%"/"%(ทดสอบ)%") จึงพึ่ง code อย่างเดียว (แก้ตามรีวิวรอบ 3, MINOR-6)
"""
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.audit_log import AuditLog
from app.models.auth_token import AuthToken
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


# ── dispatch_order: จับคู่อายุที่เหลือของเครื่องกับเวลาเรียนที่เหลือของผู้ยืม (เฟส 10, 15 ก.ย. 69) ──────
#
# ตัวอย่างจากแผน: โน้ตบุ๊กอายุ 4 ปี มีเครื่องคุณภาพ 95% · 72% · 40% · ยังไม่ประเมิน 1 เครื่อง
# | ผู้ยืม | ต้องการ | ได้ | เหตุผล |
# | ปี 1 (เหลือ 4 ปี) | ≥100% | 95% | ไม่มีตัวไหนพอ → ใกล้สุด |
# | ปี 2 (เหลือ 3 ปี) | ≥75%  | 95% | ตัวเดียวที่พอ |
# | ปี 3 (เหลือ 2 ปี) | ≥50%  | 72% | ตัวที่พอดีที่สุด |
# | ปี 4/ตกค้าง (เหลือ 1 ปี) | ≥25% | 40% | เก็บ 72%/95% ไว้ให้ปีต่ำกว่า |
# | อาจารย์ | —     | ถูกใช้น้อยสุด | กฎเดิม |

QUALITY_GROUP_NAME = "โน้ตบุ๊กทดสอบจ่ายของตามคุณภาพ"


@pytest_asyncio.fixture(loop_scope="session")
async def quality_group():
    """4 หน่วย: คุณภาพ 95% / 72% / 40% / ยังไม่ประเมิน — ทุกหน่วยเปิดติดตาม อายุการใช้งาน 4 ปี
    baseline ตั้งเป็น "เมื่อกี้" (ไม่ใช่อดีตไกล) เพื่อให้ส่วนหักจากอายุ ≈ 0 ค่าปัจจุบัน ≈ baseline พอดี
    ไม่ต้องพึ่งค่า quality_age_weight ปัจจุบันใน DB (ทนต่อเทสอื่นที่อาจแก้ setting นี้คาบเกี่ยวกัน)
    """
    tag = uuid.uuid4().hex[:6].upper()
    now = datetime.now(timezone.utc)
    specs = [("Q95", 95.0), ("Q72", 72.0), ("Q40", 40.0), ("QNA", None)]
    eq_ids = []
    async with AsyncSessionLocal() as db:
        for seq, baseline in specs:
            eq_id = uuid.uuid4()
            eq_ids.append(eq_id)
            db.add(Equipment(
                id=eq_id, code=f"TEST-QDISP-{tag}-{seq}", name=QUALITY_GROUP_NAME, item_type="durable",
                quantity_total=1, quantity_available=1, status="available", unit_value=20000,
                acquired_at=date(2020, 1, 1), quality_tracked=True, quality_life_years=4,
                quality_baseline=baseline, quality_baseline_at=now if baseline is not None else None,
            ))
        await db.commit()
    yield {"Q95": eq_ids[0], "Q72": eq_ids[1], "Q40": eq_ids[2], "QNA": eq_ids[3]}
    async with AsyncSessionLocal() as db:
        req_ids = (await db.execute(
            select(BorrowItem.borrow_request_id).where(BorrowItem.equipment_id.in_(eq_ids))
        )).scalars().all()
        item_ids = (await db.execute(
            select(BorrowItem.id).where(BorrowItem.equipment_id.in_(eq_ids))
        )).scalars().all()
        for ids in (req_ids, item_ids, eq_ids):
            if ids:
                await db.execute(delete(AuditLog).where(AuditLog.target_id.in_(ids)))
        if req_ids:
            await db.execute(delete(Notification).where(Notification.borrow_request_id.in_(req_ids)))
        await db.execute(delete(BorrowItem).where(BorrowItem.equipment_id.in_(eq_ids)))
        if req_ids:
            await db.execute(delete(BorrowRequest).where(BorrowRequest.id.in_(req_ids)))
        await db.execute(delete(Equipment).where(Equipment.id.in_(eq_ids)))
        await db.commit()


@pytest_asyncio.fixture(loop_scope="session")
async def year_students():
    """นักศึกษา 5 คน: ปี 1-4 + ตกค้าง (ปีที่ 5) — enrollment_year คำนวณสัมพัทธ์กับปีการศึกษาปัจจุบันจริง
    ที่อ่านจาก setting academic_year_start (ไม่ hardcode ปี พ.ศ. — ทนต่อวันที่รันเทสต่างวันกัน)
    """
    from app.services import settings_service
    async with AsyncSessionLocal() as db:
        start = await settings_service.get_academic_year_start(db)
    from app.utils.study_year import academic_year
    cur = academic_year(date.today(), start)

    levels = {"y1": 1, "y2": 2, "y3": 3, "y4": 4, "retained": 5}
    users: dict[str, User] = {}
    async with AsyncSessionLocal() as db:
        for key, level in levels.items():
            uid = uuid.uuid4()
            u = User(
                id=uid, full_name=f"นักศึกษาทดสอบ {key}", email=f"dispyear_{uid.hex[:6]}@cdti.ac.th",
                password_hash=hash_password("Test1234!"), role="student",
                student_id=f"97{uid.hex[:8]}", email_verified=True, is_active=True,
                enrollment_year=cur - level + 1, study_years=4,
            )
            db.add(u)
            users[key] = u
        await db.commit()
        for u in users.values():
            await db.refresh(u)
    yield users
    async with AsyncSessionLocal() as db:
        for u in users.values():
            await db.execute(delete(Notification).where(Notification.user_id == u.id))
            await db.execute(delete(AuthToken).where(AuthToken.user_id == u.id))
            await db.execute(delete(AuditLog).where(AuditLog.actor_id == u.id))
            await db.execute(delete(AuditLog).where(AuditLog.target_id == u.id))
            await db.execute(delete(User).where(User.id == u.id))
        await db.commit()


async def _ordered_codes(eq_ids: dict, borrower: User) -> list[str]:
    async with AsyncSessionLocal() as db:
        units = list((await db.execute(
            select(Equipment).where(Equipment.id.in_(eq_ids.values()))
        )).scalars().all())
        ordered = await equipment_service.dispatch_order(db, units, borrower)
    return [u.code.rsplit("-", 1)[-1] for u in ordered]


@pytest.mark.asyncio(loop_scope="session")
async def test_dispatch_order_year1_gets_closest_when_nothing_meets_requirement(quality_group, year_students):
    """ปี 1 เหลือ 4 ปี ต้องการเครื่องอายุเหลือ ≥4 ปี แต่ไม่มีตัวไหนพอ (95%×4=3.8 มากสุด) → ได้ 95%"""
    ordered = await _ordered_codes(quality_group, year_students["y1"])
    assert ordered[0] == "Q95"


@pytest.mark.asyncio(loop_scope="session")
async def test_dispatch_order_year2_gets_only_sufficient_unit(quality_group, year_students):
    """ปี 2 เหลือ 3 ปี — เฉพาะ 95% (3.8) พอ ส่วน 72% (2.88) ไม่พอ → ได้ 95%"""
    ordered = await _ordered_codes(quality_group, year_students["y2"])
    assert ordered[0] == "Q95"


@pytest.mark.asyncio(loop_scope="session")
async def test_dispatch_order_year3_gets_the_tightest_fit(quality_group, year_students):
    """ปี 3 เหลือ 2 ปี — ทั้ง 95% (3.8) และ 72% (2.88) พอ แต่ต้องได้ตัวที่พอดีที่สุด (72%) เก็บ 95% ไว้"""
    ordered = await _ordered_codes(quality_group, year_students["y3"])
    assert ordered[0] == "Q72"


@pytest.mark.asyncio(loop_scope="session")
async def test_dispatch_order_year4_and_retained_get_the_weakest_sufficient_unit(quality_group, year_students):
    """ปี 4 / ตกค้าง เหลือ 1 ปี — ทุกตัวพอ (แม้ 40%×4=1.6) ต้องได้ตัวที่อ่อนสุดที่ยังพอ เก็บตัวดีไว้ให้ปีต่ำกว่า"""
    for key in ("y4", "retained"):
        ordered = await _ordered_codes(quality_group, year_students[key])
        assert ordered[0] == "Q40", f"{key} ต้องได้ 40% ไม่ใช่เก็บของดีไว้เฉยๆ"


@pytest.mark.asyncio(loop_scope="session")
async def test_dispatch_order_unassessed_unit_always_goes_last(quality_group, year_students):
    """หน่วยที่ยังไม่ประเมินต้องต่อท้ายเสมอ ไม่ว่าผู้ยืมจะเป็นใคร"""
    for key in year_students:
        ordered = await _ordered_codes(quality_group, year_students[key])
        assert ordered[-1] == "QNA"


@pytest.mark.asyncio(loop_scope="session")
async def test_dispatch_order_falls_back_to_old_rule_for_staff_borrower(
    quality_group, test_admin: User,
):
    """อาจารย์/เจ้าหน้าที่ (ไม่มีปีการศึกษา) → กฎเดิมทั้งหมด (ถูกใช้น้อยสุดก่อน) ไม่สนคุณภาพเลย"""
    async with AsyncSessionLocal() as db:
        units = list((await db.execute(
            select(Equipment).where(Equipment.id.in_(quality_group.values()))
        )).scalars().all())
        expected = sorted(units, key=lambda u: equipment_service.dispatch_key(u, {}))
        ordered = await equipment_service.dispatch_order(db, units, test_admin)
    assert [u.code for u in ordered] == [u.code for u in expected]


@pytest.mark.asyncio(loop_scope="session")
async def test_dispatch_order_falls_back_to_old_rule_when_group_not_fully_tracked(year_students):
    """รุ่นที่มีหน่วยไม่เปิดติดตามอยู่แม้แค่หน่วยเดียว → ทั้งกลุ่มใช้กฎเดิม ไม่ผสมสองกฎ"""
    tag = uuid.uuid4().hex[:6].upper()
    tracked_id, untracked_id = uuid.uuid4(), uuid.uuid4()
    async with AsyncSessionLocal() as db:
        db.add(Equipment(
            id=tracked_id, code=f"TEST-QDISP-{tag}-MIXA", name=f"ผสมทดสอบ {tag}", item_type="durable",
            quantity_total=1, quantity_available=1, status="available",
            quality_tracked=True, quality_life_years=4, quality_baseline=90.0,
            quality_baseline_at=datetime.now(timezone.utc), acquired_at=date(2019, 1, 1),
        ))
        db.add(Equipment(
            id=untracked_id, code=f"TEST-QDISP-{tag}-MIXB", name=f"ผสมทดสอบ {tag}", item_type="durable",
            quantity_total=1, quantity_available=1, status="available",
            acquired_at=date(2023, 1, 1),
        ))
        await db.commit()
    try:
        async with AsyncSessionLocal() as db:
            units = list((await db.execute(
                select(Equipment).where(Equipment.id.in_([tracked_id, untracked_id]))
            )).scalars().all())
            expected = sorted(units, key=lambda u: equipment_service.dispatch_key(u, {}))
            ordered = await equipment_service.dispatch_order(db, units, year_students["y1"])
        assert [u.code for u in ordered] == [u.code for u in expected], \
            "มีหน่วยไม่เปิดติดตามปนอยู่ ต้อง fallback กฎเดิมทั้งกลุ่ม ไม่ใช่เลือกเฉพาะหน่วยที่ติดตาม"
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(Equipment).where(Equipment.id.in_([tracked_id, untracked_id])))
            await db.commit()


# ── M2 (รีวิวรอบ 2): เกณฑ์ "เปิดติดตามครบ" ต้องดูเฉพาะหน่วยที่ยืมได้จริง ────────────────────────────────
# ก่อนแก้: approve_request ส่ง "ทั้งกลุ่ม" ที่ล็อกมา (รวมหน่วยปลดระวาง/untracked) เข้า dispatch_order ตรง ๆ
# ทำให้ all(tracked) เป็น False ทั้งที่หน่วยที่ยืมได้จริงเปิดติดตามครบ กลายเป็น fallback ไปกฎเก่าตอนอนุมัติ
# ขณะที่ create_request/recommend กรอง eligible ไว้ก่อนแล้วเลยยังใช้กฎคุณภาพถูก — จองได้คนละหน่วยกับที่จ่ายจริง

MIXED_RETIRED_GROUP_NAME = "โน้ตบุ๊กทดสอบกลุ่มมีของปลดระวางปน"


@pytest_asyncio.fixture(loop_scope="session")
async def mixed_retired_group():
    """3 หน่วยเปิดติดตามคุณภาพ + ยืมได้จริง (95% / 72% / 40%) บวกอีก 1 หน่วยที่ **ปลดระวางแล้วและไม่เปิด
    ติดตาม** (สถานการณ์ตรงตัวจาก M2: "3 tracked available units plus 1 untracked retired unit")
    """
    tag = uuid.uuid4().hex[:6].upper()
    now = datetime.now(timezone.utc)
    eq_ids: dict[str, uuid.UUID] = {}
    async with AsyncSessionLocal() as db:
        for seq, baseline, status_, tracked in (
            ("Q95", 95.0, "available", True), ("Q72", 72.0, "available", True),
            ("Q40", 40.0, "available", True), ("RETIRED", None, "retired", False),
        ):
            eq_id = uuid.uuid4()
            eq_ids[seq] = eq_id
            db.add(Equipment(
                id=eq_id, code=f"TEST-QMIX-{tag}-{seq}", name=MIXED_RETIRED_GROUP_NAME, item_type="durable",
                quantity_total=1, quantity_available=1, status=status_, unit_value=20000,
                acquired_at=date(2020, 1, 1), quality_tracked=tracked, quality_life_years=4,
                quality_baseline=baseline, quality_baseline_at=now if baseline is not None else None,
            ))
        await db.commit()
    yield eq_ids
    async with AsyncSessionLocal() as db:
        ids = list(eq_ids.values())
        req_ids = (await db.execute(
            select(BorrowItem.borrow_request_id).where(BorrowItem.equipment_id.in_(ids))
        )).scalars().all()
        item_ids = (await db.execute(select(BorrowItem.id).where(BorrowItem.equipment_id.in_(ids)))).scalars().all()
        for group_ids in (req_ids, item_ids, ids):
            if group_ids:
                await db.execute(delete(AuditLog).where(AuditLog.target_id.in_(group_ids)))
        if req_ids:
            await db.execute(delete(Notification).where(Notification.borrow_request_id.in_(req_ids)))
        await db.execute(delete(BorrowItem).where(BorrowItem.equipment_id.in_(ids)))
        if req_ids:
            await db.execute(delete(BorrowRequest).where(BorrowRequest.id.in_(req_ids)))
        await db.execute(delete(Equipment).where(Equipment.id.in_(ids)))
        await db.commit()


@pytest.mark.asyncio(loop_scope="session")
async def test_reserved_recommended_and_approved_unit_agree_despite_untracked_retired_sibling(
    test_admin: User, year_students, mixed_retired_group,
):
    # หมายเหตุลำดับ fixture: year_students ต้องมาก่อน mixed_retired_group ในพารามิเตอร์ — เทสนี้สร้าง
    # BorrowRequest ที่ผูก student_id ของ year_students กับ equipment ของ mixed_retired_group จริง ถ้า
    # year_students ถูก teardown ก่อน (ลบ users) ทั้งที่ BorrowRequest ยังอ้างถึงอยู่จะชน FK — teardown เป็น
    # LIFO ของลำดับ setup จึงต้องให้ mixed_retired_group (ซึ่ง teardown ลบ BorrowRequest ที่มันสร้างด้วย) ถูก
    # setup หลังสุด เพื่อให้ teardown ก่อน year_students เสมอ
    """M2 e2e: หน่วยที่จองตอนยื่นคำขอ, หน่วยที่ระบบแนะนำใน UnitPickerModal (recommended_unit_id), และหน่วยที่
    จ่ายจริงตอนอนุมัติ ต้องเป็นหน่วยเดียวกันเสมอ (Q72 สำหรับผู้ยืมปี 3) แม้กลุ่มจะมีหน่วยปลดระวางที่ไม่เปิด
    ติดตามปนอยู่ — ก่อนแก้ M2 ขั้นตอนอนุมัติจะได้คนละหน่วยกับที่จองไว้เพราะ fallback ไปกฎเก่า
    """
    from app.schemas.borrow import BorrowItemRequest, BorrowRequestCreate

    y3 = year_students["y3"]
    any_unit_id = mixed_retired_group["Q95"]  # ส่งหน่วยไหนก็ได้ในกลุ่ม — resolve เป็นทั้งกลุ่มเอง

    # 1) recommended_unit_id ที่ UnitPickerModal ใช้ขึ้นป้าย "แนะนำสำหรับผู้ยืมนี้"
    async with AsyncSessionLocal() as db:
        admin = await db.get(User, test_admin.id)
        detail = await equipment_service.get_equipment_group_detail(
            db, any_unit_id, viewer=admin, recommend_for=y3.id)
    assert detail.recommended_unit_id == mixed_retired_group["Q72"]

    # 2) จองตอนยื่นคำขอ
    async with AsyncSessionLocal() as db:
        student = await db.get(User, y3.id)
        resp = await borrow_service.create_request(db, student, BorrowRequestCreate(
            purpose="ทดสอบ M2", requested_due_date=date.today() + timedelta(days=30),
            items=[BorrowItemRequest(equipment_id=any_unit_id, quantity=1)],
        ))
        req_id = resp.id
    async with AsyncSessionLocal() as db:
        item = (await db.execute(select(BorrowItem).where(BorrowItem.borrow_request_id == req_id))).scalar_one()
        assert item.equipment_id == mixed_retired_group["Q72"], "จองตอนยื่นคำขอต้องได้ Q72"

    # 3) จัดสรรจริงตอนอนุมัติ — ต้องได้หน่วยเดียวกับที่จองไว้ ไม่ใช่ fallback ไปกฎเก่าเพราะมีหน่วยปลดระวางปน
    async with AsyncSessionLocal() as db:
        admin = await db.get(User, test_admin.id)
        await borrow_service.approve_request(db, admin, req_id)
    async with AsyncSessionLocal() as db:
        item = (await db.execute(select(BorrowItem).where(BorrowItem.borrow_request_id == req_id))).scalar_one()
        assert item.equipment_id == mixed_retired_group["Q72"], \
            "อนุมัติต้องได้หน่วยเดียวกับที่จอง/แนะนำ (Q72) — ไม่ใช่คนละหน่วยเพราะ fallback ไปกฎเก่า"


# ── M6 (รีวิวรอบ 2): เทสระดับ service ปลายทางจริง ─────────────────────────────────────────────────────

@pytest.mark.asyncio(loop_scope="session")
async def test_create_request_reserves_same_unit_approve_allocates(
    test_admin: User, year_students, quality_group,
):
    """นักศึกษาปี 4 ยื่นคำขอ → จองได้ Q40 แล้วอนุมัติต้องได้ Q40 เหมือนกัน · ปี 1 ต้องได้ Q95

    หมายเหตุลำดับ fixture: year_students ต้องมาก่อน quality_group ในพารามิเตอร์ (ดูเหตุผลเดียวกับเทส M2
    ด้านบน — teardown เป็น LIFO ต้องให้ quality_group ถูก teardown ก่อน year_students เสมอ)
    """
    from app.schemas.borrow import BorrowItemRequest, BorrowRequestCreate

    y4 = year_students["y4"]
    any_unit_id = quality_group["Q95"]

    async with AsyncSessionLocal() as db:
        student = await db.get(User, y4.id)
        resp = await borrow_service.create_request(db, student, BorrowRequestCreate(
            purpose="ทดสอบ M6 ปี4", requested_due_date=date.today() + timedelta(days=30),
            items=[BorrowItemRequest(equipment_id=any_unit_id, quantity=1)],
        ))
        req_id = resp.id
    async with AsyncSessionLocal() as db:
        item = (await db.execute(select(BorrowItem).where(BorrowItem.borrow_request_id == req_id))).scalar_one()
        assert item.equipment_id == quality_group["Q40"]
    async with AsyncSessionLocal() as db:
        admin = await db.get(User, test_admin.id)
        await borrow_service.approve_request(db, admin, req_id)
    async with AsyncSessionLocal() as db:
        item = (await db.execute(select(BorrowItem).where(BorrowItem.borrow_request_id == req_id))).scalar_one()
        assert item.equipment_id == quality_group["Q40"]

    y1 = year_students["y1"]
    async with AsyncSessionLocal() as db:
        student = await db.get(User, y1.id)
        resp = await borrow_service.create_request(db, student, BorrowRequestCreate(
            purpose="ทดสอบ M6 ปี1", requested_due_date=date.today() + timedelta(days=30),
            items=[BorrowItemRequest(equipment_id=any_unit_id, quantity=1)],
        ))
        req_id_y1 = resp.id
    async with AsyncSessionLocal() as db:
        item = (await db.execute(select(BorrowItem).where(BorrowItem.borrow_request_id == req_id_y1))).scalar_one()
        assert item.equipment_id == quality_group["Q95"]


@pytest.mark.asyncio(loop_scope="session")
async def test_group_detail_recommend_for_matches_dispatch_order(test_admin: User, quality_group, year_students):
    """get_equipment_group_detail(viewer=staff, recommend_for=<ปี 3>) ต้องแนะนำ Q72 (ตัวเดียวกับ
    dispatch_order เลือกให้ตอนสร้างคำขอ/อนุมัติ)"""
    async with AsyncSessionLocal() as db:
        admin = await db.get(User, test_admin.id)
        detail = await equipment_service.get_equipment_group_detail(
            db, quality_group["Q95"], viewer=admin, recommend_for=year_students["y3"].id)
    assert detail.recommended_unit_id == quality_group["Q72"]


@pytest.mark.asyncio(loop_scope="session")
async def test_student_viewing_group_detail_does_not_corrupt_quality_columns_for_later_dispatch(
    year_students, quality_group,
):
    """MINOR 1 e2e: นักศึกษาเปิดดูรายละเอียดกลุ่ม (ถูกซ่อนค่าคุณภาพที่ response) แล้วยื่นคำขอต่อใน session
    เดียวกัน — ของเดิมเคยเขียนทับคอลัมน์จริงเป็น None ผ่าน set_committed_value ตอนซ่อนข้อมูล ทำให้ dispatch_order
    ที่เรียกต่อใน request/session เดียวกันเห็น quality_tracked เป็น None (falsy) แล้ว fallback ผิดกฎ ต้องยัง
    เลือกหน่วยตามกฎคุณภาพได้ถูกต้อง (ปี 4 ได้ Q40) และคอลัมน์จริงใน DB ต้องไม่ถูกแตะเลย

    หมายเหตุลำดับ fixture: year_students ต้องมาก่อน quality_group ในพารามิเตอร์ (เหตุผลเดียวกับ 2 เทสด้านบน)
    """
    from app.schemas.borrow import BorrowItemRequest, BorrowRequestCreate

    y4 = year_students["y4"]
    any_unit_id = quality_group["Q95"]

    async with AsyncSessionLocal() as db:
        student = await db.get(User, y4.id)
        # 1) นักศึกษาเปิดดูรายละเอียดกลุ่มก่อน (ต้องไม่เห็นค่าคุณภาพ และต้องไม่แตะคอลัมน์จริง)
        detail = await equipment_service.get_equipment_group_detail(db, any_unit_id, viewer=student)
        assert detail.quality_tracked is None, "นักศึกษาไม่ควรเห็นค่าคุณภาพ"
        for m in detail.members:
            assert m.quality_tracked is None

        # 2) ยื่นคำขอต่อใน session เดียวกัน — ต้องยังเลือกหน่วยตามกฎคุณภาพได้ถูกต้อง (ไม่ fallback)
        resp = await borrow_service.create_request(db, student, BorrowRequestCreate(
            purpose="ทดสอบ MINOR1", requested_due_date=date.today() + timedelta(days=30),
            items=[BorrowItemRequest(equipment_id=any_unit_id, quantity=1)],
        ))
        req_id = resp.id

    async with AsyncSessionLocal() as db:
        item = (await db.execute(select(BorrowItem).where(BorrowItem.borrow_request_id == req_id))).scalar_one()
        assert item.equipment_id == quality_group["Q40"], \
            "ต้องยังใช้กฎคุณภาพเลือก Q40 ให้ปี 4 — ถ้าคอลัมน์จริงถูกเขียนทับเป็น None จะ fallback ไปกฎเก่า"

        # 3) คอลัมน์จริงใน DB ต้องไม่ถูกแตะเลยจากขั้นตอนที่ 1 (ยังเป็น True/ตัวเลขจริง ไม่ใช่ None)
        rows = (await db.execute(
            select(Equipment).where(Equipment.id.in_(quality_group.values()))
        )).scalars().all()
        for eq in rows:
            assert eq.quality_tracked is True
        by_code_suffix = {eq.code.rsplit("-", 1)[-1]: eq for eq in rows}
        assert float(by_code_suffix["Q95"].quality_baseline) == 95.0
        assert float(by_code_suffix["Q72"].quality_baseline) == 72.0
        assert float(by_code_suffix["Q40"].quality_baseline) == 40.0
        assert by_code_suffix["QNA"].quality_baseline is None
