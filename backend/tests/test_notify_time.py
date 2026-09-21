"""เวลาส่งแจ้งเตือนรายวัน (setting notify_time — 21 ก.ย. 69): superadmin เท่านั้น · ตรวจรูปแบบ · เลื่อน job ทันที

หมายเหตุ: conftest.py มี PYTEST_ALLOW_DB=1 รันใส่ DB dev จริง — คืนค่าเดิมใน finally เสมอ
(audit ของ throwaway superadmin ถูกลบตามตอน fixture ลบ user)
"""
from httpx import AsyncClient

from app.utils.scheduler import DAILY_JOB_IDS, _check_due_soon, _check_overdue, scheduler
from tests.conftest import auth


async def test_notify_time_superadmin_only_validated_and_reschedules(
    client: AsyncClient, admin_token: str, superadmin_token: str,
):
    sa = auth(superadmin_token)
    before = next(s for s in (await client.get("/settings", headers=sa)).json()
                  if s["key"] == "notify_time")["value"]
    # เทสไม่ผ่าน lifespan จึงไม่มี job — ลงไว้แบบ pending (scheduler ไม่ได้ start) เพื่อดูว่าถูกเลื่อนจริง
    for job_id, fn in zip(DAILY_JOB_IDS, (_check_due_soon, _check_overdue)):
        scheduler.add_job(fn, "cron", hour=0, minute=0, id=job_id, replace_existing=True)
    try:
        assert (await client.patch("/settings/notify_time", headers=auth(admin_token),
                                   json={"value": "07:30"})).status_code == 403
        for bad in ("25:00", "7:30", "08:60", "08.00", ""):
            r = await client.patch("/settings/notify_time", headers=sa, json={"value": bad})
            assert r.status_code == 400, f"{bad!r} -> {r.status_code}"

        r = await client.patch("/settings/notify_time", headers=sa, json={"value": "07:30"})
        assert r.status_code == 200, r.text
        for job_id in DAILY_JOB_IDS:
            fields = {f.name: str(f) for f in scheduler.get_job(job_id).trigger.fields}
            assert (fields["hour"], fields["minute"]) == ("7", "30"), job_id
    finally:
        await client.patch("/settings/notify_time", headers=sa, json={"value": before})
        for job_id in DAILY_JOB_IDS:
            scheduler.remove_job(job_id)
