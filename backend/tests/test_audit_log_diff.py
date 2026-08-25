"""Audit log เก็บ diff ก่อน/หลังจริง (ไม่ใช่แค่ชื่อฟิลด์ที่เปลี่ยน) — ครอบคลุม update_equipment,
bulk_update_equipment, import commit (action=update), และ update_bundle
"""
import uuid

import openpyxl
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.equipment import Equipment
from app.services.audit_service import diff_fields
from tests.conftest import auth


async def _make_equipment(client: AsyncClient, admin_header: dict, **overrides) -> str:
    suffix = uuid.uuid4().hex[:6].upper()
    body = {
        "code": f"AUDDIFF-{suffix}", "name": f"อุปกรณ์ทดสอบ diff {suffix}",
        "category_ids": [], "item_type": "durable", "quantity_total": 1,
        "image_urls": ["/uploads/test.jpg"],
    }
    body.update(overrides)
    r = await client.post("/equipment", json=body, headers=admin_header)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _cleanup(*eq_ids: str) -> None:
    async with AsyncSessionLocal() as db:
        for eq_id in eq_ids:
            await db.execute(delete(AuditLog).where(AuditLog.target_id == uuid.UUID(eq_id)))
            await db.execute(delete(Equipment).where(Equipment.id == uuid.UUID(eq_id)))
        await db.commit()


def test_diff_fields_only_returns_changed_values():
    class Fake:
        code = "A001"
        name = "เดิม"
        location = "15310"

    diffs = diff_fields(Fake(), {"code": "A001", "name": "ใหม่", "location": "15310"})
    assert diffs == {"name": ["เดิม", "ใหม่"]}  # code/location ไม่เปลี่ยน ไม่ต้องอยู่ใน diff


async def test_update_equipment_logs_before_after_for_every_changed_field(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    eq_id = await _make_equipment(client, h, location="15310", description="เดิม")
    try:
        r = await client.patch(f"/equipment/{eq_id}", json={
            "name": "ชื่อใหม่", "location": "15399", "description": "ใหม่",
        }, headers=h)
        assert r.status_code == 200, r.text

        async with AsyncSessionLocal() as db:
            log = (await db.execute(
                select(AuditLog).where(AuditLog.target_id == uuid.UUID(eq_id), AuditLog.action == "update_equipment")
            )).scalars().first()
            changes = log.detail["changes"]
            assert changes["location"] == ["15310", "15399"]
            assert changes["description"] == ["เดิม", "ใหม่"]
            assert changes["name"][1] == "ชื่อใหม่"
    finally:
        await _cleanup(eq_id)


async def test_update_equipment_category_ids_diff_uses_names(
    client: AsyncClient, admin_token: str, test_category
):
    h = auth(admin_token)
    eq_id = await _make_equipment(client, h, category_ids=[str(test_category.id)])
    new_cat_id = None
    try:
        r = await client.post("/equipment-categories", json={"name": f"หมวดทดสอบ diff {uuid.uuid4().hex[:6]}"}, headers=h)
        assert r.status_code == 201, r.text
        new_cat_id = r.json()["id"]
        r = await client.patch(f"/equipment/{eq_id}", json={"category_ids": [new_cat_id]}, headers=h)
        assert r.status_code == 200, r.text

        async with AsyncSessionLocal() as db:
            log = (await db.execute(
                select(AuditLog).where(AuditLog.target_id == uuid.UUID(eq_id), AuditLog.action == "update_equipment")
            )).scalars().first()
            old_names, new_names = log.detail["changes"]["category_ids"]
            assert old_names == [test_category.name]
    finally:
        await _cleanup(eq_id)
        if new_cat_id:
            async with AsyncSessionLocal() as db:
                from app.models.equipment_category import EquipmentCategory
                await db.execute(delete(EquipmentCategory).where(EquipmentCategory.id == uuid.UUID(new_cat_id)))
                await db.commit()


async def test_bulk_update_equipment_logs_set_shape(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    ids = [await _make_equipment(client, h) for _ in range(2)]
    try:
        r = await client.patch("/equipment/bulk-update", json={
            "equipment_ids": ids, "update": {"location": "15399"},
        }, headers=h)
        assert r.status_code == 200, r.text

        async with AsyncSessionLocal() as db:
            log = (await db.execute(
                select(AuditLog).where(AuditLog.action == "bulk_update_equipment", AuditLog.target_id == uuid.UUID(ids[0]))
            )).scalars().first()
            assert log.detail["set"] == {"location": "15399"}
            assert log.detail["count"] == 2
    finally:
        await _cleanup(*ids)


def _register_file(tmp_path, code, name, broken=False):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "คณะเทคโนฯดิจิทัล"
    for _ in range(4):
        ws.append([None])
    if broken:
        ws.append([1, code, name, 1000, None, None, "X", None, None, None, "คณะ", "15399"])
    else:
        ws.append([1, code, name, 1000, None, "P", None, None, None, None, "คณะ", "15310"])
    path = tmp_path / f"register-{uuid.uuid4().hex[:6]}.xlsx"
    wb.save(path)
    return path


async def test_import_commit_update_action_logs_real_diff(client: AsyncClient, admin_token: str, tmp_path):
    h = auth(admin_token)
    code = f"AUDDIFF-{uuid.uuid4().hex[:6].upper()}"
    eq_id = await _make_equipment(client, h, code=code, name="ชื่อเดิมในระบบ", location="15310")
    try:
        path = _register_file(tmp_path, code, "ชื่อใหม่จากทะเบียน", broken=True)
        with open(path, "rb") as f:
            res = await client.post(
                "/equipment/import/preview",
                files={"file": ("register.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                headers=h,
            )
        assert res.status_code == 200, res.text
        draft = res.json()
        row = next(r for r in draft["rows"] if r["code"] == code)
        assert row["action"] == "update"

        res = await client.post(
            f"/equipment/import/{draft['import_id']}/commit",
            json={"filename": "register.xlsx", "rows": [row]},
            headers=h,
        )
        assert res.status_code == 200, res.text
        assert res.json()["update"] == 1

        async with AsyncSessionLocal() as db:
            log = (await db.execute(
                select(AuditLog).where(AuditLog.target_id == uuid.UUID(eq_id), AuditLog.action == "update_equipment")
            )).scalars().first()
            changes = log.detail["changes"]
            assert changes["name"] == ["ชื่อเดิมในระบบ", "ชื่อใหม่จากทะเบียน"]
            assert changes["status"] == ["available", "damaged"]
    finally:
        await _cleanup(eq_id)


async def test_update_bundle_logs_diff(client: AsyncClient, admin_token: str):
    h = auth(admin_token)
    member_id = await _make_equipment(client, h, item_type="material")
    bundle_id = None
    try:
        r = await client.post("/bundles", headers=h, json={
            "name": "ชุดทดสอบ diff", "items": [{"equipment_id": member_id, "quantity": 1}],
        })
        assert r.status_code == 201, r.text
        bundle_id = r.json()["id"]

        r = await client.patch(f"/bundles/{bundle_id}", json={"name": "ชุดทดสอบ diff (แก้แล้ว)"}, headers=h)
        assert r.status_code == 200, r.text

        async with AsyncSessionLocal() as db:
            log = (await db.execute(
                select(AuditLog).where(AuditLog.target_id == uuid.UUID(bundle_id), AuditLog.action == "update_bundle")
            )).scalars().first()
            assert log.detail["changes"]["name"] == ["ชุดทดสอบ diff", "ชุดทดสอบ diff (แก้แล้ว)"]
    finally:
        if bundle_id:
            from app.models.bundle import Bundle, BundleItem
            async with AsyncSessionLocal() as db:
                await db.execute(delete(AuditLog).where(AuditLog.target_id == uuid.UUID(bundle_id)))
                await db.execute(delete(BundleItem).where(BundleItem.bundle_id == uuid.UUID(bundle_id)))
                await db.execute(delete(Bundle).where(Bundle.id == uuid.UUID(bundle_id)))
                await db.commit()
        await _cleanup(member_id)
