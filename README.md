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

## สำรองและกู้คืนข้อมูล (Backup / Restore)

ระบบผูกกับชนิดข้อมูลเฉพาะของ PostgreSQL (JSONB, UUID) การกัน "ฐานข้อมูลเสีย"
จึงใช้วิธีสำรองข้อมูลสม่ำเสมอ ไม่ใช่การย้ายไปฐานข้อมูลยี่ห้ออื่น

**สำคัญ: ต้องสำรอง 2 อย่างคู่กันเสมอ**
รูปภาพ (รูปอุปกรณ์ / รูปความเสียหาย / รูปโปรไฟล์) เก็บเป็น**ไฟล์บนดิสก์**ใน `backend/uploads/`
ฐานข้อมูลเก็บแค่ path ถ้ากู้เฉพาะ DB path ในตารางจะชี้ไปไฟล์ที่ไม่มีอยู่

### สำรอง

```bash
bash backend/scripts/backup_db.sh
# ปรับได้ด้วย env: BACKUP_DIR (ค่าเริ่มต้น /var/backups/equipment-borrow), RETAIN_DAYS (7)
```

ตั้งอัตโนมัติทุกวันตี 2 ด้วย cron:

```bash
0 2 * * * bash /path/to/backend/scripts/backup_db.sh >> /var/log/eqb-backup.log 2>&1
```

สคริปต์จะได้ไฟล์ 2 ชุดต่อรอบ: `db-<วันเวลา>.dump` (pg_dump แบบ custom format) และ
`uploads-<วันเวลา>.tar.gz` พร้อมลบไฟล์เก่าเกิน `RETAIN_DAYS` วันให้อัตโนมัติ

### กู้คืน

```bash
# 1) สร้างฐานข้อมูลเปล่า (ต้องใช้สิทธิ์ที่สร้าง database ได้ เช่น postgres)
createdb -h localhost -U postgres equipment_borrow

# 2) กู้ข้อมูล
pg_restore -h localhost -U postgres -d equipment_borrow db-20260719-020000.dump

# 3) กู้รูปกลับเข้าที่เดิม
tar xzf uploads-20260719-020000.tar.gz -C backend/

# 4) ปรับ schema ให้ตรงโค้ดปัจจุบัน (เผื่อ backup เก่ากว่า migration ล่าสุด)
cd backend && alembic upgrade head
```

ตรวจไฟล์ backup ว่าใช้ได้จริงโดยไม่ต้องกู้ทับของจริง: `pg_restore -l db-....dump`
จะลิสต์ตารางทั้งหมดในไฟล์ออกมา — ควรทดลองกู้ลงฐานข้อมูลทดสอบอย่างน้อยเทอมละครั้ง

---

## API Endpoints หลัก

| Module | Base Path |
|---|---|
| Auth | `/auth` |
| Users | `/users` |
| Equipment | `/equipment` |
| Bundles (ชุดอุปกรณ์) | `/bundles` |
| Borrow Requests | `/borrow-requests` |
| Notifications | `/notifications` |
| Settings | `/settings` |
| Audit Logs | `/audit-logs` |
| Dashboard | `/dashboard` |
