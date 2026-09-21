"""Shared fixtures สำหรับ integration tests"""
import uuid

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, text, update

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.audit_log import AuditLog
from app.models.borrow_item import BorrowItem
from app.models.borrow_request import BorrowRequest
from app.models.equipment import Equipment
from app.models.equipment_category import EquipmentCategory
from app.models.notification import Notification
from app.models.setting import Setting
from app.models.user import User


# fixture ในไฟล์นี้ลบแถวตรง ๆ ผ่าน AsyncSessionLocal ตัวเดียวกับที่แอปใช้
# ถ้าเผลอรัน pytest บนเครื่องที่ .env ชี้ DB ของจริง (เช่นใน container ตอน deploy)
# ข้อมูลผู้ใช้/คำขอยืมจะหายทันทีโดยไม่มีอะไรถาม — กันไว้ตรงนี้เพราะกู้คืนแพงกว่ามาก
_DB_NAME = settings.DATABASE_URL.rsplit("/", 1)[-1].split("?")[0]
if not _DB_NAME.endswith("_test") and not settings.PYTEST_ALLOW_DB:
    raise RuntimeError(
        f"ปฏิเสธการรันเทสต์กับฐานข้อมูล '{_DB_NAME}' เพราะเทสต์จะลบข้อมูลทิ้ง\n"
        f"ใช้ฐานข้อมูลที่ชื่อลงท้ายด้วย _test หรือถ้ายืนยันว่าเป็นเครื่อง dev "
        f"ให้ตั้ง PYTEST_ALLOW_DB=1 ใน backend/.env"
    )


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _delete_user_cascade(uid: uuid.UUID) -> None:
    """ลบ user พร้อม cascade ทั้งหมดด้วย SQL ตรงๆ เพื่อเลี่ยง ORM cascade issue"""
    async with AsyncSessionLocal() as db:
        # อ่าน student_id ไว้ก่อนลบ — /auth/register ส่ง notification "registration_pending" ไปหา staff
        # ทุกคน (ไม่ใช่แค่ผู้สมัครเอง) เมื่อบัญชีเข้าคิวรออนุมัติ ข้อความมีรหัสนักศึกษาฝังอยู่ แต่แถวนั้นอยู่ใต้
        # user_id ของ "staff" (admin/superadmin จริง) ไม่ใช่ของผู้สมัคร — ลบแค่ user นี้ทิ้งโดยไม่ตามไปเก็บกวาด
        # ข้อความเหล่านั้นด้วย จะเหลือเป็นขยะถาวรในกล่องแจ้งเตือนของบัญชีจริงที่อ้างถึงบัญชีทดสอบที่ไม่มีอยู่แล้ว
        # (รหัสทดสอบสุ่ม 10 หลัก ชนกับของจริงแทบเป็นไปไม่ได้ จึงกรองด้วยรหัสนี้พอ ไม่ต้อง scope ด้วยเวลาเพิ่ม)
        student_id = (await db.execute(select(User.student_id).where(User.id == uid))).scalar_one_or_none()
        # ลบ FK ที่ชี้มาที่ user ก่อน — ต้องลบ BorrowItem/Notification ที่ชี้มาที่คำขอก่อน ค่อยลบตัวคำขอ (FK order)
        borrow_reqs = (await db.execute(
            select(BorrowRequest.id).where(BorrowRequest.student_id == uid)
        )).scalars().all()
        for req_id in borrow_reqs:
            await db.execute(delete(Notification).where(Notification.borrow_request_id == req_id))
            await db.execute(delete(BorrowItem).where(BorrowItem.borrow_request_id == req_id))
        await db.execute(delete(BorrowRequest).where(BorrowRequest.student_id == uid))
        await db.execute(delete(Notification).where(Notification.user_id == uid))
        if student_id:
            await db.execute(delete(Notification).where(
                Notification.type == "registration_pending",
                Notification.message.like(f"%({student_id})%"),
            ))
        # user นี้อาจเป็น admin ที่ approve/รับคืนคำขอของ student คนอื่น (ไม่ใช่แค่ของตัวเอง) — เคลียร์ FK ก่อนลบ
        await db.execute(update(BorrowRequest).where(BorrowRequest.approved_by == uid).values(approved_by=None))
        await db.execute(update(BorrowRequest).where(BorrowRequest.returned_by == uid).values(returned_by=None))
        # audit_logs อ้าง actor_id → ต้องลบก่อนลบ user (FK)
        await db.execute(delete(AuditLog).where(AuditLog.actor_id == uid))
        await db.execute(delete(User).where(User.id == uid))
        await db.commit()


# ── HTTP client ───────────────────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# ── seed settings ─────────────────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="session", loop_scope="session", autouse=True)
async def ensure_settings():
    from sqlalchemy import select
    defaults = {
        "max_active_requests_per_student": "2",
        "max_items_per_request": "5",
        "max_renew_count": "1",
        "max_renew_days": "7",
        "due_soon_notify_days_before": "2",
    }
    async with AsyncSessionLocal() as db:
        for key, value in defaults.items():
            result = await db.execute(select(Setting).where(Setting.key == key))
            if result.scalar_one_or_none() is None:
                db.add(Setting(key=key, value=value))
        await db.commit()


@pytest_asyncio.fixture(scope="session", loop_scope="session", autouse=True)
async def sweep_leftover_test_equipment():
    """กวาดอุปกรณ์ทดสอบที่ค้างเมื่อจบ session — เทสที่ fail กลางคันจะข้าม cleanup ของตัวเองเสมอ

    ปล่อยไว้ไม่ใช่แค่รก: `find_group_members` จับกลุ่มอุปกรณ์ด้วย **ชื่อ** เทสรอบถัดไปที่สร้างของ
    ชื่อเดียวกันจึงไปตัดสต็อกของแถวขยะแทน แล้วไม่มีใครคืน (เคยสะสมจนสต็อกรวมหายไป 19 หน่วย)
    ลบเฉพาะแถวที่ไม่มี borrow_items อ้างถึงแล้ว — ของจริงที่ยังมีประวัติการยืมจะไม่ถูกแตะ
    """
    yield
    async with AsyncSessionLocal() as db:
        await db.execute(text("""
            delete from equipment e
            where (e.name like 'อุปกรณ์ทดสอบ%' or e.name like '%(ทดสอบ)%'
                   or e.code like 'TEST-%' or e.code like 'AUTOCODE-TEST-%')
              and not exists (select 1 from borrow_items bi where bi.equipment_id = e.id)
        """))
        await db.execute(text("""
            delete from equipment_categories c
            where c.name like 'หมวดทดสอบ%'
              and not exists (select 1 from equipment_category_links l where l.category_id = c.id)
        """))
        await db.commit()


# ── test users ────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_student():
    uid = uuid.uuid4()
    async with AsyncSessionLocal() as db:
        user = User(
            id=uid, full_name="นักศึกษา ทดสอบ",
            email=f"student_{uid.hex[:6]}@cdti.ac.th",
            password_hash=hash_password("Test1234!"),
            role="student", student_id=f"65{uid.hex[:8]}",
            email_verified=True, is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        yield user
    await _delete_user_cascade(uid)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_admin():
    uid = uuid.uuid4()
    async with AsyncSessionLocal() as db:
        user = User(
            id=uid, full_name="แอดมิน ทดสอบ",
            email=f"admin_{uid.hex[:6]}@cdti.ac.th",
            password_hash=hash_password("Admin1234!"),
            role="admin", email_verified=True, is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        yield user
    await _delete_user_cascade(uid)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_superadmin():
    """ผู้ดูแลระบบสูงสุด — ใช้กับ endpoint ที่ย้ายไปจำกัดสิทธิ์ (ลบถาวร/แก้ settings/เปลี่ยน role)"""
    uid = uuid.uuid4()
    async with AsyncSessionLocal() as db:
        user = User(
            id=uid, full_name="ซูเปอร์แอดมิน ทดสอบ",
            email=f"superadmin_{uid.hex[:6]}@cdti.ac.th",
            password_hash=hash_password("Super1234!"),
            role="superadmin", email_verified=True, is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        yield user
    await _delete_user_cascade(uid)


# ── test equipment ────────────────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_category():
    cat_id = uuid.uuid4()
    async with AsyncSessionLocal() as db:
        cat = EquipmentCategory(id=cat_id, name=f"หมวดทดสอบ_{cat_id.hex[:4]}")
        db.add(cat)
        await db.commit()
        await db.refresh(cat)
        yield cat
    async with AsyncSessionLocal() as db:
        await db.execute(delete(EquipmentCategory).where(EquipmentCategory.id == cat_id))
        await db.commit()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_equipment(test_category: EquipmentCategory):
    eq_id = uuid.uuid4()
    async with AsyncSessionLocal() as db:
        cat = await db.get(EquipmentCategory, test_category.id)
        eq = Equipment(
            id=eq_id,
            code=f"TEST-{eq_id.hex[:6].upper()}",
            name="Arduino Uno R3 (ทดสอบ)",
            categories=[cat],
            item_type="durable",
            quantity_total=5,
            quantity_available=5,
            status="available",
        )
        db.add(eq)
        await db.commit()
        await db.refresh(eq)
        yield eq
    async with AsyncSessionLocal() as db:
        # ลบ borrow_items ที่ชี้มาก่อน (FK NOT NULL)
        await db.execute(delete(BorrowItem).where(BorrowItem.equipment_id == eq_id))
        await db.execute(delete(Equipment).where(Equipment.id == eq_id))
        await db.commit()


# ── tokens ────────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def student_token(test_student: User) -> str:
    return create_access_token(str(test_student.id), extra={"role": "student"})


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def superadmin_token(test_superadmin: User) -> str:
    return create_access_token(str(test_superadmin.id), extra={"role": "superadmin"})


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def admin_token(test_admin: User) -> str:
    return create_access_token(str(test_admin.id), extra={"role": "admin"})
