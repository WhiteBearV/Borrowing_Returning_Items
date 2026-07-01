"""Shared fixtures สำหรับ integration tests"""
import uuid

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, text

from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.borrow_item import BorrowItem
from app.models.borrow_request import BorrowRequest
from app.models.equipment import Equipment
from app.models.equipment_category import EquipmentCategory
from app.models.notification import Notification
from app.models.setting import Setting
from app.models.user import User


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _delete_user_cascade(uid: uuid.UUID) -> None:
    """ลบ user พร้อม cascade ทั้งหมดด้วย SQL ตรงๆ เพื่อเลี่ยง ORM cascade issue"""
    async with AsyncSessionLocal() as db:
        # ลบ FK ที่ชี้มาที่ user ก่อน
        borrow_reqs = (await db.execute(
            delete(BorrowRequest).where(BorrowRequest.student_id == uid).returning(BorrowRequest.id)
        )).scalars().all()
        for req_id in borrow_reqs:
            await db.execute(delete(Notification).where(Notification.borrow_request_id == req_id))
            await db.execute(delete(BorrowItem).where(BorrowItem.borrow_request_id == req_id))
        await db.execute(delete(Notification).where(Notification.user_id == uid))
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
        "max_loan_days_durable": "7",
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
        eq = Equipment(
            id=eq_id,
            code=f"TEST-{eq_id.hex[:6].upper()}",
            name="Arduino Uno R3 (ทดสอบ)",
            category_id=test_category.id,
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
async def admin_token(test_admin: User) -> str:
    return create_access_token(str(test_admin.id), extra={"role": "admin"})
