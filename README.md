# ระบบยืม-คืนอุปกรณ์ (Equipment Borrowing System)

ระบบเว็บแอปสำหรับจัดการการยืม-คืนอุปกรณ์ครุภัณฑ์และวัสดุสิ้นเปลือง  
สำหรับนักศึกษาและอาจารย์ของสาขาวิศวกรรมคอมพิวเตอร์และสาขาออกแบบดิจิทัล  
สถาบันเทคโนโลยีดิจิทัลสวนจิตรลดา (CDTI)

---

## Tech Stack

| ส่วน | เทคโนโลยี |
|---|---|
| Backend | Python 3.12 + FastAPI |
| ORM / Migration | SQLAlchemy 2.0 (async) + Alembic |
| Database | PostgreSQL 16 |
| Auth | JWT (access + refresh token) + Email verification |
| Email | FastAPI-Mail |
| Frontend | React 18 + Vite + TailwindCSS |
| HTTP Client | Axios |
| Container | Docker + Docker Compose |
| Scheduler | APScheduler |

---

## โครงสร้างโปรเจค

```
├── backend/
│   ├── app/
│   │   ├── core/         # config, database, security (JWT)
│   │   ├── models/       # SQLAlchemy ORM (9 ตาราง)
│   │   ├── schemas/      # Pydantic request/response schemas
│   │   ├── routers/      # FastAPI routers แยกตาม domain
│   │   ├── services/     # Business logic
│   │   ├── utils/        # email, pdf, qrcode, scheduler
│   │   ├── dependencies.py
│   │   └── main.py
│   ├── alembic/          # Database migrations
│   ├── .env.example
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── api/          # Axios API calls แยก domain
│   │   ├── components/   # Reusable UI components
│   │   ├── context/      # AuthContext
│   │   ├── hooks/        # useBorrowCart
│   │   └── pages/        # student/ และ admin/
│   └── package.json
├── docker-compose.yml
└── docker-compose.prod.yml
```

---

## วิธีรัน (Development)

### 1. ตั้งค่า Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env            # แก้ค่าใน .env ก่อน
alembic upgrade head             # สร้างตาราง + seed settings
python -m app.main               # รันที่ port 8000
```

Swagger UI: `http://localhost:8000/docs`

### 2. ตั้งค่า Frontend

```bash
cd frontend
npm install
cp .env.example .env
npm run dev                     # รันที่ port 5173
```

### 3. รันด้วย Docker Compose

```bash
# Development
docker compose up --build

# Production
docker compose -f docker-compose.prod.yml up --build
```

---

## Environment Variables หลัก (`.env`)

| ตัวแปร | คำอธิบาย |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |
| `SECRET_KEY` | JWT secret key |
| `MAIL_USERNAME` / `MAIL_PASSWORD` | Gmail app password สำหรับส่งอีเมล |
| `FRONTEND_URL` | URL ของ frontend (สำหรับ CORS + email links) |
| `ALLOWED_EMAIL_DOMAINS` | Domain อีเมลที่อนุญาตลงทะเบียน เช่น `cdti.ac.th` |

ดูตัวอย่างทั้งหมดได้ที่ `backend/.env.example`

---

## ฟีเจอร์หลัก

- **นักศึกษา** — ดูรายการอุปกรณ์, ยื่นคำขอยืม, ติดตามสถานะ, ดาวน์โหลด PDF ใบยืม, ขอต่อเวลา
- **แอดมิน** — อนุมัติ/ปฏิเสธคำขอ, ยืนยันรับคืน, จัดการอุปกรณ์, ดู audit log, ปรับ settings
- **ระบบอัตโนมัติ** — แจ้งเตือนใกล้ครบกำหนด (due_soon) และเกินกำหนดคืน (overdue) ทุกวันเที่ยงคืน
- **QR Code** — สร้าง QR Code ประจำอุปกรณ์แต่ละชิ้น

---

## API Endpoints หลัก

| Module | Base Path |
|---|---|
| Auth | `/auth` |
| Users | `/users` |
| Equipment | `/equipment` |
| Borrow Requests | `/borrow-requests` |
| Notifications | `/notifications` |
| Settings | `/settings` |
| Audit Logs | `/audit-logs` |
| Dashboard | `/dashboard` |
