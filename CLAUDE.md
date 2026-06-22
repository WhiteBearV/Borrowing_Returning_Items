# CLAUDE.md — ระบบยืม-คืนอุปกรณ์ (Equipment Borrowing System)

เอกสารนี้ให้บริบทที่ Claude Code ต้องรู้ก่อนเขียนโค้ดทุกครั้ง อ่านให้ครบทุกหัวข้อก่อนเริ่มงานใด ๆ

---

## 1. ภาพรวมโครงการ

ระบบเว็บแอปสำหรับจัดการการยืม-คืนอุปกรณ์ครุภัณฑ์และวัสดุสิ้นเปลือง  
สำหรับนักศึกษาและอาจารย์ของสาขาวิศวกรรมคอมพิวเตอร์และสาขาออกแบบดิจิทัล  
ใช้งานจริงบนเซิร์ฟเวอร์ของคณะ มีผู้ใช้งาน ~100–300 คน อุปกรณ์ในคลัง ≤100 รายการ

**เอกสารอ้างอิงที่ต้องอ่านร่วม:**
- `docs/01-proposal.md` — ที่มา ปัญหา วัตถุประสงค์ ขอบเขต
- `docs/02-system-design.md` — DB schema ทุกตาราง, รายการ API endpoint ทั้งหมด, enum, ค่าเริ่มต้น settings, state transitions

---

## 2. Tech Stack

| ส่วน | เทคโนโลยี | เวอร์ชัน |
|---|---|---|
| Backend language | Python | 3.12+ |
| Web framework | FastAPI | ล่าสุด |
| ORM | SQLAlchemy | 2.0+ (async) |
| Migration | Alembic | ล่าสุด |
| Database | PostgreSQL | 16+ |
| Auth | JWT (python-jose + passlib[bcrypt]) | — |
| Email | FastAPI-Mail | — |
| PDF | ReportLab | — |
| QR Code | qrcode[pil] | — |
| File upload | python-multipart + เก็บใน local /uploads | — |
| Frontend | React 18 + Vite | — |
| CSS | TailwindCSS | 3+ |
| HTTP client | axios | — |
| Routing | react-router-dom | v6 |
| Container | Docker + Docker Compose | — |
| Scheduler | APScheduler (รันใน process เดียวกับ FastAPI) | — |

---

## 3. โครงสร้างโฟลเดอร์ (Project Structure)

```
project-root/
├── backend/
│   ├── app/
│   │   ├── main.py                  # entry point — สร้าง FastAPI app, mount routers
│   │   ├── core/
│   │   │   ├── config.py            # อ่านค่าจาก .env ผ่าน pydantic-settings
│   │   │   ├── security.py          # สร้าง/ตรวจสอบ JWT, hash รหัสผ่าน
│   │   │   └── database.py          # สร้าง async engine, sessionmaker
│   │   ├── models/                  # SQLAlchemy ORM models (1 ไฟล์ = 1 ตาราง)
│   │   │   ├── user.py
│   │   │   ├── equipment.py
│   │   │   ├── equipment_category.py
│   │   │   ├── borrow_request.py
│   │   │   ├── borrow_item.py
│   │   │   ├── notification.py
│   │   │   ├── audit_log.py
│   │   │   ├── auth_token.py
│   │   │   └── setting.py
│   │   ├── schemas/                 # Pydantic schemas (request body / response)
│   │   │   ├── auth.py
│   │   │   ├── user.py
│   │   │   ├── equipment.py
│   │   │   ├── borrow.py
│   │   │   ├── notification.py
│   │   │   └── setting.py
│   │   ├── routers/                 # FastAPI routers แยกตาม domain
│   │   │   ├── auth.py
│   │   │   ├── users.py
│   │   │   ├── equipment.py
│   │   │   ├── borrow.py
│   │   │   ├── settings.py
│   │   │   ├── notification.py
│   │   │   ├── audit.py
│   │   │   └── dashboard.py
│   │   ├── services/                # Business logic (แยกออกจาก router เสมอ)
│   │   │   ├── auth_service.py
│   │   │   ├── equipment_service.py
│   │   │   ├── borrow_service.py    # ควบคุม workflow ยืม-อนุมัติ-คืน
│   │   │   └── notification_service.py
│   │   ├── utils/
│   │   │   ├── email.py             # ส่งอีเมลผ่าน FastAPI-Mail
│   │   │   ├── pdf.py               # สร้าง PDF ใบยืมด้วย ReportLab
│   │   │   ├── qrcode_gen.py        # สร้างรูป QR จาก equipment.code
│   │   │   └── scheduler.py         # APScheduler jobs (due_soon, overdue)
│   │   └── dependencies.py          # get_db(), get_current_user(), require_admin()
│   ├── alembic/                     # migration scripts
│   │   ├── env.py
│   │   └── versions/
│   ├── uploads/                     # รูปถ่ายความเสียหาย, รูปอุปกรณ์ (ไม่ commit ขึ้น git)
│   ├── .env.example
│   ├── requirements.txt
│   └── Dockerfile
│
├── frontend/
│   ├── src/
│   │   ├── main.jsx
│   │   ├── App.jsx                  # React Router setup
│   │   ├── pages/
│   │   │   ├── LoginPage.jsx
│   │   │   ├── RegisterPage.jsx
│   │   │   ├── VerifyEmailPage.jsx
│   │   │   ├── student/
│   │   │   │   ├── DashboardPage.jsx
│   │   │   │   ├── EquipmentListPage.jsx
│   │   │   │   ├── EquipmentDetailPage.jsx
│   │   │   │   ├── BorrowRequestPage.jsx   # ตะกร้ายืมอุปกรณ์
│   │   │   │   ├── MyBorrowsPage.jsx
│   │   │   │   └── ProfilePage.jsx
│   │   │   └── admin/
│   │   │       ├── DashboardPage.jsx
│   │   │       ├── EquipmentManagePage.jsx
│   │   │       ├── BorrowRequestsPage.jsx  # รายการรออนุมัติ
│   │   │       ├── AllBorrowsPage.jsx
│   │   │       ├── UsersPage.jsx
│   │   │       ├── AuditLogPage.jsx
│   │   │       └── SettingsPage.jsx
│   │   ├── components/              # UI ที่ใช้ซ้ำ
│   │   │   ├── common/              # Button, Modal, Badge, Pagination, Spinner
│   │   │   ├── equipment/           # EquipmentCard, EquipmentStatusBadge
│   │   │   ├── borrow/              # BorrowItemRow, ReturnModal, DamageForm
│   │   │   └── layout/              # Navbar, Sidebar, ProtectedRoute
│   │   ├── api/                     # axios calls แยกตาม domain
│   │   │   ├── axiosInstance.js     # base URL, interceptor ใส่ JWT header, refresh token
│   │   │   ├── authApi.js
│   │   │   ├── equipmentApi.js
│   │   │   ├── borrowApi.js
│   │   │   └── notificationApi.js
│   │   ├── context/
│   │   │   └── AuthContext.jsx      # เก็บ user state, login/logout
│   │   └── hooks/
│   │       ├── useAuth.js
│   │       └── useBorrowCart.js     # state ตะกร้าเลือกอุปกรณ์ก่อนยืน
│   ├── .env.example
│   ├── package.json
│   └── Dockerfile
│
├── docker-compose.yml
├── docker-compose.prod.yml
└── docs/
    ├── 01-proposal.md
    └── 02-system-design.md
```

---

## 4. ข้อตกลงการเขียนโค้ด (Coding Conventions)

### Python (Backend)
- ใช้ **Type hint ทุกฟังก์ชัน** — parameter และ return type เสมอ ไม่มีข้อยกเว้น
- ฟังก์ชันใน `services/` ต้องมี **docstring** อธิบายว่าทำอะไรและทำไม ไม่ใช่แค่ว่าทำยังไง
- comment บรรทัดที่ logic ซับซ้อนเป็นภาษาไทยได้ เพื่อให้เจ้าของโปรเจกต์อธิบายได้
- ชื่อตัวแปร/ฟังก์ชัน/คลาส: `snake_case` ตามมาตรฐาน Python
- **ห้าม** ใส่ business logic ใน router — router ทำหน้าที่แค่ validate input, เรียก service, คืน response
- **ห้าม** query ฐานข้อมูลโดยตรงใน router — ผ่าน service เสมอ
- Database session ต้องผ่าน `get_db()` dependency injection เสมอ ไม่สร้างเองใน function
- ใช้ `async/await` ทุกที่ที่เรียก DB (SQLAlchemy 2.0 async)
- Error ที่ควบคุมได้ให้ raise `HTTPException` พร้อม detail message ที่อ่านเข้าใจ (ภาษาอังกฤษ)

```python
# ตัวอย่าง router ที่ถูกต้อง
@router.post("/borrow-requests", response_model=BorrowRequestResponse, status_code=201)
async def create_borrow_request(
    body: BorrowRequestCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BorrowRequestResponse:
    """สร้างคำขอยืมอุปกรณ์ใหม่ ตรวจสอบโควต้าก่อนสร้าง"""
    return await borrow_service.create_request(db, current_user, body)
```

### React (Frontend)
- ใช้ **functional components + hooks** เสมอ ไม่ใช้ class component
- ชื่อ component: `PascalCase` / ชื่อ hook: `camelCase` ขึ้นต้นด้วย `use`
- แต่ละไฟล์ใน `pages/` และ `components/` มีแค่ 1 component หลัก
- เรียก API ผ่าน `api/` เสมอ ห้าม `axios.get(...)` ตรงใน component
- State ที่ใช้แค่ใน component เดียวใช้ `useState` / ข้าม component ใช้ `AuthContext` หรือ prop drilling ที่ชัดเจน ยังไม่ใช้ library state management เพิ่มเติม
- ใช้ TailwindCSS utility class ตรงใน JSX ไม่สร้างไฟล์ CSS แยก (ยกเว้นมีเหตุผลจำเป็น)

---

## 5. กฎเกณฑ์ทางธุรกิจที่สำคัญ (Business Rules)

กฎเหล่านี้ต้องบังคับใช้ใน `services/borrow_service.py` ทุกครั้ง ไม่ใช่แค่ฝั่ง frontend

**การยืมอุปกรณ์:**
- นักศึกษาสามารถเลือกอุปกรณ์ได้หลายรายการในคำขอเดียว สูงสุด `max_items_per_request` รายการ (ค่าเริ่มต้น 5)
- นักศึกษาจะมีคำขอที่ยังไม่คืนได้พร้อมกันสูงสุด `max_active_requests_per_student` คำขอ (ค่าเริ่มต้น 2) — เช็คก่อนสร้างคำขอใหม่ทุกครั้ง
- อุปกรณ์ที่ `quantity_available = 0` หรือ `status != available` (สำหรับครุภัณฑ์) ต้องยืมไม่ได้ — ตรวจสอบตอน validate request ก่อน insert
- ค่าต่าง ๆ เช่น `max_loan_days_durable`, `max_items_per_request` ต้องอ่านมาจากตาราง `settings` ไม่ hardcode ในโค้ด

**การอนุมัติ:**
- เมื่ออนุมัติ: ลด `equipment.quantity_available` ทันที, คำนวณ `due_date = approved_at + max_loan_days_durable`, ส่งแจ้งเตือนนักศึกษา
- ของสิ้นเปลือง (`item_type = consumable`): ตั้ง `borrow_item.returned = true` ทันทีที่อนุมัติ — เบิกแล้วไม่ต้องคืน, หักสต็อกออกเลย

**การคืนอุปกรณ์:**
- **นักศึกษาไม่สามารถกดคืนอุปกรณ์เองได้** — endpoint `return` ต้องใช้สิทธิ์ `admin` เท่านั้น บังคับใช้ผ่าน `require_admin()` dependency
- เมื่อคืน: แอดมินต้องระบุ `condition_on_return` (`ok`/`damaged`/`lost`) และ `damage_note` (ถ้า damaged/lost) ก่อน confirm ได้
- เมื่อคืนครบทุกรายการใน request: อัปเดต `borrow_request.status = completed` และ `returned_at` อัตโนมัติ
- เมื่อคืนแล้ว: เพิ่ม `equipment.quantity_available` กลับคืน (เฉพาะกรณี condition = ok)

**การต่อเวลา:**
- ต่อได้สูงสุด `max_renew_count` ครั้งต่อรายการ (ค่าเริ่มต้น 1 ครั้ง)
- เช็ค `borrow_item.renewed_count < max_renew_count` ก่อนอนุญาตต่อเวลาเสมอ

**Email verification:**
- `users.email_verified` ต้องเป็น `true` ก่อน login ได้ — ถ้ายังไม่ verify คืน HTTP 403 พร้อม message ชัดเจน

---

## 6. Role และ Permission

| การกระทำ | Student | Admin |
|---|---|---|
| ดูรายการอุปกรณ์ | ✅ | ✅ |
| ดูสถานะ/ผู้ครอบครองอุปกรณ์ | ✅ | ✅ |
| ยื่นคำขอยืม | ✅ | ✅ |
| ยกเลิกคำขอ (ของตัวเอง, pending) | ✅ | ✅ |
| ดูประวัติการยืมตัวเอง | ✅ | ✅ |
| ดาวน์โหลด PDF ใบยืม | ✅ (เฉพาะของตัวเอง) | ✅ |
| ขอต่อเวลา | ✅ (เฉพาะของตัวเอง) | ✅ |
| **กดยืนยันการคืนอุปกรณ์** | ❌ | ✅ |
| อนุมัติ/ปฏิเสธคำขอ | ❌ | ✅ |
| เพิ่ม/แก้ไข/ปลดระวางอุปกรณ์ | ❌ | ✅ |
| ดูรายการคำขอทั้งหมด | ❌ | ✅ |
| ส่งแจ้งเตือนแบบ manual | ❌ | ✅ |
| จัดการบัญชีผู้ใช้ | ❌ | ✅ |
| แก้ไข settings | ❌ | ✅ |
| ดู audit log | ❌ | ✅ |

**Dependency ที่ต้องใช้ใน `dependencies.py`:**
```python
async def get_current_user(...)   # ตรวจสอบ JWT, คืน User object
async def require_admin(...)      # get_current_user + เช็ค role == "admin"
```

---

## 7. Environment Variables (`.env.example`)

```env
# Database
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/equipment_borrow

# JWT
SECRET_KEY=your-secret-key-here-change-in-production
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7

# Email (FastAPI-Mail)
MAIL_USERNAME=your-email@example.com
MAIL_PASSWORD=your-app-password
MAIL_FROM=your-email@example.com
MAIL_PORT=587
MAIL_SERVER=smtp.gmail.com
MAIL_STARTTLS=true
MAIL_SSL_TLS=false

# App
APP_BASE_URL=http://localhost:8000
FRONTEND_URL=http://localhost:5173
UPLOAD_DIR=./uploads

# EMAIL domain ที่อนุญาตให้ลงทะเบียน (comma-separated)
ALLOWED_EMAIL_DOMAINS=kmitl.ac.th,student.kmitl.ac.th

# LINE OA (เผื่ออนาคต, ใส่เปล่าไว้ก่อนถ้ายังไม่ใช้)
LINE_CHANNEL_ACCESS_TOKEN=
```

---

## 8. วิธีรันโปรเจกต์ (Development Setup)

### Backend
```bash
cd backend
python -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env           # แก้ค่าใน .env ก่อน
alembic upgrade head            # สร้างตารางในฐานข้อมูล
python -m app.main              # รัน dev server ที่ port 8000
# Swagger UI ดูได้ที่ http://localhost:8000/docs
```

### Frontend
```bash
cd frontend
npm install
cp .env.example .env
npm run dev                    # รัน dev server ที่ port 5173
```

### Docker Compose (ใช้ตอน deploy หรือทดสอบ full stack)
```bash
docker compose up --build      # dev
docker compose -f docker-compose.prod.yml up --build  # prod
```

---

## 9. API Response Format

**สำเร็จ (200/201):** คืน object ตาม Pydantic response schema โดยตรง

**Error:** คืนในรูป
```json
{
  "detail": "คำอธิบายข้อผิดพลาดที่อ่านเข้าใจ"
}
```

**Pagination (รายการ):**
```json
{
  "items": [...],
  "total": 42,
  "page": 1,
  "page_size": 20
}
```

Frontend อ่านค่า error จาก `error.response.data.detail` เสมอ

---

## 10. Pending Items (รอข้อมูลเพิ่มเติม)

- **ไฟล์ Excel คลังอุปกรณ์เดิม** — รอทีมอื่นส่งมา เมื่อได้รับแล้วให้ทำ column mapping จากคอลัมน์ Excel → ตาราง `equipment` / `equipment_categories` แล้วเขียนสคริปต์ seed data import ไว้ใน `backend/scripts/import_equipment.py`
- **ALLOWED_EMAIL_DOMAINS** — ยืนยันกับอาจารย์ว่า domain อีเมลมหาลัยที่ใช้จริงคืออะไร ก่อน deploy จริง
- **LINE OA** — ยืนยัน Channel Access Token เมื่อพร้อม implement stretch goal นี้

---

## 11. สิ่งที่อยู่นอกขอบเขตเฟสนี้ (Out of Scope)

- ระบบคำนวณค่าปรับ/ค่าเสียหายอัตโนมัติ — บันทึกความเสียหายได้แต่ยังไม่คิดค่าปรับ
- LINE OA notification — เป็น stretch goal ถ้าเวลาพอ
- SSO / ผูกกับระบบบัญชีมหาวิทยาลัย — ไม่รวมในเฟสนี้
- รายงาน Export Excel
