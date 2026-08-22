"""Tests: ทำเครื่องหมายว่าอ่านแล้วทั้งหมดในคราวเดียว (feedback UX — เดิมต้องกดทีละรายการ)"""
import uuid

from httpx import AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.notification import Notification
from tests.conftest import auth


async def _make_notification(user_id: uuid.UUID, is_read: bool = False) -> uuid.UUID:
    n_id = uuid.uuid4()
    async with AsyncSessionLocal() as db:
        db.add(Notification(
            id=n_id, user_id=user_id, type="due_soon", channel="in_app",
            message="ทดสอบแจ้งเตือน", is_read=is_read,
        ))
        await db.commit()
    return n_id


async def _cleanup(*ids: uuid.UUID) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Notification).where(Notification.id.in_(ids)))
        await db.commit()


async def test_mark_all_read_marks_only_own_unread(client: AsyncClient, student_token: str, admin_token: str, test_student, test_admin):
    h_student = auth(student_token)
    unread_id = await _make_notification(test_student.id, is_read=False)
    already_read_id = await _make_notification(test_student.id, is_read=True)
    other_user_unread_id = await _make_notification(test_admin.id, is_read=False)
    try:
        r = await client.patch("/notifications/read-all", headers=h_student)
        assert r.status_code == 200, r.text

        r = await client.get("/notifications/me", params={"page": 1, "page_size": 50}, headers=h_student)
        items = {i["id"]: i["is_read"] for i in r.json()["items"]}
        assert items[str(unread_id)] is True
        assert items[str(already_read_id)] is True

        # ไม่แตะของ user อื่น
        r = await client.get("/notifications/me", params={"page": 1, "page_size": 50}, headers=auth(admin_token))
        admin_items = {i["id"]: i["is_read"] for i in r.json()["items"]}
        assert admin_items[str(other_user_unread_id)] is False
    finally:
        await _cleanup(unread_id, already_read_id, other_user_unread_id)
