"""ตรวจครุภัณฑ์รายห้องด้วย QR — เจ้าหน้าที่เท่านั้น (logic อยู่ที่ stocktake_service)"""
import asyncio
import uuid
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.dependencies import get_db, require_admin
from app.models.user import User
from app.routers.equipment import _forwarded_frontend_origin
from app.schemas.stocktake import (
    RoomItem, StocktakeConditionRequest, StocktakeFinishRequest, StocktakeLocation, StocktakeRoundCreate, StocktakeRoundResponse, StocktakeRoundSummary,
    StocktakeScanRequest, StocktakeScanResponse,
)
from app.services import stocktake_service
from app.utils.pdf import generate_room_qr_pdf, generate_stocktake_pdf, generate_stocktake_summary_pdf
from app.utils.qrcode_gen import generate_qr_png
from app.utils.stocktake_xlsx import generate_stocktake_xlsx, preview_rows, summary_head, xlsx_rows
from app.utils.stocktake_xlsx import preview as stocktake_xlsx_preview

router = APIRouter(prefix="/stocktake", tags=["stocktake"])


@router.get("/locations", response_model=list[StocktakeLocation])
async def list_locations(
    _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
) -> list[StocktakeLocation]:
    return await stocktake_service.list_locations(db)


@router.get("/locations/items", response_model=list[RoomItem])
async def room_items(
    location: str = Query(..., min_length=1),
    admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
) -> list[RoomItem]:
    """ของในห้องตามทะเบียน — ดูคร่าว ๆ ก่อนตรวจ ไม่เปิดรอบ"""
    return await stocktake_service.room_items(db, admin, location)


@router.get("/locations/qr.pdf")
async def room_qr_pdf(
    request: Request, location: list[str] | None = Query(None),
    _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
) -> Response:
    """QR ประจำห้องสำหรับพิมพ์ติดหน้าห้อง — ไม่ระบุ location = ทุกห้อง · QR = ลิงก์หน้าตรวจของห้องนั้น"""
    origin = _forwarded_frontend_origin(request) or settings.FRONTEND_URL
    rooms = [r for r in await stocktake_service.list_locations(db) if not location or r.location in location]
    pdf = generate_room_qr_pdf([
        (r.location, r.count, generate_qr_png(f"{origin}/admin/stocktake?location={quote(r.location)}"))
        for r in rooms
    ])
    return Response(content=pdf, media_type="application/pdf", headers={"Cache-Control": "no-store"})


@router.get("/rounds", response_model=list[StocktakeRoundSummary])
async def list_rounds(
    location: str | None = None,
    _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
) -> list[StocktakeRoundSummary]:
    return await stocktake_service.list_rounds(db, location)


@router.post("/rounds", response_model=StocktakeRoundResponse, status_code=201)
async def start_round(
    body: StocktakeRoundCreate,
    admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
) -> StocktakeRoundResponse:
    """เปิดรอบตรวจห้อง (มีรอบค้างของห้องนี้อยู่แล้ว = คืนรอบเดิม)"""
    return await stocktake_service.start_round(db, admin, body.location)


@router.get("/rounds/{round_id}", response_model=StocktakeRoundResponse)
async def get_round(
    round_id: uuid.UUID,
    _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
) -> StocktakeRoundResponse:
    return await stocktake_service.get_round(db, round_id)


@router.post("/rounds/{round_id}/scan", response_model=StocktakeScanResponse)
async def scan(
    round_id: uuid.UUID, body: StocktakeScanRequest,
    admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
) -> StocktakeScanResponse:
    return await stocktake_service.scan(db, admin, round_id, body)


@router.post("/rounds/{round_id}/finish", response_model=StocktakeRoundResponse)
async def finish(
    round_id: uuid.UUID, body: StocktakeFinishRequest,
    admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
) -> StocktakeRoundResponse:
    return await stocktake_service.finish(db, admin, round_id, body.note)


@router.post("/rounds/{round_id}/items/{item_id}/condition", response_model=StocktakeRoundResponse)
async def set_condition(
    round_id: uuid.UUID, item_id: uuid.UUID, body: StocktakeConditionRequest,
    admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
) -> StocktakeRoundResponse:
    """ติ๊กสภาพ (ปกติ/ชำรุด/เสื่อมสภาพ/สูญหาย/รายการผิดประเภท) + หมายเหตุ — ไม่ใช่ปกติบังคับหมายเหตุ"""
    return await stocktake_service.set_condition(db, admin, round_id, item_id, body)


@router.post("/rounds/{round_id}/items/{item_id}/undo", response_model=StocktakeRoundResponse)
async def undo_scan(
    round_id: uuid.UUID, item_id: uuid.UUID,
    admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
) -> StocktakeRoundResponse:
    """ยกเลิกการสแกน (สแกนผิด) — ของที่ย้ายมาจากห้องอื่น ย้ายทะเบียนกลับห้อง+ตู้เดิม"""
    return await stocktake_service.undo_scan(db, admin, round_id, item_id)


@router.get("/summary-preview")
async def summary_preview(_admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict:
    """ใบรวมทุกห้อง (แบบรายงานทะเบียนคุมทรัพย์สินทั้งคณะ) — พรีวิว"""
    return preview_rows(summary_head(_today()), await stocktake_service.summary_rows(db))


@router.get("/summary.xlsx")
async def summary_xlsx(_admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> Response:
    return Response(
        content=xlsx_rows(summary_head(_today()), await stocktake_service.summary_rows(db)),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=stocktake-summary.xlsx"},
    )


@router.get("/summary.pdf")
async def summary_pdf(_admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> Response:
    rows = await stocktake_service.summary_rows(db)
    return Response(content=await asyncio.to_thread(generate_stocktake_summary_pdf, rows, _today()),
                    media_type="application/pdf")


def _today() -> datetime:
    return datetime.now(timezone.utc)


@router.get("/rounds/{round_id}/report-preview")
async def report_preview(
    round_id: uuid.UUID,
    _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
) -> dict:
    """พรีวิวใบตรวจแบบ Excel บนหน้าเว็บ (ไม่ต้องโหลดไฟล์) — แถวชุดเดียวกับไฟล์ .xlsx"""
    return stocktake_xlsx_preview(await stocktake_service.get_round(db, round_id))


@router.get("/rounds/{round_id}/report.xlsx")
async def report_xlsx(
    round_id: uuid.UUID,
    _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
) -> Response:
    """ใบตรวจแบบ Excel คอลัมน์เดียวกับไฟล์รายงานทะเบียนคุมทรัพย์สิน — คัดลอกไปวางต่อในทะเบียนหลักได้"""
    rnd = await stocktake_service.get_round(db, round_id)
    return Response(
        content=generate_stocktake_xlsx(rnd),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=stocktake.xlsx"},
    )


@router.get("/rounds/{round_id}/report.pdf")
async def report_pdf(
    round_id: uuid.UUID,
    _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
) -> Response:
    rnd = await stocktake_service.get_round(db, round_id)
    return Response(content=generate_stocktake_pdf(rnd), media_type="application/pdf")
