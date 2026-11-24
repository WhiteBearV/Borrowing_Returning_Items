"""กรอง/ค้นหาอุปกรณ์ตามห้อง (23 พ.ย. 69) — dropdown ห้องในหน้าจัดการอุปกรณ์ + ช่องค้นหาเจอด้วยเลขห้อง"""
import uuid

from httpx import AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.equipment import Equipment
from tests.conftest import auth


async def test_filter_and_search_by_location(client: AsyncClient, admin_token: str, student_token: str):
    tag = uuid.uuid4().hex[:6]
    room_a, room_b = f"ห้องกรองA-{tag}", f"ห้องกรองB-{tag}"
    name = f"อุปกรณ์ทดสอบกรองห้อง {tag}"
    # รุ่นเดียวกัน 3 หน่วย: 2 หน่วยอยู่ห้อง A · 1 หน่วยอยู่ห้อง B
    rows = [Equipment(id=uuid.uuid4(), code=f"TEST-LOC-{tag}-{k}", name=name, item_type="durable",
                      quantity_total=1, quantity_available=1, status="available", location=loc)
            for k, loc in enumerate([room_a, room_a, room_b])]
    async with AsyncSessionLocal() as db:
        db.add_all(rows)
        await db.commit()
    try:
        locs = (await client.get("/equipment/locations", headers=auth(admin_token))).json()
        assert {"location": room_a, "count": 2} in locs and {"location": room_b, "count": 1} in locs
        assert (await client.get("/equipment/locations", headers=auth(student_token))).status_code == 403

        # การ์ดรุ่นนับเฉพาะหน่วยในห้องที่เลือก ไม่ใช่ทั้งรุ่น
        g = (await client.get("/equipment/grouped", headers=auth(admin_token), params={"location": room_a})).json()
        assert g["total"] == 1 and g["items"][0]["unit_count"] == 2
        flat = (await client.get("/equipment", headers=auth(admin_token), params={"location": room_b})).json()
        assert [e["code"] for e in flat["items"]] == [rows[2].code]

        # พิมพ์ชื่อห้องในช่องค้นหาก็เจอ
        s = (await client.get("/equipment", headers=auth(admin_token), params={"search": f"กรองB-{tag}"})).json()
        assert [e["code"] for e in s["items"]] == [rows[2].code]
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(Equipment).where(Equipment.id.in_([r.id for r in rows])))
            await db.commit()


async def test_room_and_spot(client: AsyncClient, admin_token: str):
    """ห้อง + ตำแหน่งในห้อง: กรองห้องนับของในตู้รวม · ค้นด้วยตู้เจอ · ย้ายห้องล้างตำแหน่ง (รายชิ้น/หลายรายการ/ตรวจครุภัณฑ์)
    · ตรวจเจอของในตู้ห้องเดียวกัน = พบ ตำแหน่งไม่หาย"""
    from app.models.audit_log import AuditLog
    from app.models.stocktake import StocktakeRound

    tag = uuid.uuid4().hex[:6]
    room, other = f"ห้องตู้-{tag}", f"ห้องอื่น-{tag}"
    a, b, c = (Equipment(id=uuid.uuid4(), code=f"TEST-SPOT-{tag}-{k}", name=f"อุปกรณ์ทดสอบตู้ {tag} {k}",
                         item_type="durable", quantity_total=1, quantity_available=1, status="available",
                         location=room, location_detail=detail)
               for k, detail in enumerate([None, f"ตู้A-{tag} ชั้น3", f"ตู้B-{tag}"]))
    ids = [a.id, b.id, c.id]
    async with AsyncSessionLocal() as db:
        db.add_all([a, b, c])
        await db.commit()
    try:
        H = auth(admin_token)
        locs = (await client.get("/equipment/locations", headers=H)).json()
        assert {"location": room, "count": 3} in locs  # ตู้ไม่แตกเป็นห้องใหม่
        s = (await client.get("/equipment", headers=H, params={"search": f"ตู้A-{tag}"})).json()
        assert [e["code"] for e in s["items"]] == [b.code] and s["items"][0]["location_detail"] == f"ตู้A-{tag} ชั้น3"

        # ตรวจห้อง: เจอของในตู้ = พบ ตำแหน่งยังอยู่ · รายการในรอบโชว์ตำแหน่ง
        rnd = (await client.post("/stocktake/rounds", headers=H, json={"location": room})).json()
        assert {i["location_detail"] for i in rnd["items"]} == {None, f"ตู้A-{tag} ชั้น3", f"ตู้B-{tag}"}
        r = await client.post(f"/stocktake/rounds/{rnd['id']}/scan", headers=H, json={"equipment_id": str(b.id)})
        assert r.json()["outcome"] == "found"
        assert (await client.get(f"/equipment/{b.id}", headers=H)).json()["location_detail"] == f"ตู้A-{tag} ชั้น3"

        # แก้รายชิ้น: ย้ายห้องโดยไม่ส่งตำแหน่ง = ล้าง · ส่งตำแหน่งมาด้วย = ใช้ค่าที่ส่ง
        r = await client.patch(f"/equipment/{b.id}", headers=H, json={"location": other})
        assert r.status_code == 200 and r.json()["location_detail"] is None
        r = await client.patch(f"/equipment/{b.id}", headers=H, json={"location": room, "location_detail": "  ตู้C  "})
        assert r.json()["location"] == room and r.json()["location_detail"] == "ตู้C"

        # แก้หลายรายการ: ล้างเฉพาะแถวที่ห้องเปลี่ยนจริง
        async with AsyncSessionLocal() as db:
            (await db.get(Equipment, c.id)).location = other
            await db.commit()
        r = await client.patch("/equipment/bulk-update", headers=H,
                               json={"equipment_ids": [str(b.id), str(c.id)], "update": {"location": room}})
        assert r.status_code == 200, r.text
        got = {e: (await client.get(f"/equipment/{e}", headers=H)).json()["location_detail"] for e in (b.id, c.id)}
        assert got == {b.id: "ตู้C", c.id: None}

        # ตรวจครุภัณฑ์ "ย้ายมาห้องนี้" = ห้องใหม่ ตำแหน่งเดิมล้าง
        async with AsyncSessionLocal() as db:
            row = await db.get(Equipment, a.id)
            row.location, row.location_detail = other, "ตู้เก่า"
            await db.commit()
        r = await client.post(f"/stocktake/rounds/{rnd['id']}/scan", headers=H, json={"equipment_id": str(a.id)})
        assert r.json()["outcome"] == "found"  # อยู่ในรายการรอบอยู่แล้ว → ย้ายทะเบียนกลับ
        a_now = (await client.get(f"/equipment/{a.id}", headers=H)).json()
        assert a_now["location"] == room and a_now["location_detail"] is None
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(StocktakeRound).where(StocktakeRound.location.in_([room, other])))
            await db.execute(delete(AuditLog).where(AuditLog.target_id.in_(ids)))
            await db.execute(delete(AuditLog).where(AuditLog.detail["location"].astext.in_([room, other])))
            await db.execute(delete(Equipment).where(Equipment.id.in_(ids)))
            await db.commit()
