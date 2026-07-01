# HANDOFF — ระบบยืม-คืนอุปกรณ์

อัปเดต: 1 กรกฎาคม 2026 | เวอร์ชัน 1.2 | ผู้พัฒนา: วีรภัทร สาลีผล

---

## 1. สิ่งที่ต้องทำก่อนเริ่ม (ทำครั้งเดียว)

### ติดตั้ง dependencies เครื่องใหม่
- Python 3.12+
- Node.js 20+
- PostgreSQL 16+ (หรือใช้ Docker แทนได้เลย)
- Docker + Docker Compose (แนะนำ — รันครบในคำสั่งเดียว)

### Clone และ setup
```bash
git clone <repo-url>
cd TermPJ

# Backend
cd backend
cp .env.example .env        # แก้ค่าตาม section 2 ด้านล่าง
python -m venv venv
source venv/bin/activate    # Windows: venv\Scripts\activate
pip install -r requirements.txt
alembic upgrade head        # สร้างตารางทั้งหมด + seed settings เริ่มต้น

# Frontend
cd ../frontend
npm ci                      # ใช้ ci ไม่ใช่ install เพื่อให้ตรง package-lock.json
```

---

## 2. ค่า `.env` ที่ต้องแก้ก่อนรัน

ไฟล์อยู่ที่ `backend/.env` (copy จาก `.env.example`)

| ตัวแปร | ต้องแก้เป็น | หมายเหตุ |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://user:pass@localhost:5432/equipment_borrow` | แก้ user/pass ให้ตรง PostgreSQL |
| `SECRET_KEY` | รัน `python -c "import secrets; print(secrets.token_hex(32))"` | ห้ามใช้ค่า default |
| `MAIL_USERNAME` | Gmail ที่จะใช้ส่งอีเมล | เช่น `borrowsystem@gmail.com` |
| `MAIL_PASSWORD` | Gmail **App Password** 16 ตัว (ไม่ใช่รหัส Gmail ปกติ) | Google Account → Security → App passwords |
| `MAIL_FROM` | เหมือน `MAIL_USERNAME` | — |

ค่าอื่นๆ ไม่ต้องแก้ตอน dev บนเครื่องตัวเอง

### ต้องการข้ามการส่งอีเมลตอนทดสอบ?
เพิ่มบรรทัดนี้ใน `.env`:
```
DEV_AUTO_VERIFY_EMAIL=true
```
ระบบจะ verify email ให้อัตโนมัติโดยไม่ส่งอีเมลจริง

---

## 3. วิธีรัน

**Docker Compose (แนะนำ):**
```bash
docker compose up --build
```
- Frontend: http://localhost:5173
- Backend API: http://localhost:8000/docs

**รันแยก (สำหรับ debug):**
```bash
# Terminal 1 — Backend
cd backend && source venv/bin/activate
python -m app.main

# Terminal 2 — Frontend
cd frontend && npm run dev
```

---

## 4. สร้างบัญชี Admin ครั้งแรก

ระบบยังไม่มี admin registration flow — ต้องแทรกตรงใน DB:

```sql
-- รัน SQL นี้หลัง alembic upgrade head
INSERT INTO users (
  email, hashed_password, full_name, role,
  email_verified, is_active, username
) VALUES (
  'admin@cdti.ac.th',
  -- hash รหัสผ่าน 'admin1234' ด้วย bcrypt
  '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewdBpj4OzNE8UYMO',
  'ผู้ดูแลระบบ', 'admin', true, true, 'Admin'
);
```

หรือรันผ่าน Python เพื่อ hash รหัสผ่านที่ต้องการ:
```python
from passlib.context import CryptContext
pwd = CryptContext(schemes=["bcrypt"])
print(pwd.hash("รหัสผ่านที่ต้องการ"))
```

---

## 5. สถานะโค้ด (Version 1.2 — 1 ก.ค. 2026)

### เสร็จแล้ว ✅
| ส่วน | สถานะ |
|---|---|
| Auth: register, email verify, login, refresh, forgot/reset password | ✅ |
| Login แบบ Student ID / Username / Email (แท็บแยก role) | ✅ |
| Equipment: list, detail, CRUD (admin), QR code, image upload | ✅ |
| Borrow: สร้างคำขอ, อนุมัติ/ปฏิเสธ, คืน+ระบุสภาพ, ต่อเวลา | ✅ |
| PDF ใบยืม (รองรับ font ภาษาไทย NotoSansThai/Garuda) | ✅ |
| Admin: Dashboard, Users, Audit Log, Settings | ✅ |
| Scheduler: แจ้งเตือนใกล้ครบกำหนด + เกินกำหนด | ✅ |
| Frontend ทุกหน้า (student + admin) | ✅ |
| Alembic migrations ครบ 3 ไฟล์ | ✅ |
| Tests: integration, pdf, security | ✅ |

### ยังค้างอยู่ 🔴
| งาน | Priority | หมายเหตุ |
|---|---|---|
| ทดสอบ full stack จริง (login ทั้งสองโหมด, borrow flow) | สูง | ยังไม่ได้ทดสอบ end-to-end หลัง v1.2 |
| Endpoint `POST /users/admin` สร้างบัญชีแอดมินใหม่ | กลาง | ตอนนี้ต้องแทรก SQL ตรง |
| Image upload UI (หน้า Equipment Manage) | กลาง | Backend รองรับแล้ว แค่ UI ยังไม่ครบ |
| ยืนยัน `ALLOWED_EMAIL_DOMAINS` กับอาจารย์ | สูง | ก่อน deploy จริง |
| LINE OA notification | ต่ำ | Stretch goal, token ยังไม่ได้รับ |

---

## 6. โครงสร้างไฟล์ที่ต้องรู้

```
backend/app/
  services/borrow_service.py   ← business logic ทั้งหมดอยู่ที่นี่
  services/auth_service.py     ← login รองรับ student_id / username / email
  models/                      ← 9 tables, ดู schema ใน docs/02-system-design.md
  utils/pdf.py                 ← สร้างใบยืม (ใช้ font จาก utils/fonts/)
  utils/scheduler.py           ← APScheduler job แจ้งเตือนรายวัน

frontend/src/
  pages/student/               ← หน้าสำหรับนักศึกษา
  pages/admin/                 ← หน้าสำหรับแอดมิน
  api/                         ← axios calls แยก domain (ห้าม axios ตรงใน page)
  components/common/           ← ConfirmModal, Pagination (ใช้ซ้ำทุกหน้า)
  context/AuthContext.jsx      ← login state + role ของ user ปัจจุบัน
```

---

## 7. Rules ที่สำคัญ (ต้องรักษาไว้)

- **Admin คนเดียวที่กดคืนอุปกรณ์ได้** — `require_admin()` dependency ใน return endpoint
- **ของสิ้นเปลือง (consumable)** — `returned = true` ทันทีที่อนุมัติ ไม่ต้องคืน
- **ค่า config ระบบ** (จำนวนวันยืม, โควต้า) — อ่านจาก DB ตาราง `settings` เท่านั้น ห้าม hardcode
- **Business logic** — ต้องอยู่ใน `services/` ห้ามใส่ใน router
- **DB query** — ต้องผ่าน service เสมอ ห้าม query ตรงใน router

---

## 8. รัน Tests

```bash
cd backend
source venv/bin/activate
pytest                    # รันทุก test
pytest tests/test_pdf.py  # รันเฉพาะ PDF test
```

---

## 9. Reference

- `CLAUDE.md` — บริบทโปรเจคครบถ้วน (tech stack, conventions, business rules)
- `docs/02-system-design.md` — DB schema ทุกตาราง, API endpoints ทั้งหมด
- `Report/` — บันทึกความคืบหน้าแต่ละวัน
- Swagger: http://localhost:8000/docs (เปิดหลังรัน backend)
