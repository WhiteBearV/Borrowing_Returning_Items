"""ค่าตั้งระบบที่ตัวอ่านแปลงเป็นตัวเลขตรง ๆ ต้องถูกตรวจตอนบันทึก (QA-07 — 30 ก.ย. 69)

เดิมล้างช่อง "จำนวนคำขอที่ยังไม่คืนพร้อมกันสูงสุด" แล้วกดบันทึกได้ → ค่า "" ลง DB → ยื่นคำขอยืมทั้งระบบ 500
ทุกเคสในเทสนี้ถูกปฏิเสธ จึงไม่มีค่าไหนใน DB เปลี่ยน (ไม่ต้องคืนค่า)
"""
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.setting import Setting
from tests.conftest import auth

BAD = [
    ("max_active_requests_per_student", ""), ("max_active_requests_per_student", "1.5"),
    ("max_items_per_request", "0"), ("max_items_per_request", "abc"), ("max_renew_count", "-1"),
    ("due_soon_notify_days_before", "x"), ("fine_per_day_per_item", "-5"), ("fine_grace_days", "abc"),
    ("fine_max_per_item", "เยอะ"), ("depreciation_years_default", "0"), ("pdf_value_source", "hack"),
    ("default_pickup_time", "25:00"), ("low_stock_threshold_default", "abc"),
]


@pytest.mark.parametrize("key,value", BAD)
async def test_bad_setting_values_rejected(client: AsyncClient, superadmin_token: str, key: str, value: str):
    async with AsyncSessionLocal() as db:
        before = (await db.execute(select(Setting.value).where(Setting.key == key))).scalar_one()
    r = await client.patch(f"/settings/{key}", headers=auth(superadmin_token), json={"value": value})
    assert r.status_code == 400, r.text
    async with AsyncSessionLocal() as db:
        assert (await db.execute(select(Setting.value).where(Setting.key == key))).scalar_one() == before
