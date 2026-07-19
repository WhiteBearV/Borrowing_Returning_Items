import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.routers import auth, audit, borrow, bundle, dashboard, equipment, notification, settings as settings_router, users
from app.utils.scheduler import start_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
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
async def health() -> dict:
    return {"status": "ok"}
