"""นักศึกษาต้องเปิดดูใบคำขอของตัวเองได้ทุกสถานะ (pending = ใบร่าง, ยกเลิกแล้วก็ยังดูย้อนหลังได้)"""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.borrow_item import BorrowItem
from app.models.borrow_request import BorrowRequest
from app.models.equipment import Equipment
from app.models.notification import Notification
from tests.conftest import auth


async def _cleanup(req_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Notification).where(Notification.borrow_request_id == req_id))
        await db.execute(delete(BorrowItem).where(BorrowItem.borrow_request_id == req_id))
        await db.execute(delete(BorrowRequest).where(BorrowRequest.id == req_id))
        await db.commit()


@pytest.mark.asyncio(loop_scope="session")
async def test_pdf_available_for_pending_and_cancelled(
    client: AsyncClient, student_token: str, test_equipment: Equipment
):
    r = await client.post("/borrow-requests", headers=auth(student_token), json={
        "purpose": "ทดสอบดูใบร่าง",
        "items": [{"equipment_id": str(test_equipment.id), "quantity": 1}],
    })
    assert r.status_code == 201
    req_id = r.json()["id"]

    pending_pdf = await client.get(f"/borrow-requests/{req_id}/pdf", headers=auth(student_token))
    assert pending_pdf.status_code == 200
    assert pending_pdf.content.startswith(b"%PDF")

    assert (await client.patch(f"/borrow-requests/{req_id}/cancel",
                               headers=auth(student_token))).status_code == 200
    cancelled_pdf = await client.get(f"/borrow-requests/{req_id}/pdf", headers=auth(student_token))
    assert cancelled_pdf.status_code == 200
    assert cancelled_pdf.content.startswith(b"%PDF")

    await _cleanup(uuid.UUID(req_id))
