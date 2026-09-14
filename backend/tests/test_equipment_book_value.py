"""มูลค่าตามบัญชี (ค่าเสื่อมเส้นตรง) + ช่องแก้ทับของแอดมิน

feedback อาจารย์: อุปกรณ์ต้องมี 2 มูลค่า — มูลค่าแท้จริง (ราคาที่ซื้อ, คือ unit_value เดิม)
กับมูลค่าตามบัญชีหลังหักค่าเสื่อม ซึ่งระบบคำนวณให้แต่แอดมินกดแก้ทับได้

หมายเหตุ: conftest.py มี PYTEST_ALLOW_DB=1 รันใส่ DB dev จริง — ทุกเทสต้อง cleanup ใน finally เสมอ
"""
import uuid
from datetime import date, timedelta

from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.equipment import Equipment
from app.services.equipment_service import book_value
from tests.conftest import auth


class _Fake:
    """อุปกรณ์จำลองสำหรับทดสอบสูตรล้วน ๆ — ไม่แตะ DB"""
    def __init__(self, unit_value=None, acquired_at=None, useful_life_years=None, book_value_override=None):
        self.unit_value = unit_value
        self.acquired_at = acquired_at
        self.useful_life_years = useful_life_years
        self.book_value_override = book_value_override


TODAY = date(2026, 1, 1)


def test_book_value_half_life_is_about_half_way():
    """ผ่านไปครึ่งอายุการใช้งาน → เหลือประมาณกึ่งกลางระหว่างราคาทุนกับมูลค่าซาก"""
    eq = _Fake(unit_value=10000, acquired_at=TODAY - timedelta(days=int(5 * 365.25 / 2)))
    v = book_value(eq, years_default=5, salvage=1.0, today=TODAY)
    assert 5000 < v < 5010  # (10000-1)/2 + 1 ≈ 5000.5


def test_book_value_stops_at_salvage_never_zero_or_negative():
    """ครบอายุแล้วหยุดที่มูลค่าซาก ไม่เป็น 0 และไม่ติดลบ แม้เลยอายุมาหลายเท่า"""
    # +30 วัน เพื่อให้พ้นเส้นอายุเต็มแน่ ๆ (365.25*5 = 1826.25 วัน ปัดเป็น int แล้วยังขาดอยู่เศษวัน)
    for years_passed in (5, 10, 40):
        eq = _Fake(unit_value=2000, acquired_at=TODAY - timedelta(days=int(365.25 * years_passed) + 30))
        assert book_value(eq, 5, 1.0, TODAY) == 1.0


def test_book_value_brand_new_equals_cost():
    eq = _Fake(unit_value=2000, acquired_at=TODAY)
    assert book_value(eq, 5, 1.0, TODAY) == 2000.0


def test_book_value_future_acquired_date_does_not_go_above_cost():
    """ลงวันที่ได้มาไว้ในอนาคต (พิมพ์ผิด) ต้องไม่ทำให้มูลค่าเกินราคาทุน"""
    eq = _Fake(unit_value=2000, acquired_at=TODAY + timedelta(days=400))
    assert book_value(eq, 5, 1.0, TODAY) == 2000.0


def test_book_value_none_when_price_or_date_missing():
    """ไม่มีราคา หรือไม่มีวันที่ได้มา = คำนวณไม่ได้ ต้องคืน None ไม่ใช่เดาเป็น 0"""
    assert book_value(_Fake(unit_value=None, acquired_at=TODAY), 5, 1.0, TODAY) is None
    assert book_value(_Fake(unit_value=2000, acquired_at=None), 5, 1.0, TODAY) is None


def test_per_item_useful_life_beats_default_setting():
    """อายุการใช้งานรายชิ้นชนะค่ากลาง — ของอายุ 20 ปีเสื่อมช้ากว่าเกณฑ์กลาง 5 ปีชัดเจน"""
    acquired = TODAY - timedelta(days=int(365.25 * 5) + 30)
    slow = book_value(_Fake(2000, acquired, useful_life_years=20), 5, 1.0, TODAY)
    fast = book_value(_Fake(2000, acquired), 5, 1.0, TODAY)
    assert fast == 1.0
    assert slow > 1400


def test_override_wins_over_formula():
    eq = _Fake(unit_value=2000, acquired_at=TODAY - timedelta(days=9999), book_value_override=777.5)
    assert book_value(eq, 5, 1.0, TODAY) == 777.5


def test_cost_below_salvage_is_not_inflated():
    """ของราคาต่ำกว่ามูลค่าซาก (วัสดุชิ้นละไม่กี่สตางค์) ต้องไม่ถูกดันขึ้นเป็น 1 บาท"""
    eq = _Fake(unit_value=0.4, acquired_at=TODAY - timedelta(days=9999))
    assert book_value(eq, 5, 1.0, TODAY) == 0.4


# ---------- ผ่าน API จริง ----------

async def _cleanup_by_name(name: str) -> None:
    async with AsyncSessionLocal() as db:
        eq_ids = (await db.execute(select(Equipment.id).where(Equipment.name == name))).scalars().all()
        if not eq_ids:
            return
        await db.execute(delete(AuditLog).where(AuditLog.target_id.in_(eq_ids)))
        await db.execute(delete(Equipment).where(Equipment.id.in_(eq_ids)))
        await db.commit()


async def test_api_returns_book_value_and_override_round_trip(
    client: AsyncClient, admin_token: str, superadmin_token: str,
):
    """response ต้องมี book_value ที่คำนวณให้ · กรอกทับแล้วชนะ · ส่ง null แล้วกลับไปใช้ค่าคำนวณ

    มูลค่าตามบัญชีเป็นฟิลด์การเงิน — ตั้งแต่เฟส 8 แก้ได้เฉพาะ superadmin (ผู้ดูแลคลังยื่นคำขอแทน)
    """
    h = auth(admin_token)
    h_super = auth(superadmin_token)
    name = f"อุปกรณ์ทดสอบมูลค่า {uuid.uuid4().hex[:6]}"
    r = await client.post("/equipment", json={
        "code": f"{uuid.uuid4().int % 10**15:015d}", "name": name,
        "category_ids": [], "item_type": "durable", "quantity_total": 1,
        "image_urls": ["/uploads/test.jpg"],
        "unit_value": 10000,
        "acquired_at": (date.today() - timedelta(days=int(365.25 * 5) + 30)).isoformat(),
    }, headers=h)
    assert r.status_code == 201, r.text
    eq_id = r.json()["id"]
    try:
        # หมดอายุพอดี → เหลือมูลค่าซาก
        assert r.json()["unit_value"] == 10000
        assert r.json()["book_value"] == 1.0
        assert r.json()["book_value_override"] is None

        # กรอกทับ
        r2 = await client.patch(f"/equipment/{eq_id}", json={"book_value_override": 4200}, headers=h_super)
        assert r2.status_code == 200, r2.text
        assert r2.json()["book_value"] == 4200.0

        # ส่ง null = กลับไปใช้ค่าคำนวณ (อาศัย exclude_unset ใน update_equipment)
        r3 = await client.patch(f"/equipment/{eq_id}", json={"book_value_override": None}, headers=h_super)
        assert r3.status_code == 200, r3.text
        assert r3.json()["book_value_override"] is None
        assert r3.json()["book_value"] == 1.0
    finally:
        await _cleanup_by_name(name)


async def test_price_is_required_on_create_but_cannot_be_cleared_on_update(client: AsyncClient, admin_token: str):
    """ของทุกชิ้นต้องมีราคา — สร้างโดยไม่กรอกไม่ได้ และแก้ทีหลังก็ล้างทิ้งไม่ได้"""
    h = auth(admin_token)
    name = f"อุปกรณ์ทดสอบบังคับราคา {uuid.uuid4().hex[:6]}"
    base = {
        "code": f"{uuid.uuid4().int % 10**15:015d}", "name": name,
        "category_ids": [], "item_type": "durable", "quantity_total": 1,
        "image_urls": ["/uploads/test.jpg"],
    }
    assert (await client.post("/equipment", json=base, headers=h)).status_code == 422
    r = await client.post("/equipment", json={**base, "unit_value": 500, "acquired_at": "2024-01-15"}, headers=h)
    assert r.status_code == 201, r.text
    eq_id = r.json()["id"]
    try:
        # null = "ไม่แก้ราคา" ไม่ใช่ "ล้างราคา" — ค่าเดิมต้องอยู่ครบ
        r2 = await client.patch(f"/equipment/{eq_id}", json={"unit_value": None}, headers=h)
        assert r2.status_code == 200, r2.text
        assert r2.json()["unit_value"] == 500
        # 0 หรือติดลบไม่ใช่ราคาที่ถูกต้อง
        assert (await client.patch(f"/equipment/{eq_id}", json={"unit_value": 0}, headers=h)).status_code == 422
    finally:
        await _cleanup_by_name(name)
