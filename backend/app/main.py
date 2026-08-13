import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.dependencies import get_db
from app.routers import auth, audit, borrow, bundle, dashboard, equipment, notification, settings as settings_router, users
from app.utils.email import email_configured
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
    start_scheduler()
    yield


app = FastAPI(
    title="ระบบยืม-คืนอุปกรณ์",
    description="Equipment Borrowing System — CE & DD CDTI",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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


@app.get("/health")
async def health(db: AsyncSession = Depends(get_db)) -> dict:
    """
    Health check ที่แตะ DB จริง

    คืน ok เฉย ๆ โดยไม่ query จะเขียวตลอดแม้ Postgres ล่ม
    ซึ่งทำให้ healthcheck ของ docker ไม่มีประโยชน์อะไรเลย
    """
    await db.execute(text("SELECT 1"))
    return {"status": "ok"}
