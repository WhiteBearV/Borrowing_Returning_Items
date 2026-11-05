from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile

from app.dependencies import get_current_user
from app.models.user import User
from app.services import feedback_service

router = APIRouter(prefix="/feedback", tags=["feedback"])


@router.post("", status_code=204)
async def send_feedback(
    request: Request,
    kind: Literal["bug", "suggestion"] = Form(...),
    detail: str = Form(..., max_length=5000),
    page_url: str | None = Form(None, max_length=500),
    files: list[UploadFile] = File([]),
    user: User = Depends(get_current_user),
) -> None:
    """ปุ่ม "แจ้งปัญหา / ข้อเสนอแนะ" — ผู้ใช้ที่ล็อกอินแล้วทุกระดับส่งรายละเอียด + รูปหลักฐานถึงผู้พัฒนาทางอีเมล"""
    await feedback_service.send_feedback(
        user, kind, detail, page_url, request.headers.get("user-agent"), files)
