"""รอบตรวจเช็คอุปกรณ์ (24 ก.ย. 69): inspection_status() แยกกอง low/overdue/unassessed ถูก · 0 = ปิดรอบตรวจ
· job ทวงเจ้าหน้าที่ครั้งเดียวต่อสัปดาห์ · setting ตรวจรูปแบบ

หมายเหตุ: conftest.py มี PYTEST_ALLOW_DB=1 รันใส่ DB dev จริง — ลบของที่สร้าง + แจ้งเตือนที่ job ยิงใน finally
และคืนค่า setting เดิม
"""
import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.equipment import Equipment
from app.models.notification import Notification
from app.models.setting import Setting
from app.services import equipment_service
from app.utils.scheduler import _check_inspection
from tests.conftest import auth


async def _set_interval(value: str) -> None:
    async with AsyncSessionLocal() as db:
        (await db.execute(select(Setting).where(Setting.key == "quality_inspect_interval_months"))
         ).scalar_one().value = value
        await db.commit()


async def test_inspection_status_and_weekly_reminder(client: AsyncClient, admin_token: str):
    now = datetime.now(timezone.utc)
    tag = uuid.uuid4().hex[:6].upper()
    stale, fresh, never = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with AsyncSessionLocal() as db:
        before = (await db.execute(select(Setting.value).where(
            Setting.key == "quality_inspect_interval_months"))).scalar_one()
        for eq_id, suffix, baseline_at in ((stale, "S", now - timedelta(days=200)),
                                           (fresh, "F", now - timedelta(days=10)), (never, "N", None)):
            db.add(Equipment(
                id=eq_id, code=f"TEST-INSP-{tag}-{suffix}", name=f"เครื่องทดสอบรอบตรวจ {tag}-{suffix}",
                item_type="durable", quantity_total=1, quantity_available=1, status="available",
                quality_tracked=True, quality_life_years=4,
                quality_baseline=90 if baseline_at else None, quality_baseline_at=baseline_at,
            ))
        await db.commit()
    try:
        await _set_interval("6")
        async with AsyncSessionLocal() as db:
            st = {k: {e.id for e in v} for k, v in (await equipment_service.inspection_status(db)).items()}
        assert stale in st["overdue"] and fresh not in st["overdue"]
        assert never in st["unassessed"] and never not in st["overdue"]
        assert stale not in st["low"]  # 90% − ~5% ยังเหนือเกณฑ์ 10%

        await _set_interval("0")
        async with AsyncSessionLocal() as db:
            assert stale not in {e.id for e in (await equipment_service.inspection_status(db))["overdue"]}

        # setting: ผู้ดูแลคลังแก้ได้ · ตรวจรูปแบบ
        for bad in ("-1", "1.5", "abc", "100"):
            r = await client.patch("/settings/quality_inspect_interval_months",
                                   headers=auth(admin_token), json={"value": bad})
            assert r.status_code == 400, f"{bad!r} -> {r.status_code}"
        r = await client.patch("/settings/quality_inspect_interval_months",
                               headers=auth(admin_token), json={"value": "6"})
        assert r.status_code == 200, r.text

        # job: รอบแรกยิง (ไม่มีแจ้งเตือนชนิดนี้ในสัปดาห์นี้) รอบสองวันเดียวกันต้องไม่ยิงซ้ำ
        async with AsyncSessionLocal() as db:
            await db.execute(delete(Notification).where(Notification.type == "inspection_due",
                                                        Notification.sent_at >= now - timedelta(days=8)))
            await db.commit()
        await _check_inspection()
        await _check_inspection()
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(select(Notification.user_id, Notification.message).where(
                Notification.type == "inspection_due", Notification.sent_at >= now))).all()
        users = [u for u, _ in rows]
        assert users and len(users) == len(set(users))  # เจ้าหน้าที่แต่ละคนได้ 1 ข้อความ ไม่ใช่ 2
        assert all(f"TEST-INSP-{tag}-S" in m for _, m in rows)
    finally:
        await _set_interval(before)
        async with AsyncSessionLocal() as db:
            await db.execute(delete(Notification).where(Notification.type == "inspection_due",
                                                        Notification.sent_at >= now))
            await db.execute(delete(Equipment).where(Equipment.id.in_((stale, fresh, never))))
            await db.commit()
