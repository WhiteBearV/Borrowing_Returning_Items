import os
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict

# เวลาใน DB เก็บเป็น UTC เสมอ — โซนนี้ใช้ตอนแสดงผล/ตัดช่วงวันในเอกสาร (ใช้ในคณะเดียว hardcode พอ)
TZ = ZoneInfo("Asia/Bangkok")

# ชี้ backend/.env แบบ absolute — สคริปต์ใน scripts/ รันจาก cwd ไหนก็เจอ .env เหมือนกัน
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.path.join(BACKEND_DIR, ".env"),
        env_file_encoding="utf-8",
        # ไม่งั้นคีย์ที่ไม่ใช่ของ backend ใน .env (POSTGRES_*, PYTEST_ALLOW_DB, ฯลฯ)
        # ทำให้แอปไม่ยอมบูตทั้งระบบ ทั้งที่ค่าที่จำเป็นครบอยู่แล้ว
        extra="ignore",
    )

    # Database
    DATABASE_URL: str

    # JWT
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Email
    ENABLE_EMAIL: bool = False  # ปิดการส่งอีเมลทั้งระบบไว้ก่อน ตั้ง true ตอนพร้อม SMTP จริง
    MAIL_USERNAME: str = ""
    MAIL_PASSWORD: str = ""
    MAIL_FROM: str = ""
    MAIL_PORT: int = 587
    MAIL_SERVER: str = "smtp.gmail.com"
    MAIL_STARTTLS: bool = True
    MAIL_SSL_TLS: bool = False

    # App
    APP_BASE_URL: str = "http://localhost:8000"
    FRONTEND_URL: str = "http://localhost:5173"
    UPLOAD_DIR: str = "./uploads"
    # ต้องอยู่นอก UPLOAD_DIR — main.py mount UPLOAD_DIR เป็น StaticFiles แบบไม่มี auth
    # ไฟล์ที่นี่คือทะเบียนครุภัณฑ์ทั้งคณะที่แอดมินอัปมา ห้ามให้โหลดได้จากภายนอก
    # ponytail: ไม่ต้อง mount volume — ไฟล์อยู่แค่ช่วง preview→commit รีสตาร์ตแล้วอัปใหม่ได้
    IMPORT_DIR: str = "./import_tmp"
    ALLOWED_EMAIL_DOMAINS: str = "cdti.ac.th,student.cdti.ac.th"

    # Dev
    DEV_AUTO_VERIFY_EMAIL: bool = False  # ต้องตั้งชัดเจน ห้าม True ใน production
    # ยอมให้ pytest รันกับ DB ที่ชื่อไม่ได้ลงท้าย _test (เทสต์ลบข้อมูลทิ้ง — ดู tests/conftest.py)
    # ตั้งไว้เฉพาะ backend/.env ของเครื่อง dev เท่านั้น prod ไม่มีไฟล์นี้ใน image อยู่แล้ว
    PYTEST_ALLOW_DB: bool = False

    # LINE OA
    LINE_CHANNEL_ACCESS_TOKEN: str = ""

    @property
    def allowed_email_domains_list(self) -> list[str]:
        return [d.strip() for d in self.ALLOWED_EMAIL_DOMAINS.split(",")]


settings = Settings()
