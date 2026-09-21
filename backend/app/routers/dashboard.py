import csv
import io
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import TZ
from app.dependencies import get_db, require_admin
from app.models.user import User
from app.schemas.dashboard import DashboardSummaryResponse, FineSummaryResponse, UtilizationResponse
from app.services import dashboard_service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummaryResponse)
async def get_summary(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> DashboardSummaryResponse:
    return await dashboard_service.get_summary(db)


@router.get("/utilization", response_model=UtilizationResponse)
async def get_utilization(
    item_type: str | None = Query(None, pattern="^(durable|material|consumable|all)$"),
    date_from: date | None = Query(None, description="ไม่ส่งทั้งคู่ = สะสมตั้งแต่เข้าระบบ"),
    date_to: date | None = Query(None),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> UtilizationResponse:
    """สถิติความคุ้มค่ารายหน่วย + สรุปรายเดือน (ประกอบการตัดสินใจจัดซื้อ ไม่ใช่ฐานคิดค่าปรับ)"""
    if (date_from is None) != (date_to is None) or (date_from and date_from > date_to):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="ระบุช่วงวันที่ให้ครบทั้งเริ่มต้นและสิ้นสุด และวันเริ่มต้องไม่หลังวันสิ้นสุด")
    return await dashboard_service.get_utilization(db, item_type, date_from, date_to)


@router.get("/fines", response_model=FineSummaryResponse)
async def get_fines(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> FineSummaryResponse:
    """ค่าปรับทุกรายการ + ยอดรวมแยกตามสถานะ — หน้าเว็บกรอง/เรียงเองฝั่ง client"""
    return await dashboard_service.get_fines(db)


_CSV_HEADER = ["เลขคำขอ", "ผู้ยืม", "รหัสประจำตัว", "อุปกรณ์", "รหัสอุปกรณ์", "กำหนดคืน",
               "คืนเมื่อ", "ล่าช้า (วัน)", "ค่าปรับล่าช้า", "ค่าเสียหาย", "รวม", "สถานะ",
               "ผู้ยกเว้น", "เหตุผลที่ยกเว้น"]
_CSV_STATUS = {"unpaid": "ค้างชำระ", "paid": "ชำระแล้ว", "waived": "ยกเว้น"}


@router.get("/fines/export")
async def export_fines(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """ไฟล์ CSV ของค่าปรับทั้งหมด — งานการเงินจริงต้องส่งไฟล์ให้คนอื่นตรวจ ไม่ใช่ดูบนจออย่างเดียว"""
    data = await dashboard_service.get_fines(db)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_CSV_HEADER)
    for r in data.rows:
        writer.writerow([
            r.request_code, r.student_name or "", r.student_identifier or "",
            r.equipment_name or "", r.equipment_code or "",
            r.due_date.isoformat() if r.due_date else "",
            r.returned_at.astimezone(TZ).strftime("%Y-%m-%d %H:%M") if r.returned_at else "",
            r.days_late, f"{r.late_amount:.2f}", f"{r.damage_amount:.2f}", f"{r.total:.2f}",
            _CSV_STATUS.get(r.status, r.status), r.waived_by_name or "", r.waived_reason or "",
        ])
    # BOM — Excel บนวินโดวส์อ่าน UTF-8 ที่ไม่มี BOM เป็นภาษาไทยไม่ออก (ขึ้นเป็นตัวขยะ)
    return Response(
        content="﻿" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="fines.csv"'},
    )
