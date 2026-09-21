import os
import tempfile
import uuid

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, require_admin
from app.models.user import User
from app.schemas.student import PaginatedEligibleStudents, StudentImportResult
from app.services import student_import_service

router = APIRouter(prefix="/eligible-students", tags=["eligible-students"])


@router.get("", response_model=PaginatedEligibleStudents)
async def list_eligible_students(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    search: str | None = Query(None),
    cohort: str | None = Query(None, pattern=r"^\d{2}$", description="รุ่น = 2 หลักแรกของรหัส เช่น 66"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> PaginatedEligibleStudents:
    """รายชื่อนักศึกษาที่สาขารับรอง (ใช้ตรวจตอนสมัคร) พร้อมธงว่าใครสมัครใช้งานแล้ว"""
    return await student_import_service.list_students(db, page, page_size, search, cohort)


@router.post("/import", response_model=StudentImportResult)
async def import_eligible_students(
    file: UploadFile = File(...),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> StudentImportResult:
    """นำเข้าไฟล์รายชื่อจากสำนักทะเบียน (.xls/.xlsx/.csv/.pdf) — นำเข้าซ้ำได้ อัปเดตทับด้วยรหัสนักศึกษา"""
    contents = await file.read()
    if len(contents) > student_import_service.MAX_IMPORT_BYTES:
        from fastapi import HTTPException, status as http_status
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="ไฟล์ใหญ่เกิน 10MB")
    # ทุกไลบรารีที่ใช้ (xlrd/openpyxl/pypdf) อ่านจาก path — เขียนลงไฟล์ชั่วคราวแล้วลบทิ้งเสมอ
    # ไฟล์นี้มีชื่อ-รหัส นศ. ทั้งห้อง ห้ามค้างบนดิสก์ (เหตุผลเดียวกับ IMPORT_DIR ของทะเบียนอุปกรณ์)
    suffix = os.path.splitext(file.filename or "")[1].lower()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(contents)
        tmp_path = tmp.name
    try:
        return await student_import_service.import_students(db, admin, tmp_path, file.filename or "")
    finally:
        os.unlink(tmp_path)


@router.delete("/{row_id}", status_code=204)
async def delete_eligible_student(
    row_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """ถอนรายชื่อออกจาก whitelist — ไม่กระทบบัญชีที่สมัครไปแล้ว"""
    await student_import_service.delete_student(db, admin, row_id)
    return Response(status_code=204)
