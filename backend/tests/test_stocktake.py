"""ตรวจครุภัณฑ์รายห้องด้วย QR (16 พ.ย. 69) — found / moved_here / on_loan / missing / สแกนซ้ำ / สแกนพร้อมกัน"""
import asyncio
import uuid
from datetime import date, timedelta

from httpx import AsyncClient
from sqlalchemy import delete, or_, select

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.borrow_item import BorrowItem
from app.models.borrow_request import BorrowRequest
from app.models.equipment import Equipment
from app.models.notification import Notification
from app.models.stocktake import StocktakeRound
from tests.conftest import auth


def r_round(resp) -> list[dict]:
    return resp.json()["items"]


async def _make(location: str, n: int) -> list[Equipment]:
    rows = []
    async with AsyncSessionLocal() as db:
        for k in range(n):
            eid = uuid.uuid4()
            rows.append(Equipment(id=eid, code=f"TEST-ST-{eid.hex[:6].upper()}", name=f"อุปกรณ์ทดสอบตรวจห้อง {k}",
                                  item_type="durable", quantity_total=1, quantity_available=1,
                                  status="available", location=location,
                                  asset_number=f"99-999-999-{eid.int % 1000:03d}-{k:04d}"))
        db.add_all(rows)
        await db.commit()
    return rows


async def _mark_found_normal(client: AsyncClient, token: str, round_id: str) -> None:
    """ของที่เจอแล้วต้องติ๊กสภาพก่อนปิดรอบ (23 พ.ย. 69) — เทสที่ไม่ได้สนเรื่องสภาพติ๊กปกติให้หมด"""
    rnd = (await client.get(f"/stocktake/rounds/{round_id}", headers=auth(token))).json()
    for i in rnd["items"]:
        if i["result"] in ("found", "moved_here") and not i["condition"]:
            r = await client.post(f"/stocktake/rounds/{round_id}/items/{i['id']}/condition", headers=auth(token),
                                  json={"condition": "normal"})
            assert r.status_code == 200, r.text


async def test_stocktake_round_flow(client: AsyncClient, admin_token: str, student_token: str):
    room = f"ห้องทดสอบ-{uuid.uuid4().hex[:6]}"
    other = f"ห้องทดสอบอื่น-{uuid.uuid4().hex[:6]}"
    a, b, c, d = await _make(room, 4)
    (stray,) = await _make(other, 1)
    ids = [e.id for e in (a, b, c, d, stray)]
    rid = None
    try:
        # d ถูกยืมอยู่ → ต้องติด on_loan ตั้งแต่เปิดรอบ ไม่ใช่ "ไม่พบ"
        r = await client.post("/borrow-requests", headers=auth(student_token), json={
            "purpose": "stocktake", "requested_due_date": str(date.today() + timedelta(days=3)),
            "items": [{"equipment_id": str(d.id), "quantity": 1}]})
        assert r.status_code == 201, r.text
        rid = r.json()["id"]
        assert (await client.patch(f"/borrow-requests/{rid}/approve", headers=auth(admin_token))).status_code == 200

        locs = (await client.get("/stocktake/locations", headers=auth(admin_token))).json()
        assert any(x["location"] == room and x["count"] == 4 for x in locs)
        assert (await client.get("/stocktake/locations", headers=auth(student_token))).status_code == 403

        # ดูของในห้องคร่าว ๆ — ครบ 4 ชิ้น d บอกผู้ยืม และไม่เปิดรอบ
        items = (await client.get("/stocktake/locations/items", headers=auth(admin_token),
                                  params={"location": room})).json()
        assert sorted(i["code"] for i in items) == sorted(e.code for e in (a, b, c, d))
        assert [i["holder_name"] is not None for i in items if i["id"] == str(d.id)] == [True]
        assert not any(x["open_round_id"] for x in (await client.get("/stocktake/locations", headers=auth(admin_token))).json()
                       if x["location"] == room)
        assert (await client.get("/stocktake/locations/items", headers=auth(student_token),
                                 params={"location": room})).status_code == 403

        # สองเครื่องสแกน QR ห้องพร้อมกัน = รอบเดียวกัน
        r1, r2 = await asyncio.gather(*[client.post("/stocktake/rounds", headers=auth(admin_token),
                                                    json={"location": room}) for _ in range(2)])
        assert r1.status_code == r2.status_code == 201, (r1.text, r2.text)
        assert r1.json()["id"] == r2.json()["id"]
        rnd = r1.json()
        assert rnd["counts"] == {"pending": 3, "on_loan": 1}

        base = f"/stocktake/rounds/{rnd['id']}"
        r = await client.post(f"{base}/scan", headers=auth(admin_token), json={"equipment_id": str(a.id)})
        assert r.json()["outcome"] == "found"
        # เลขครุภัณฑ์พิมพ์ติดกันก็จับคู่ได้ · สแกนสองเครื่องพร้อมกันไม่ชน
        digits = b.asset_number.replace("-", "")
        res = await asyncio.gather(*[client.post(f"{base}/scan", headers=auth(admin_token), json={"code": digits})
                                     for _ in range(2)])
        assert sorted(x.json()["outcome"] for x in res) == ["already", "found"], [x.text for x in res]
        # ของห้องอื่น → ย้ายมาห้องนี้
        r = await client.post(f"{base}/scan", headers=auth(admin_token), json={"code": stray.code})
        assert r.json()["outcome"] == "moved_here" and r.json()["item"]["from_location"] == other
        assert (await client.post(f"{base}/scan", headers=auth(admin_token), json={"code": "NO-SUCH"})).status_code == 404

        # เจอแล้วยังไม่ติ๊กสภาพ = ปิดรอบไม่ได้
        r = await client.post(f"{base}/finish", headers=auth(admin_token), json={})
        assert r.status_code == 400 and "ยังไม่ได้เลือกสภาพ" in r.json()["detail"]
        item_of = {i["equipment_id"]: i["id"] for i in r_round(await client.get(base, headers=auth(admin_token)))}
        cond = lambda eq: f"{base}/items/{item_of[str(eq.id)]}/condition"  # noqa: E731
        # ไม่ใช่ปกติ = บังคับหมายเหตุ
        r = await client.post(cond(a), headers=auth(admin_token), json={"condition": "damaged", "note": "  "})
        assert r.status_code == 422
        r = await client.post(cond(a), headers=auth(admin_token), json={"condition": "damaged", "note": "ขาหัก"})
        assert r.status_code == 200, r.text
        # กดจากรายการ (ไม่ได้สแกน) ติ๊กสูญหาย = ไม่พบทันที
        r = await client.post(cond(c), headers=auth(admin_token), json={"condition": "lost", "note": "หาไม่เจอทั้งห้อง"})
        assert next(i for i in r.json()["items"] if i["equipment_id"] == str(c.id))["result"] == "missing"
        await _mark_found_normal(client, admin_token, rnd["id"])
        x = await client.get(f"{base}/report.xlsx", headers=auth(admin_token))
        assert x.status_code == 200 and x.content[:2] == b"PK"
        import io
        import openpyxl
        ws = openpyxl.load_workbook(io.BytesIO(x.content)).active
        row_a = next(r for r in range(5, ws.max_row) if ws.cell(r, 2).value in (a.asset_number, a.code))
        assert [ws.cell(row_a, c).value for c in range(6, 11)] == [None, "✓", None, None, None]
        assert "ขาหัก" in ws.cell(row_a, 18).value
        assert "." not in ws["N3"].value  # ชื่อเดือนเต็ม ไม่ใช่ตัวย่อ "พ.ย."
        # พรีวิวบนเว็บ = แถวเดียวกับไฟล์
        pv = (await client.get(f"{base}/report-preview", headers=auth(admin_token))).json()
        assert pv["headers"][5] == "ปกติ" and len(pv["rows"]) == ws.max_row - 5
        assert next(r for r in pv["rows"] if r[1] in (a.asset_number, a.code))[6] == "✓"

        r = await client.post(f"{base}/finish", headers=auth(admin_token), json={"note": "ทดสอบ"})
        assert r.json()["counts"] == {"found": 2, "moved_here": 1, "missing": 1, "on_loan": 1}
        assert (await client.post(f"{base}/scan", headers=auth(admin_token),
                                  json={"equipment_id": str(c.id)})).status_code == 400
        pdf = await client.get(f"{base}/report.pdf", headers=auth(admin_token))
        assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
        qr = await client.get("/stocktake/locations/qr.pdf", headers=auth(admin_token), params={"location": room})
        assert qr.status_code == 200 and qr.content[:4] == b"%PDF"

        async with AsyncSessionLocal() as db:
            assert (await db.get(Equipment, stray.id)).location == room
    finally:
        async with AsyncSessionLocal() as db:
            round_ids = (await db.execute(select(StocktakeRound.id).where(StocktakeRound.location == room))).scalars().all()
            targets = [*ids, *round_ids]
            if rid:
                req_id = uuid.UUID(rid)
                item_ids = (await db.execute(
                    select(BorrowItem.id).where(BorrowItem.borrow_request_id == req_id))).scalars().all()
                targets += [req_id, *item_ids]
                await db.execute(delete(Notification).where(Notification.borrow_request_id == req_id))
                await db.execute(delete(BorrowItem).where(BorrowItem.borrow_request_id == req_id))
                await db.execute(delete(BorrowRequest).where(BorrowRequest.id == req_id))
            await db.execute(delete(AuditLog).where(AuditLog.target_id.in_(targets)))
            await db.execute(delete(Notification).where(or_(
                Notification.message.like(f"%{room}%"), Notification.message.like(f"%{rid}%") if rid else False)))
            await db.execute(delete(StocktakeRound).where(StocktakeRound.location == room))
            await db.execute(delete(Equipment).where(Equipment.id.in_(ids)))
            await db.commit()


async def test_two_rooms_audited_together(client: AsyncClient, admin_token: str):
    """รีวิว: ของทะเบียนห้อง A ที่รอบห้อง B สแกนเจอ → ปิดรอบ A ต้องเป็น "พบที่ห้องอื่น" ไม่ใช่ "ไม่พบ"
    และถ้า A สแกนเจอตัวจริงทีหลัง ทะเบียนต้องย้ายกลับมา A"""
    room_a, room_b = f"ห้องทดสอบA-{uuid.uuid4().hex[:6]}", f"ห้องทดสอบB-{uuid.uuid4().hex[:6]}"
    e1, e2 = await _make(room_a, 2)
    (b1,) = await _make(room_b, 1)
    ids = [e1.id, e2.id, b1.id]
    try:
        ra = (await client.post("/stocktake/rounds", headers=auth(admin_token), json={"location": room_a})).json()
        rb = (await client.post("/stocktake/rounds", headers=auth(admin_token), json={"location": room_b})).json()
        for eq in (e1, e2):  # ทั้งสองชิ้นถูกสแกนในห้อง B
            r = await client.post(f"/stocktake/rounds/{rb['id']}/scan", headers=auth(admin_token),
                                  json={"equipment_id": str(eq.id)})
            assert r.json()["outcome"] == "moved_here"
        # e2 อยู่ห้อง A จริง (B สแกนผิด) → A สแกนเจอ = พบ + ย้ายทะเบียนกลับ
        r = await client.post(f"/stocktake/rounds/{ra['id']}/scan", headers=auth(admin_token),
                              json={"equipment_id": str(e2.id)})
        assert r.json()["outcome"] == "found"
        await _mark_found_normal(client, admin_token, ra["id"])
        r = await client.post(f"/stocktake/rounds/{ra['id']}/finish", headers=auth(admin_token), json={})
        res = {i["equipment_id"]: i for i in r.json()["items"]}
        assert res[str(e1.id)]["result"] == "elsewhere" and res[str(e1.id)]["from_location"] == room_b
        assert "missing" not in r.json()["counts"]
        async with AsyncSessionLocal() as db:
            assert (await db.get(Equipment, e2.id)).location == room_a
            assert (await db.get(Equipment, e1.id)).location == room_b
    finally:
        async with AsyncSessionLocal() as db:
            round_ids = (await db.execute(select(StocktakeRound.id).where(
                StocktakeRound.location.in_([room_a, room_b])))).scalars().all()
            await db.execute(delete(AuditLog).where(AuditLog.target_id.in_([*ids, *round_ids])))
            await db.execute(delete(StocktakeRound).where(StocktakeRound.location.in_([room_a, room_b])))
            await db.execute(delete(Equipment).where(Equipment.id.in_(ids)))
            await db.commit()


async def test_undo_scan_materials_excluded_and_summary(client: AsyncClient, admin_token: str):
    """23 พ.ย. 69: สแกนผิดยกเลิกได้ (ย้ายกลับห้อง+ตู้เดิม) · ตรวจเฉพาะครุภัณฑ์ · ใบรวมทุกห้องใช้ผลตรวจล่าสุด"""
    H = auth(admin_token)
    room, other = f"ห้องทดสอบยก-{uuid.uuid4().hex[:6]}", f"ห้องทดสอบเดิม-{uuid.uuid4().hex[:6]}"
    (a,) = await _make(room, 1)
    (stray,) = await _make(other, 1)
    mat_id = uuid.uuid4()
    async with AsyncSessionLocal() as db:
        (await db.get(Equipment, stray.id)).location_detail = "ตู้เดิม"
        db.add(Equipment(id=mat_id, code=f"TEST-ST-M{mat_id.hex[:6]}", name="วัสดุทดสอบตรวจห้อง", item_type="material",
                         quantity_total=1, quantity_available=1, status="available", location=room))
        await db.commit()
    ids = [a.id, stray.id, mat_id]
    try:
        rnd = (await client.post("/stocktake/rounds", headers=H, json={"location": room})).json()
        assert [i["equipment_id"] for i in rnd["items"]] == [str(a.id)]  # วัสดุไม่อยู่ในรอบ
        base = f"/stocktake/rounds/{rnd['id']}"

        # สแกนของห้องอื่นผิด → ยกเลิก = ทะเบียนกลับห้อง+ตู้เดิม และหายจากรอบ
        r = (await client.post(f"{base}/scan", headers=H, json={"equipment_id": str(stray.id)})).json()
        assert r["outcome"] == "moved_here" and r["item"]["from_location"] == other
        r = await client.post(f"{base}/items/{r['item']['id']}/undo", headers=H)
        assert r.status_code == 200 and len(r.json()["items"]) == 1
        s_now = (await client.get(f"/equipment/{stray.id}", headers=H)).json()
        assert (s_now["location"], s_now["location_detail"]) == (other, "ตู้เดิม")

        # สแกนของในห้อง + ติ๊ก → ยกเลิก = กลับเป็นยังไม่ตรวจ ล้างสภาพ
        item_id = rnd["items"][0]["id"]
        await client.post(f"{base}/scan", headers=H, json={"equipment_id": str(a.id)})
        await client.post(f"{base}/items/{item_id}/condition", headers=H, json={"condition": "normal"})
        it = (await client.post(f"{base}/items/{item_id}/undo", headers=H)).json()["items"][0]
        assert (it["result"], it["condition"]) == ("pending", None)
        assert (await client.post(f"{base}/items/{item_id}/undo", headers=H)).status_code == 400  # ยังไม่ได้สแกน

        # ใบรวม: ติ๊กเสื่อมสภาพแล้ว ต้องขึ้นในแถวของชิ้นนี้ · ชิ้นที่ไม่เคยตรวจ = ว่าง
        await client.post(f"{base}/items/{item_id}/condition", headers=H, json={"condition": "deteriorated", "note": "สีลอก"})
        pv = (await client.get("/stocktake/summary-preview", headers=H)).json()
        assert pv["date"].startswith("ข้อมูล ณ วันที่")
        row_a = next(r for r in pv["rows"] if r[1] == a.asset_number)
        assert row_a[7] == "✓" and "สีลอก" in row_a[17] and row_a[11] == room
        row_s = next(r for r in pv["rows"] if r[1] == stray.asset_number)
        assert row_s[5:10] == [None] * 5 and row_s[17] == "ยังไม่เคยตรวจ"
        assert not any(r[2] == "วัสดุทดสอบตรวจห้อง" for r in pv["rows"])
        for ext, magic in (("xlsx", b"PK"), ("pdf", b"%PDF")):
            f = await client.get(f"/stocktake/summary.{ext}", headers=H)
            assert f.status_code == 200 and f.content[:len(magic)] == magic
    finally:
        async with AsyncSessionLocal() as db:
            round_ids = (await db.execute(select(StocktakeRound.id).where(StocktakeRound.location == room))).scalars().all()
            await db.execute(delete(AuditLog).where(AuditLog.target_id.in_([*ids, *round_ids])))
            await db.execute(delete(StocktakeRound).where(StocktakeRound.location == room))
            await db.execute(delete(Equipment).where(Equipment.id.in_(ids)))
            await db.commit()


async def test_lost_then_found_and_lowercase_code(client: AsyncClient, admin_token: str):
    """QA 23 พ.ย. 69 — ติ๊กสูญหายแล้วสแกนเจอ = ต้องเลือกสภาพใหม่ · ของย้ายมาติ๊กสูญหายไม่ได้ · พิมพ์รหัสตัวเล็กก็เจอ"""
    H = auth(admin_token)
    room = f"ห้องทดสอบ-{uuid.uuid4().hex[:6]}"
    other = f"ห้องทดสอบอื่น-{uuid.uuid4().hex[:6]}"
    a, b = await _make(room, 2)
    (stray,) = await _make(other, 1)
    ids = [a.id, b.id, stray.id]
    try:
        rnd = (await client.post("/stocktake/rounds", headers=H, json={"location": room})).json()
        base = f"/stocktake/rounds/{rnd['id']}"
        ia = next(i for i in rnd["items"] if i["equipment_id"] == str(a.id))
        assert (await client.post(f"{base}/items/{ia['id']}/condition", headers=H,
                                  json={"condition": "lost", "note": "หาไม่เจอ"})).status_code == 200
        it = (await client.post(f"{base}/scan", headers=H, json={"equipment_id": str(a.id)})).json()["item"]
        assert (it["result"], it["condition"]) == ("found", None)

        r = await client.post(f"{base}/scan", headers=H, json={"code": f" {b.code.lower()} "})
        assert r.status_code == 200 and r.json()["outcome"] == "found", r.text

        moved = (await client.post(f"{base}/scan", headers=H, json={"equipment_id": str(stray.id)})).json()["item"]
        assert (await client.post(f"{base}/items/{moved['id']}/condition", headers=H,
                                  json={"condition": "lost", "note": "x"})).status_code == 400
    finally:
        async with AsyncSessionLocal() as db:
            round_ids = (await db.execute(select(StocktakeRound.id).where(StocktakeRound.location == room))).scalars().all()
            await db.execute(delete(AuditLog).where(AuditLog.target_id.in_([*ids, *round_ids])))
            await db.execute(delete(StocktakeRound).where(StocktakeRound.location == room))
            await db.execute(delete(Equipment).where(Equipment.id.in_(ids)))
            await db.commit()
