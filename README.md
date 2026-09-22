# ระบบยืม-คืนอุปกรณ์ (Equipment Borrowing System)

ระบบเว็บแอปสำหรับจัดการการยืม-คืนครุภัณฑ์ วัสดุใช้ซ้ำ และวัสดุสิ้นเปลือง
สำหรับนักศึกษาและบุคลากรสาขาวิศวกรรมคอมพิวเตอร์และสาขาออกแบบดิจิทัล
สถาบันเทคโนโลยีจิตรลดา (CDTI)

> **คู่มือนี้คือคู่มือติดตั้งและตั้งค่าหลักของโปรเจกต์** (อัปเดตให้ตรงกับเวอร์ชัน `1da1c22` — 21 ก.ย. 2569)
> การเปลี่ยนแปลงของแต่ละเวอร์ชันดูที่ [`PATCH_NOTES.md`](PATCH_NOTES.md)

**สารบัญ**
1. [ภาพรวมระบบ](#1-ภาพรวมระบบ)
2. [สิ่งที่ต้องมีในเครื่อง](#2-สิ่งที่ต้องมีในเครื่อง)
3. [ติดตั้งสำหรับพัฒนา (Development)](#3-ติดตั้งสำหรับพัฒนา-development)
4. [Environment Variables](#4-environment-variables)
5. [ติดตั้งบนเซิร์ฟเวอร์จริง (Production)](#5-ติดตั้งบนเซิร์ฟเวอร์จริง-production)
6. [อัปเดตเวอร์ชันบนเซิร์ฟเวอร์](#6-อัปเดตเวอร์ชันบนเซิร์ฟเวอร์)
7. [การตั้งค่าในระบบ (หน้า "การตั้งค่าระบบ")](#7-การตั้งค่าในระบบ-หน้า-การตั้งค่าระบบ)
8. [สำรองและกู้คืนข้อมูล](#8-สำรองและกู้คืนข้อมูล)
9. [รันเทส](#9-รันเทส)
10. [แก้ปัญหาที่พบบ่อย](#10-แก้ปัญหาที่พบบ่อย)
11. [เอกสารอื่นที่เกี่ยวข้อง](#11-เอกสารอื่นที่เกี่ยวข้อง)

---

## 1. ภาพรวมระบบ

### Tech Stack

| ส่วน | เทคโนโลยี |
|---|---|
| Backend | Python 3.12 + FastAPI |
| ORM / Migration | SQLAlchemy 2.0 (async) + Alembic |
| Database | PostgreSQL 16 |
| Auth | JWT (access + refresh token) + ยืนยันอีเมล |
| Email | FastAPI-Mail (ปิด/เปิดได้ด้วย `ENABLE_EMAIL`) |
| PDF / QR | ReportLab (ฟอนต์ไทยในตัว) · qrcode |
| นำเข้าทะเบียนจากรูป/PDF | Tesseract OCR (ไม่บังคับ) |
| Scheduler | APScheduler (รันใน process เดียวกับ backend) |
| Frontend | React 18 + Vite + TailwindCSS + Axios |
| Deploy | Docker Compose (db + backend + nginx HTTPS) |

### ระดับสิทธิ์ผู้ใช้

| ยศ | ทำอะไรได้ (โดยย่อ) |
|---|---|
| **นักศึกษา** (`student`) | ยืม · ยกเลิก · ขอต่อเวลา · นัดคืน · ดาวน์โหลด/อัปโหลดใบยืม |
| **ผู้ดูแลคลัง** (`admin`) | อนุมัติ · รับคืน · จัดการอุปกรณ์/ผู้ใช้ · ค่าปรับ (แก้ยอด/รับชำระ) · settings งานประจำวัน |
| **ผู้ดูแลระบบสูงสุด** (`superadmin`) | ทุกอย่าง + แก้ทะเบียน/การเงิน · ยกเว้นค่าปรับ · ลบบัญชี/เปลี่ยนสิทธิ์ · settings ค่าปรับ/ค่าเสื่อม |

ตารางสิทธิ์ละเอียดอยู่ใน `CLAUDE.md` หัวข้อ 6

### โครงสร้างโปรเจกต์

```
├── backend/
│   ├── app/
│   │   ├── core/          # config (.env), database, security (JWT)
│   │   ├── models/        # SQLAlchemy ORM (13 ตาราง)
│   │   ├── schemas/       # Pydantic request/response
│   │   ├── routers/       # FastAPI routers แยกตาม domain
│   │   ├── services/      # business logic ทั้งหมด
│   │   ├── utils/         # email, pdf (+fonts), qrcode, scheduler, วันที่/ชั้นปี
│   │   ├── dependencies.py
│   │   └── main.py
│   ├── alembic/versions/  # migration 0001 → 0041
│   ├── scripts/           # create_admin.py · backup_db.sh · restore_db.sh · สคริปต์นำเข้าข้อมูล
│   ├── tests/             # pytest
│   ├── .env.example       # ตัวอย่าง .env สำหรับ dev
│   └── Dockerfile
├── frontend/
│   ├── src/               # pages/ (student, admin) · components/ · api/ · utils/
│   ├── nginx.conf         # ใช้ใน production (HTTPS + proxy /api)
│   ├── .env.example
│   └── Dockerfile
├── docker-compose.yml       # dev (ใช้แค่ service db — ดูหัวข้อ 3)
├── docker-compose.prod.yml  # production
├── .env.prod.example        # ตัวอย่าง .env สำหรับ production
└── gen-self-signed-cert.sh  # ออก cert HTTPS ให้ IP ของเครื่อง
```

---

## 2. สิ่งที่ต้องมีในเครื่อง

| โปรแกรม | ใช้ทำอะไร | หมายเหตุ |
|---|---|---|
| Python 3.12+ | รัน backend | |
| Node.js 20+ | รัน/บิลด์ frontend | |
| PostgreSQL 16+ | ฐานข้อมูล | ติดตั้งเอง หรือใช้ Docker (`docker compose up -d db`) |
| Docker + Docker Compose | รัน DB ตอน dev · deploy จริง | บังคับสำหรับ production |
| `tesseract-ocr` + `tesseract-ocr-tha` + `poppler-utils` | นำเข้าทะเบียนจากรูป/PDF (โหมดทดลอง) | ไม่บังคับตอน dev · image production ติดตั้งให้แล้ว |

---

## 3. ติดตั้งสำหรับพัฒนา (Development)

> ⚠️ **อย่าใช้ `docker compose up --build` ทั้งไฟล์** — service `frontend` ใน `docker-compose.yml` ใช้ nginx ตัวเดียวกับ
> production ซึ่งบังคับ HTTPS และหาไฟล์ cert ไม่เจอ ตอน dev ให้ใช้ Docker แค่ฐานข้อมูล แล้วรัน backend/frontend เอง

### 3.1 ฐานข้อมูล

```bash
docker compose up -d db          # PostgreSQL 16 ที่ localhost:5432 (user/password/equipment_borrow)
```

หรือใช้ PostgreSQL ที่ติดตั้งในเครื่องก็ได้ แค่แก้ `DATABASE_URL` ให้ตรง

### 3.2 Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env              # แก้ค่าตามหัวข้อ 4 (อย่างน้อย DATABASE_URL, SECRET_KEY)
alembic upgrade head               # สร้างตารางทั้งหมด + ค่าเริ่มต้นของ settings

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- Swagger UI: `http://localhost:8000/docs`
- เช็คว่าระบบ + DB พร้อม: `http://localhost:8000/health` → `{"status":"ok"}`

### 3.3 Frontend

```bash
cd frontend
npm ci
cp .env.example .env              # VITE_API_URL=/api (ผ่าน proxy ของ vite ไป localhost:8000)
npm run dev                        # http://localhost:5173
```

vite ฟังทุก network interface อยู่แล้ว มือถือหรือเครื่องอื่นในวง LAN เข้าผ่าน `http://<IP-เครื่อง>:5173` ได้ทันที
(QR code ของอุปกรณ์จะใช้ IP ที่เข้ามาจริงให้เอง)

### 3.4 สร้างบัญชีผู้ดูแลคนแรก

สร้างผ่านหน้าเว็บไม่ได้ ต้องใช้สคริปต์ (รันใน `backend/` ที่ activate venv แล้ว):

```bash
python scripts/create_admin.py --superadmin boss@cdti.ac.th 'ชื่อ นามสกุล'   # ผู้ดูแลระบบสูงสุด
python scripts/create_admin.py admin@cdti.ac.th 'ชื่อ นามสกุล'               # ผู้ดูแลคลัง
python scripts/create_admin.py                                              # ถามทีละข้อ
```

ถ้าอีเมลนั้นสมัครไว้แล้ว สคริปต์จะเลื่อนสิทธิ์ให้แทนการสร้างใหม่ · SuperAdmin คนแรก**ต้อง**สร้างด้วยสคริปต์
คนต่อไปตั้งผ่านหน้า "จัดการผู้ใช้" ได้

> ตอน dev ถ้ายังไม่มี SMTP ให้ตั้ง `DEV_AUTO_VERIFY_EMAIL=true` ใน `backend/.env` บัญชีที่สมัครใหม่จะใช้ได้ทันที
> (ลิงก์ยืนยันอีเมล/รีเซ็ตรหัสผ่านจะพิมพ์ออกมาใน log ของ backend แทนการส่งจริง)

---

## 4. Environment Variables

- **dev:** `backend/.env` (คัดลอกจาก `backend/.env.example`)
- **production:** `.env` ที่ root ของโปรเจกต์ (คัดลอกจาก `.env.prod.example`) — prod **ไม่อ่าน** `backend/.env`

| ตัวแปร | ค่าเริ่มต้น | ความหมาย / ข้อควรระวัง |
|---|---|---|
| `DATABASE_URL` | — (บังคับ) | `postgresql+asyncpg://user:pass@host:5432/db` · prod ไม่ต้องตั้ง compose ประกอบให้จาก `POSTGRES_*` |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | — | **prod เท่านั้น** ใช้สร้างฐานข้อมูลใน container `db` |
| `SECRET_KEY` | — (บังคับ) | สุ่มด้วย `openssl rand -hex 32` · ไม่ตั้ง = แอปไม่ยอมบูต · เปลี่ยน = ทุกคนหลุดล็อกอิน |
| `ALGORITHM` | `HS256` | |
| `ACCESS_TOKEN_EXPIRE_MINUTES` / `REFRESH_TOKEN_EXPIRE_DAYS` | `30` / `7` | อายุ token |
| `ENABLE_EMAIL` | `false` | `true` + ค่า `MAIL_*` จริง = ส่งอีเมลจริง · `false` = พิมพ์อีเมลลง log แทน (มีเตือนตอนบูต) |
| `MAIL_USERNAME` / `MAIL_PASSWORD` / `MAIL_FROM` | ว่าง | Gmail ต้องใช้ **App Password** 16 ตัว ไม่ใช่รหัส Gmail ปกติ |
| `MAIL_SERVER` / `MAIL_PORT` / `MAIL_STARTTLS` / `MAIL_SSL_TLS` | `smtp.gmail.com` / `587` / `true` / `false` | |
| `FRONTEND_URL` | `http://localhost:5173` | URL ที่ผู้ใช้พิมพ์ในเบราว์เซอร์ — ใช้ประกอบ**ลิงก์ในอีเมล**และ CORS · **ต้องแก้ทุกครั้งที่ IP เครื่องเปลี่ยน** |
| `APP_BASE_URL` | `http://localhost:8000` | prod ตั้งเหมือน `FRONTEND_URL` (backend อยู่หลัง nginx ที่ `/api`) |
| `UPLOAD_DIR` | `./uploads` | รูปอุปกรณ์/รูปความเสียหาย (เสิร์ฟสาธารณะที่ `/uploads`) |
| `PRIVATE_UPLOAD_DIR` | `./private_uploads` | ใบยืมที่เซ็นแล้ว (มีข้อมูลส่วนบุคคล) — **ห้ามชี้ไปในโฟลเดอร์ `UPLOAD_DIR`** |
| `IMPORT_DIR` | `./import_tmp` | ไฟล์ทะเบียนที่อัปโหลดมานำเข้า (ไฟล์ชั่วคราว ไม่เสิร์ฟสาธารณะ) |
| `ALLOWED_EMAIL_DOMAINS` | `cdti.ac.th,student.cdti.ac.th` | โดเมนอีเมลที่สมัครได้ (คั่นด้วยจุลภาค) |
| `DEV_AUTO_VERIFY_EMAIL` | `false` | `true` = สมัครแล้วใช้ได้ทันทีไม่ต้องยืนยันอีเมล · **ห้ามเปิดใน production** |
| `PYTEST_ALLOW_DB` | `false` | อนุญาตให้ pytest รันกับ DB ที่ชื่อไม่ลงท้าย `_test` (ดูหัวข้อ 9) |
| `LINE_CHANNEL_ACCESS_TOKEN` | ว่าง | ยังไม่ใช้ (LINE OA เป็น stretch goal) |

**frontend (`frontend/.env`)** มีค่าเดียว: `VITE_API_URL=/api` — ค่านี้ถูกฝังตอน build · production ตั้งให้เองใน `docker-compose.prod.yml`

**เขตเวลา:** backend container ตั้ง `TZ=Asia/Bangkok` ไว้ใน `backend/Dockerfile` แล้ว ไม่ต้องตั้งใน `.env`
(ถ้ารัน backend นอก Docker เครื่องต้องตั้งเวลาเป็นไทย ไม่งั้นงานทวงของเกินกำหนดจะคลาดไป 1 วัน)

> ค่าที่เกี่ยวกับการยืม-คืน (โควต้า ค่าปรับ เวลาแจ้งเตือน ฯลฯ) **ไม่ได้อยู่ใน `.env`** — ตั้งจากหน้าเว็บ ดูหัวข้อ 7

---

## 5. ติดตั้งบนเซิร์ฟเวอร์จริง (Production)

สถาปัตยกรรม: ผู้ใช้ → **nginx** (container `frontend`, พอร์ต 80 → redirect ไป 443 HTTPS) → เสิร์ฟหน้าเว็บ + proxy `/api` ไป
**backend** (ไม่เปิดพอร์ตออกนอก) → **db** (ไม่เปิดพอร์ตออกนอก) · ข้อมูลอยู่ใน Docker volume 3 ตัว:
`postgres_data` (ฐานข้อมูล) · `uploads_data` (รูป) · `private_uploads_data` (ใบยืมที่เซ็นแล้ว)

### 5.1 ติดตั้งครั้งแรก

```bash
git clone https://github.com/WhiteBearV/Borrowing_Returning_Items.git
cd Borrowing_Returning_Items

cp .env.prod.example .env
nano .env        # แก้อย่างน้อย: POSTGRES_PASSWORD, SECRET_KEY, FRONTEND_URL, APP_BASE_URL (เป็น https://<IP-เครื่อง>)

./gen-self-signed-cert.sh <IP-เครื่อง>                       # ได้ certs/fullchain.pem + privkey.pem (อายุ 2 ปี)
docker compose -f docker-compose.prod.yml up --build -d       # migration รันเองก่อนเปิด backend ทุกครั้ง
```

ตรวจว่าขึ้นครบ:

```bash
docker compose -f docker-compose.prod.yml ps                  # ทุกตัวต้อง Up / healthy
docker compose -f docker-compose.prod.yml logs --tail=50 backend   # ต้องเห็น alembic ขึ้นถึง 0041 (head)
curl -sk https://localhost/api/health                         # {"status":"ok"}
```

เข้าใช้งานที่ `https://<IP-เครื่อง>` — ครั้งแรกเบราว์เซอร์จะเตือนว่า "ไม่ปลอดภัย" เพราะเป็น cert ที่ออกเอง
(เข้ารหัสจริง แค่ไม่มี CA รับรอง) กด "ขั้นสูง" → "ไปต่อ" ได้ตามปกติ

### 5.2 หลังติดตั้ง — ต้องทำก่อนเปิดให้ผู้ใช้

1. **สร้าง SuperAdmin คนแรก**
   `docker compose -f docker-compose.prod.yml exec backend python scripts/create_admin.py --superadmin <อีเมล> '<ชื่อ นามสกุล>'`
2. **นำเข้ารายชื่อนักศึกษาที่รับรอง** (หน้า "รายชื่อนักศึกษาที่รับรอง" → นำเข้าไฟล์ .xls/.xlsx/.csv/.pdf จากสำนักทะเบียน ทีละอาจารย์ที่ปรึกษา)
   ไม่งั้นผู้สมัครทุกคนจะไปรอในคิวอนุมัติที่หน้า "จัดการผู้ใช้"
3. **ตรวจหน้า "การตั้งค่าระบบ"** โดยเฉพาะอัตราค่าปรับ เวลาส่งแจ้งเตือน และสถานที่/เวลานัดรับเริ่มต้น (ดูหัวข้อ 7)
4. **เพิ่มอุปกรณ์ / นำเข้าไฟล์ทะเบียน** แล้วตั้งค่าชุดอุปกรณ์ที่หน้า "ชุดอุปกรณ์" (DB ใหม่ไม่มีข้อมูลติดมาจากเครื่อง dev)
5. **ตั้ง backup อัตโนมัติ** (หัวข้อ 8) และแนะนำให้ตั้งนาฬิกาเครื่องเป็นเวลาไทย: `timedatectl set-timezone Asia/Bangkok`
   (ไม่งั้น cron "ตี 2" จะรันจริงตอน 09:00 น.)
6. **อีเมลจริง:** ตั้ง `ENABLE_EMAIL=true` + `MAIL_*` และ `DEV_AUTO_VERIFY_EMAIL=false` แล้ว `up -d` ใหม่

### 5.3 เมื่อ IP ของเครื่องเปลี่ยน (เช่น ย้าย VM)

```bash
./gen-self-signed-cert.sh <IP-ใหม่>
sed -i 's#FRONTEND_URL=.*#FRONTEND_URL=https://<IP-ใหม่>#; s#APP_BASE_URL=.*#APP_BASE_URL=https://<IP-ใหม่>#' .env
docker compose -f docker-compose.prod.yml up -d
```

ไม่แก้ `.env` = ลิงก์ยืนยันอีเมล/รีเซ็ตรหัสผ่านจะชี้ไป IP เก่าเงียบ ๆ · ไม่ออก cert ใหม่ = เบราว์เซอร์เตือน cert ไม่ตรง IP

### 5.4 container ไม่ขึ้นเองหลังรีบูตเครื่อง

ทุก service ตั้ง `restart: unless-stopped` — ขึ้นเองหลังรีบูต**ยกเว้น**ถูกสั่งหยุดไว้ก่อน (`docker compose stop`)
กรณีนั้นสั่ง `docker compose -f docker-compose.prod.yml up -d` ใหม่ได้เลย ข้อมูลไม่หาย (อยู่ใน volume)

---

## 6. อัปเดตเวอร์ชันบนเซิร์ฟเวอร์

การอัปเดตอาจมี migration ที่แก้โครงสร้างฐานข้อมูล **สำรองข้อมูลก่อนทุกครั้ง** (ระบบต้องเปิดอยู่ เพราะ backup ทำผ่าน container)

```bash
cd /root/TermPJ/Borrowing_Returning_Items

# 1) สำรอง — แยกโฟลเดอร์จาก backup รายวัน จะได้ไม่ถูกลบอัตโนมัติ
B=/root/backups/pre-update-$(date +%Y%m%d-%H%M)
BACKUP_DIR=$B bash backend/scripts/backup_db.sh
cp .env $B/env.backup && cp -r certs $B/ && git rev-parse HEAD > $B/commit.txt

# 2) ตรวจว่าไฟล์สำรองใช้ได้จริง
ls -lh $B                                                                          # ไม่มีไฟล์ขนาด 0
docker compose -f docker-compose.prod.yml exec -T db pg_restore -l < $B/db-*.dump | grep -c "TABLE DATA"
tar tzf $B/uploads-*.tar.gz | wc -l

# 3) อัปเดต
git pull
docker compose -f docker-compose.prod.yml up --build -d
docker compose -f docker-compose.prod.yml logs --tail=50 backend                  # alembic ถึง head
curl -sk https://localhost/api/health
```

แนะนำให้คัดลอกโฟลเดอร์สำรองออกมาเก็บนอกเซิร์ฟเวอร์ด้วย (รันบนเครื่องตัวเอง):
`scp -r root@<IP>:/root/backups/<ชื่อโฟลเดอร์> ~/eqb-backups/` — ไฟล์มีรหัสผ่านและข้อมูลส่วนบุคคล ห้ามแชร์สาธารณะ

**ถ้าอัปเดตแล้วพัง — ย้อนกลับ** (ย้อนโค้ด*ก่อน*แล้วค่อยกู้ DB ถ้าสลับลำดับ โค้ดใหม่จะรัน migration ทับอีกรอบ):

```bash
git checkout $(cat $B/commit.txt)
docker compose -f docker-compose.prod.yml up --build -d
bash backend/scripts/restore_db.sh $B/db-*.dump          # จะให้พิมพ์ yes ยืนยัน
```

ดูว่าแต่ละเวอร์ชันเปลี่ยนอะไรและต้องทำอะไรเพิ่มหลังอัปเดตที่ [`PATCH_NOTES.md`](PATCH_NOTES.md)

---

## 7. การตั้งค่าในระบบ (หน้า "การตั้งค่าระบบ")

ค่าเหล่านี้เก็บในตาราง `settings` แก้จากหน้าเว็บได้ทันทีไม่ต้อง deploy ใหม่ · ทุกการแก้ลงประวัติ (Audit Log)
ค่าที่แก้มีผลกับการทำงาน**ครั้งถัดไป** ยอดค่าปรับ/มูลค่าที่บันทึกไปแล้วไม่ขยับตาม

| ค่า (key) | ค่าเริ่มต้น | ความหมาย | ใครแก้ได้ |
|---|---|---|---|
| `max_items_per_request` | 5 | จำนวนรายการสูงสุดในคำขอหนึ่งใบ | ผู้ดูแลคลัง |
| `max_active_requests_per_student` | 2 | คำขอที่ยังไม่คืนพร้อมกันสูงสุดต่อนักศึกษา | ผู้ดูแลคลัง |
| `max_renew_count` | 1 | ต่อเวลาได้กี่ครั้งต่อรายการ | ผู้ดูแลคลัง |
| `max_renew_days` | 7 | ขอเลื่อนวันคืนได้ไกลสุดกี่วัน (นับจากวันนี้) | ผู้ดูแลคลัง |
| `due_soon_notify_days_before` | 2 | แจ้งเตือนล่วงหน้ากี่วันก่อนครบกำหนด | ผู้ดูแลคลัง |
| `notify_time` | 08:00 | เวลาที่ระบบส่งแจ้งเตือน/อีเมลอัตโนมัติทุกวัน (HH:MM เวลาไทย) มีผลทันที | **SuperAdmin** |
| `low_stock_threshold_default` | 5 | เกณฑ์สต็อกต่ำ (ใช้เมื่ออุปกรณ์ไม่ได้ตั้งเอง) | ผู้ดูแลคลัง |
| `default_pickup_location` | ห้องพัสดุ คณะเทคโนโลยีดิจิทัล | สถานที่นัดรับของเริ่มต้นในหน้าอนุมัติ | ผู้ดูแลคลัง |
| `default_pickup_time` | 13:00 | เวลานัดรับของเริ่มต้น | ผู้ดูแลคลัง |
| `academic_year_start` | 06-01 | วันเริ่มปีการศึกษา (MM-DD) ใช้เลื่อนชั้นปีอัตโนมัติ | ผู้ดูแลคลัง |
| `quality_repair_default_drop` | 2 | ค่าคุณภาพที่เสนอให้หักเมื่อซ่อม (%) | ผู้ดูแลคลัง |
| `quality_low_threshold` | 10 | คุณภาพต่ำกว่านี้ขึ้นป้าย "ควรตรวจสภาพ" (%) | ผู้ดูแลคลัง |
| `quality_age_weight` | 50 | น้ำหนักของอายุเทียบกับการใช้งานในสูตรคุณภาพ (0–100) | **SuperAdmin** |
| `quality_life_years_default` | 4 | อายุการใช้งานกลางสำหรับคิดคุณภาพ (ปี, จำนวนเต็ม) | **SuperAdmin** |
| `fine_per_day_per_item` | 10 | ค่าปรับคืนช้า (บาท/วัน/รายการ) | **SuperAdmin** |
| `fine_grace_days` | 0 | ผ่อนผันกี่วันก่อนเริ่มคิดค่าปรับ | **SuperAdmin** |
| `fine_max_per_item` | 0 | เพดานค่าปรับต่อรายการ (0 = ไม่จำกัด) | **SuperAdmin** |
| `depreciation_years_default` | 5 | อายุการใช้งานเริ่มต้นสำหรับค่าเสื่อม (ปี) | **SuperAdmin** |
| `depreciation_salvage_value` | 1 | มูลค่าซากหลังหมดอายุ (บาท) ตามระเบียบพัสดุ | **SuperAdmin** |
| `pdf_value_source` | acquisition | มูลค่าที่พิมพ์ในใบยืม/ใบคืน (ราคาที่ซื้อ / มูลค่าตามบัญชี) | **SuperAdmin** |

ผู้ดูแลคลังที่ต้องการเปลี่ยนค่าของ SuperAdmin ให้ยื่น "คำขอแก้ไขข้อมูล" พร้อมเหตุผล

---

## 8. สำรองและกู้คืนข้อมูล

ต้องสำรอง **ฐานข้อมูลและไฟล์รูปคู่กันเสมอ** — ฐานข้อมูลเก็บแค่ path ของรูป ถ้ากู้แค่ DB รูปจะเสียหมด

### สำรอง

```bash
bash backend/scripts/backup_db.sh
# ปรับได้ด้วย env: BACKUP_DIR (ค่าเริ่มต้น /var/backups/equipment-borrow) · RETAIN_DAYS (7)
```

สคริปต์ทำงานผ่าน `docker compose exec` (**container ต้องเปิดอยู่**) ได้ไฟล์ 2 ชุดต่อรอบ:
`db-<วันเวลา>.dump` (pg_dump custom format) และ `uploads-<วันเวลา>.tar.gz` แล้วลบไฟล์เก่าเกิน `RETAIN_DAYS` วัน

ตั้งอัตโนมัติทุกวันตี 2 (`crontab -e`):

```
0 2 * * * bash /root/TermPJ/Borrowing_Returning_Items/backend/scripts/backup_db.sh >> /var/log/eqb-backup.log 2>&1
```

> ⚠️ **ข้อจำกัดปัจจุบัน:** สคริปต์ยังไม่สำรอง volume `private_uploads_data` (ใบยืมที่เซ็นแล้ว) และ `.env` —
> สำรองเองตามขั้นตอนในหัวข้อ 6 · backup อยู่บนเครื่องเดียวกับระบบ ควรคัดลอกออกนอกเครื่องเป็นระยะ

### ตรวจไฟล์สำรอง (ไม่กู้ทับของจริง)

```bash
docker compose -f docker-compose.prod.yml exec -T db pg_restore -l < db-XXXX.dump | head   # ลิสต์ตารางในไฟล์
tar tzf uploads-XXXX.tar.gz | head                                                        # ต้องเห็นไฟล์รูปจริง
```

### กู้คืน

```bash
bash backend/scripts/restore_db.sh /var/backups/equipment-borrow/db-XXXX.dump
```

สคริปต์จะ: ถามยืนยัน → หยุด backend → สร้าง DB ใหม่ → กู้ข้อมูล → กู้รูปจาก `uploads-XXXX.tar.gz` ที่ชื่อคู่กัน (ถ้ามี)
→ เปิด backend → `alembic upgrade head` ให้ schema ทันโค้ดปัจจุบัน · **ควรซ้อมกู้ลงเครื่องทดสอบอย่างน้อยเทอมละครั้ง**

---

## 9. รันเทส

```bash
cd backend && source venv/bin/activate
pytest                                   # ทุกเทส
pytest tests/test_utilization_stats.py   # เฉพาะไฟล์
```

- เทสใช้ DB จาก `backend/.env` และ**ปฏิเสธที่จะรัน**ถ้าชื่อ DB ไม่ลงท้าย `_test` (กันเผลอล้างข้อมูลจริง)
  เครื่อง dev ที่ยืนยันแล้วว่าไม่ใช่ข้อมูลจริง ให้รัน `PYTEST_ALLOW_DB=1 pytest` · ทุกเทสลบข้อมูลที่ตัวเองสร้างทิ้งใน `finally`
- **ห้ามรัน pytest บนเซิร์ฟเวอร์ production**
- frontend: `cd frontend && npm test` และเช็คสูตรวันที่/เวลาไทย `node src/utils/formatDate.check.mjs`

---

## 10. แก้ปัญหาที่พบบ่อย

| อาการ | สาเหตุ / วิธีแก้ |
|---|---|
| หน้าเว็บเปิดไม่ได้หลังรีบูตเครื่อง | container ถูกสั่งหยุดไว้ → `docker compose -f docker-compose.prod.yml up -d` (หัวข้อ 5.4) |
| ลิงก์ในอีเมลยืนยัน/รีเซ็ตรหัสผ่านกดไม่ได้ | `FRONTEND_URL` ใน `.env` ไม่ตรง URL จริง (มักเป็น IP เก่า) → แก้แล้ว `up -d` |
| สมัครแล้วล็อกอินไม่ได้ "ยังไม่ยืนยันอีเมล" | ยังไม่ได้กดลิงก์ในอีเมล · ถ้า `ENABLE_EMAIL=false` ลิงก์อยู่ใน log ของ backend |
| สมัครแล้วล็อกอินไม่ได้ "รอเจ้าหน้าที่อนุมัติ" | รหัส/ชื่อไม่ตรงรายชื่อที่รับรอง → อนุมัติที่หน้า "จัดการผู้ใช้" หรือนำเข้ารายชื่อให้ครบ |
| ผู้ดูแลคลังกดแก้บางค่าแล้วเจอ 403 | ค่านั้นเป็นของ SuperAdmin (ราคา/วันที่ได้มา/ค่าปรับ/ค่าเสื่อม) → ยื่นคำขอแก้ไขข้อมูล |
| ไม่มีใครแก้ค่าปรับ/ราคาได้เลย | ยังไม่มี SuperAdmin → สร้างด้วย `create_admin.py --superadmin` (หัวข้อ 5.2) |
| เวลา/วันที่เพี้ยนไป 7 ชม. หรือ 1 วัน | backend ไม่ได้รันด้วยเวลาไทย → ใช้ image ล่าสุด (`TZ=Asia/Bangkok`) หรือตั้งเวลาเครื่องเป็นไทย |
| นำเข้าทะเบียนจากรูป/PDF ขึ้น "ยังไม่ได้ติดตั้ง OCR" | ติดตั้ง `tesseract-ocr tesseract-ocr-tha poppler-utils` (image production มีให้แล้ว) |
| backup ได้ไฟล์ขนาด 0 ไบต์ | container `db` ไม่ได้รันตอน backup → เปิดระบบก่อน แล้วลบไฟล์ 0 ไบต์ทิ้ง |
| dev: `docker compose up --build` แล้ว frontend ขึ้นไม่ได้ | ใช้ Docker แค่ `db` ตอน dev (หัวข้อ 3) |

---

## 11. เอกสารอื่นที่เกี่ยวข้อง

| เอกสาร | เนื้อหา |
|---|---|
| [`PATCH_NOTES.md`](PATCH_NOTES.md) | การเปลี่ยนแปลงของแต่ละเวอร์ชัน + สิ่งที่ต้องทำหลังอัปเดต |
| `CLAUDE.md` | บริบทโปรเจกต์ครบ: conventions · business rules · ตารางสิทธิ์ |
| [`docs/02-system-design.md`](docs/02-system-design.md) | DB schema · API endpoints · state transitions |
| [`docs/naming-convention.md`](docs/naming-convention.md) | มาตรฐานการตั้งชื่ออุปกรณ์ (ชื่อ ≠ รุ่น ≠ SN ≠ รหัสทะเบียน) |
| `คู่มือการใช้งาน-แอดมิน` / `คู่มือการใช้งาน-นักศึกษา` | วิธีใช้งานหน้าเว็บสำหรับผู้ใช้ |
| [`HANDOFF.md`](HANDOFF.md) | สรุปสำหรับนักพัฒนาที่มารับช่วงต่อ |
| `Swagger` | `http://localhost:8000/docs` (dev) — รายการ API ทั้งหมดพร้อมทดลองยิง |

### API modules

| Module | Base path |
|---|---|
| Auth | `/auth` |
| Users | `/users` |
| Equipment · หมวดหมู่ · ชิ้นส่วน | `/equipment` · `/equipment-categories` · `/equipment/{id}/parts` |
| ชุดอุปกรณ์ | `/bundles` |
| คำขอยืม (อนุมัติ/คืน/ต่อเวลา/ค่าปรับ/ใบยืมที่เซ็น) | `/borrow-requests` |
| รายชื่อนักศึกษาที่รับรอง | `/eligible-students` |
| คำขอแก้ไขข้อมูล · ตรวจสอบระบบ | `/change-requests` · `/change-requests/system-check` |
| แจ้งเตือน | `/notifications` |
| Settings | `/settings` |
| Audit Log | `/audit-logs` |
| Dashboard · สถิติความคุ้มค่า · ค่าปรับ | `/dashboard/summary` · `/dashboard/utilization` · `/dashboard/fines` |
| Health check | `/health` |

(production เรียกผ่าน prefix `/api` เช่น `https://<IP>/api/health`)
