import asyncio
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.dependencies import get_db
from app.routers import (
    auth, audit, borrow, bundle, change_request, dashboard, eligible_students, equipment,
    notification, settings as settings_router, users,
)
from app.utils.email import email_configured
from app.services import import_service
from app.utils import perf
from app.utils.scheduler import start_scheduler


def _warn_unsafe_config() -> None:
    """
    เตือนตอนบูตถ้าเปิดโหมดที่ปลอดภัยเฉพาะตอน dev

    สองอย่างนี้เคยพลาดมาแล้วเพราะมันเงียบสนิท: ระบบทำงานได้ปกติทุกอย่าง
    แค่ไม่ตรวจอีเมลกับไม่ส่งอีเมล ซึ่งจะรู้ตัวอีกทีตอนผู้ใช้จริงบ่นว่าไม่ได้รับเมล
    """
    if settings.DEV_AUTO_VERIFY_EMAIL:
        print(
            "\n!!! DEV_AUTO_VERIFY_EMAIL=true — บัญชีใหม่ถูกยืนยันอัตโนมัติโดยไม่ตรวจอีเมล\n"
            "!!! ห้ามใช้ค่านี้ตอนเปิดใช้งานจริง: ใครก็สมัครด้วยอีเมลที่ไม่ใช่ของตัวเองแล้วเข้าใช้ได้ทันที\n"
        )
    if not email_configured:
        reason = "ENABLE_EMAIL=false" if not settings.ENABLE_EMAIL else "ยังไม่ได้ตั้ง MAIL_USERNAME"
        print(
            f"\n!!! การส่งอีเมลถูกปิดอยู่ ({reason}) — ระบบจะ print อีเมลลง log แทนการส่งจริง\n"
            "!!! ลิงก์ยืนยันอีเมล/รีเซ็ตรหัสผ่าน และการทวงของเกินกำหนด จะไปไม่ถึงผู้ใช้\n"
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    _warn_unsafe_config()
    await start_scheduler()
    import_service.sweep_import_dir()
    # ตัววัด event loop lag ของหน้าตรวจสอบระบบ — task เดียววนทุกวินาที ยกเลิกตอนปิดเซิร์ฟเวอร์
    lag_task = asyncio.create_task(perf.loop_lag_monitor())
    yield
    lag_task.cancel()


app = FastAPI(
    title="ระบบยืม-คืนอุปกรณ์",
    description="Equipment Borrowing System — CE & DD CDTI",
    version="1.0.0",
    lifespan=lifespan,
)

# จับเวลาทุก request (หน้าตรวจสอบระบบ) — เพิ่มก่อน CORS จึงอยู่ชั้นใน ครอบเฉพาะงานของแอปจริง
app.add_middleware(perf.PerfMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Process-Time"],
)



@app.exception_handler(DBAPIError)
async def _nul_byte_handler(request: Request, exc: DBAPIError) -> JSONResponse:
    """ตัวอักษร NUL (\x00) ในช่องค้นหา/ฟอร์ม — PostgreSQL เก็บใน text ไม่ได้ เดิมหลุดเป็น 500 (QA-05)
    ดักที่จุดเดียวแทนการไล่ตัดทุกฟิลด์ · error ฐานข้อมูลอื่นปล่อยผ่านเป็น 500 ตามเดิม (ต้องเห็นใน log)"""
    if "0x00" in str(exc.orig):
        return JSONResponse(status_code=400, content={"detail": "Input contains an invalid character."})
    # ข้อความยาวเกินขนาดคอลัมน์ (ชื่อ/รหัส/สถานที่ ฯลฯ 22 จุด — R2-03) ดักจุดเดียวเหตุผลเดียวกับ NUL ข้างบน
    # ชน unique ตอนสองคำขอเขียนพร้อมกัน (ดับเบิลคลิกสมัครสมาชิก ฯลฯ) — การเช็คซ้ำก่อน insert กันได้เฉพาะทีละคำขอ (R3-03)
    if "duplicate key value violates unique constraint" in str(exc.orig):
        return JSONResponse(status_code=409, content={"detail": "ข้อมูลนี้ถูกบันทึกไปแล้ว หรือซ้ำกับที่มีอยู่ กรุณาตรวจสอบแล้วลองใหม่"})
    if "value too long for type" in str(exc.orig):
        return JSONResponse(status_code=400, content={"detail": "ข้อความยาวเกินกว่าที่ช่องนี้รับได้ กรุณาย่อให้สั้นลง"})
    raise exc


os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(equipment.router)
app.include_router(borrow.router)
app.include_router(settings_router.router)
app.include_router(notification.router)
app.include_router(audit.router)
app.include_router(dashboard.router)
app.include_router(bundle.router)
app.include_router(change_request.router)
app.include_router(eligible_students.router)


@app.get("/health")
async def health(db: AsyncSession = Depends(get_db)) -> dict:
    """
    Health check ที่แตะ DB จริง

    คืน ok เฉย ๆ โดยไม่ query จะเขียวตลอดแม้ Postgres ล่ม
    ซึ่งทำให้ healthcheck ของ docker ไม่มีประโยชน์อะไรเลย
    """
    await db.execute(text("SELECT 1"))
    return {"status": "ok"}
