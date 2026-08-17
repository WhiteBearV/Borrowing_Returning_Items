# แผนเตรียม Deploy — ระบบยืม-คืนอุปกรณ์

> เป้าหมาย: ขึ้น Proxmox VM คณะ ใช้งานจริงผ่าน LAN ผู้ใช้ ~100–300 คน
> สร้างเมื่อ 2 ส.ค. 2026 · **ข้อ 1–16 ทำครบแล้ว** เหลือแต่ที่ต้องยืนยันบน VM จริง (ดูท้ายไฟล์)
> อัปเดต 13 ส.ค. 2026: เพิ่ม `ENABLE_EMAIL` flag (ปิดอีเมลไว้ก่อนรอบ pilot นี้ตั้งใจ) + แก้บั๊กที่เจอจากจำลอง QA จริง (ดูหัวข้อ "เจอเพิ่มระหว่างทำ") + ตรวจ `docker-compose.prod.yml` ซ้ำด้วย `.env` จริง ผ่านครบ (ดู Verification)

## สรุปสถานะ

**ฟีเจอร์เสร็จแล้วจริง** — endpoint ครบ 100% ตาม `02-system-design.md`, business rule 13 ข้อบังคับใช้ครบใน `borrow_service.py`, alembic เรียงตรงไม่แตก head, เทสต์ 113 ตัว
**ปัญหาอยู่ที่ชั้น deploy + ความปลอดภัย** ซึ่งแก้ครบแล้ว — เดิม `docker compose -f docker-compose.prod.yml up --build` รันไม่ขึ้นเลย ตอนนี้ยกสแตกขึ้นได้จริงและผ่านการตรวจ 8 ข้อ

**เจอเพิ่มระหว่างทำ (ไม่ได้อยู่ในแผนตอนแรก):**
- `email.py` ตั้ง `MAIL_FROM` fallback เป็น `dev@localhost` ซึ่งไม่ผ่าน validator ของ pydantic → **แอปบูตไม่ขึ้นเลยบนเครื่องที่ยังไม่ตั้ง SMTP** เจอตอนยกสแตกจริง ไม่มีทางเจอจากการอ่านโค้ด แก้เป็น `noreply@example.com`
- `uploads/imports/` มีไฟล์ทะเบียนครุภัณฑ์ค้างอยู่ **93 ไฟล์ (1.9 MB)** ที่โหลดได้โดยไม่ต้อง login — ย้ายออกไป `backend/import_tmp/` แล้ว
- `update_equipment` ปล่อยให้ตั้ง `quantity_total` ต่ำกว่า `quantity_available` ได้ ซึ่งจะไปชน CHECK constraint ใหม่แล้วกลายเป็น 500 → ดักให้ลดของว่างตามอัตโนมัติ
- **(13 ส.ค.)** `AuditLogResponse.actor_id` ไม่ใช่ Optional ทั้งที่ DB ตั้งใจให้ null ได้ตอน user ถูกลบ (`ON DELETE SET NULL`) → หน้า Audit Log 500 ทันทีที่มี log ของ admin ที่ถูกลบไปแล้ว แก้เป็น `uuid.UUID | None`
- **(13 ส.ค.)** `RegisterRequest.student_id` ไม่มี validation ฝั่ง backend เลย ทั้งที่ frontend บังคับ `\d{10}` — ยิง API ตรง ๆ ใส่ค่าอะไรก็ผ่าน (เจอจากจำลอง QA จริงด้วย Postman-style test) แก้ให้ตรงกับ frontend เป๊ะ

---

## กลยุทธ์หลัก: ยิงผ่าน `/api` origin เดียว

`frontend/vite.config.js:8-13` **มี proxy `/api` → `localhost:8000` พร้อม rewrite อยู่แล้ว** แต่ frontend ไม่ได้ใช้เพราะ `VITE_API_URL` เป็น URL เต็ม

แค่ตั้ง **`VITE_API_URL=/api`** + ให้ nginx rewrite แบบเดียวกับ vite → ได้ 5 อย่างฟรี **โดยไม่แก้โค้ด frontend สักบรรทัด**:
ไม่ต้องตั้ง CORS · IP ไม่ถูกฝังใน bundle · ไม่ต้องเปิด port 8000 · วาง rate limit + จำกัดขนาดไฟล์ที่ nginx ได้ · เติม TLS ทีหลังแก้ไฟล์เดียว

> ⚠️ **ห้ามใช้ path prefix ตรง ๆ แทน `/api`** — frontend route `/dashboard` (`App.jsx:45`) กับ `/equipment` (`:50-51`) ชนกับ API prefix พอดี

---

## Tier 0 — Blocker (ไม่แก้ = รันไม่ขึ้น)

- [x] **1. `frontend/nginx.conf`** (ไฟล์ใหม่) — ไม่มีในดิสก์และไม่เคย commit แต่ `frontend/Dockerfile:10` เรียกใช้ → build fail
  - SPA fallback `try_files $uri $uri/ /index.html` (ไม่มี = deep link 404 ทุกหน้า)
  - `location /api/` → rewrite ตัด `/api` + `proxy_pass http://backend:8000`
  - `client_max_body_size 11m` — ตัดไฟล์ยักษ์ที่ขอบก่อนถึง Python
  - `limit_req` เฉพาะ `/api/auth/login` + `/api/auth/forgot-password` — อุด brute-force โดยไม่แตะ backend
  - เตรียม block `listen 443` เป็น comment รอวันมี domain
- [x] **2. `.env.prod.example` (root) + แก้ `docker-compose.prod.yml`**
  - prod ไม่มีที่มาของ `${POSTGRES_*}` และไม่ override `DATABASE_URL` (ชี้ `localhost` = ตัว container เอง)
  - เลิกใช้ `env_file: ./backend/.env` (ไฟล์ dev ที่มี `DEV_AUTO_VERIFY_EMAIL=true`) → ใช้ root `.env`
  - `environment:` ตั้ง `DATABASE_URL=...@db:5432/...` (ชนะ `env_file` จึงตั้งผิดไม่ได้)
  - `command: sh -c "alembic upgrade head && uvicorn ... --workers 1"`
    `--workers 1` = วิธีสั้นที่สุดกัน APScheduler รันซ้ำ (async worker เดียวรับ 300 คนสบาย)
  - db healthcheck + backend `depends_on: condition: service_healthy` (prod หายไป ทั้งที่ dev มี)
  - frontend `build.args: VITE_API_URL=/api`, ลบ `"443:443"` (ไม่มีอะไร listen)
  - `logging: json-file max-size 10m max-file 3` ทั้ง 3 service — กัน log กินดิสก์เต็ม VM
- [x] **3. `frontend/Dockerfile`** — เพิ่ม `ARG/ENV VITE_API_URL` **ก่อน** `RUN npm run build` (vite inline ตอน build ไม่ใช่ตอน run)
- [x] **4. `.dockerignore` 2 ไฟล์** — ตอนนี้ไม่มีทั้งคู่ → `backend/Dockerfile:13` `COPY . .` **อบ `backend/.env` (SECRET_KEY, รหัสอีเมล) ลง image layer** + ลาก `venv/` และ `uploads/` 14MB เข้าไป; `frontend/Dockerfile:5` ทับ `node_modules` ที่ `npm ci` เพิ่งสร้าง

---

## Tier 1 — ช่องโหว่ร้ายแรง / บั๊กที่ทำข้อมูลพัง

- [x] **5. สต็อกติดลบจาก race condition — สำคัญที่สุด**
  `borrow_service.py:289-309` เป็น read-check-modify ใน Python ล้วน ไม่มี lock (`with_for_update` = 0 hit ทั้ง repo) และ `0001_initial_schema.py:70` ไม่มี CHECK constraint ที่ design doc §2.3 กำหนด
  → แอดมิน 2 คนอนุมัติของชิ้นสุดท้ายพร้อมกัน = **ปล่อยของชิ้นเดียวออกไป 2 ครั้ง** เงียบ ๆ ไม่มี error
  - `select(Equipment).where(id.in_(...)).order_by(Equipment.id).with_for_update().execution_options(populate_existing=True)` ก่อนลูป (order_by กัน deadlock, populate_existing บังคับรีเฟรชค่าที่ selectinload โหลดไว้)
  - migration `0016` เพิ่ม `CHECK (quantity_available >= 0 AND quantity_available <= quantity_total)` เป็นตาข่ายชั้นสุดท้าย
  - **เขียนเทสต์ 1 ตัว**: อนุมัติพร้อมกัน 2 session → สำเร็จ 1 ล้ม 1
- [x] **6. จำกัดขนาดไฟล์ก่อนอ่านเข้า RAM**
  `equipment_service.py:37-39` + `import_service.py:244-246` ทำ `await file.read()` **ก่อน** เช็คขนาด
  `POST /users/me/avatar` (`routers/users.py:34-41`) นักศึกษาคนไหนก็ยิงได้ → ส่ง 4GB ไป worker เดียวก็ OOM ทั้งระบบล่ม
  → เช็ค `file.size` ก่อน `read()` ทั้ง 2 จุด (+ nginx เป็นด่านแรกจากข้อ 1)
- [x] **7. ไฟล์ทะเบียนที่ import หลุดสาธารณะ**
  `import_service.py:248-253` เขียน Excel ทะเบียนครุภัณฑ์คณะลง `UPLOAD_DIR/imports/` ซึ่ง `main.py:36` mount เป็น `StaticFiles` **ไม่มี auth**
  → ย้าย import dir ออกนอก `UPLOAD_DIR` (เพิ่ม `IMPORT_DIR` ใน `config.py`, แก้ `_import_path()` + จุดเขียนไฟล์)
- [x] **8. `DEV_AUTO_VERIFY_EMAIL` + เตือนตอน startup**
  `backend/.env:28` = `true` ทั้งที่ `config.py:43` เขียนคอมเมนต์ไว้เองว่า "ห้าม True ใน production" → ใครสมัครด้วยอีเมล `@cdti.ac.th` ที่ไม่ใช่ของตัวเองก็เข้าใช้ได้ทันที
  - เพิ่ม warning ใน `main.py` lifespan: เตือนถ้า `DEV_AUTO_VERIFY_EMAIL=true`
  - เตือนถ้า `email.py:6,18` ตั้ง `SUPPRESS_SEND=True` เงียบ ๆ (อีเมลไม่ออกโดยไม่มีใครรู้)
  - **ต้องทดสอบส่งเมลจริงก่อน deploy** → ผ่าน = ตั้ง `false`; ไม่ผ่าน = ยอม `true` ชั่วคราวแต่**ต้องปิดหน้าสมัครเอง** ให้แอดมินสร้างบัญชีผ่าน `POST /users` แทน
- [x] **9. ความยาวรหัสผ่านขั้นต่ำ** — `schemas/auth.py:8,33` + `schemas/user.py:25` เป็น `password: str` เปล่า สมัครด้วย `"1"` ผ่านฉลุย
  → `Field(min_length=8, max_length=72)` (72 เพราะ bcrypt ตัดทิ้งเกินนั้นเงียบ ๆ) + แก้ข้อความที่ frontend ให้ตรง
- [x] **10. Scheduler timezone** — `scheduler.py:15` ไม่ตั้ง timezone → container เป็น UTC → `CronTrigger(hour=0)` **ยิง 07:00 น. ไทย** ทั้งที่ `config.py:7` นิยาม `TZ = ZoneInfo("Asia/Bangkok")` ไว้แล้วแต่ไม่มีใครใช้
  → `AsyncIOScheduler(timezone=settings.TZ)` + `misfire_grace_time=3600` (VM ปิดคร่อมเที่ยงคืน = รอบนั้นหายถาวร)
- [x] **11. ต่อเวลาแล้วยังโดนตีตราเกินกำหนด** — `renew_item` (`borrow_service.py:399-400`) เขียนแค่ `item.extended_due_date` ไม่แตะ `req.due_date` แต่ `scheduler.py:57` กรองด้วย `req.due_date` อย่างเดียว → **นักศึกษาที่ต่อเวลาถูกต้องยังโดนอีเมลทวง** และ `is_overdue` ไม่เคยรีเซ็ต
  → อัปเดต `req.due_date` เป็นวันไกลสุดของ item ทั้งใบ + `req.is_overdue = False`

---

## Tier 2 — ต้องมีก่อนใช้จริง

- [x] **12. สร้าง admin คนแรก — ตอนนี้ไม่มีทางทำเลย**
  `POST /users` ที่รับ `role` ถูกกั้นด้วย `require_admin` (`routers/users.py:56-59`) และ `RegisterRequest` (`schemas/auth.py:4-9`) ไม่มีฟิลด์ `role` → ไก่กับไข่ (grep `create_admin|superuser|bootstrap` = 0 hit)
  → `backend/scripts/create_admin.py` ~15 บรรทัด ใช้ `hash_password` ที่มีอยู่
- [x] **13. `/health` แตะ DB จริง** — `main.py:49-51` คืน literal → เขียวตลอดแม้ Postgres ตาย ใช้เป็น healthcheck ไม่ได้
- [x] **14. Backup ที่ใช้ได้จริงกับ Docker** — `backup_db.sh` พัง 3 ทาง: `pg_dump` ยิงจาก host แต่ prod ไม่เปิด 5432 / อ่าน `DATABASE_URL` ที่ชี้ `localhost` / **tar `backend/uploads` บน host ซึ่งว่าง เพราะไฟล์จริงอยู่ใน volume `uploads_data`** → ได้ backup ที่ดูเหมือนสำเร็จแต่ไม่มีรูปสักไฟล์
  → เปลี่ยนเป็น `docker compose exec -T` + เขียน `restore_db.sh` คู่กัน (ตอนนี้ restore เป็นคำสั่ง manual ใน `README.md:141-155`)
  → **ทดสอบ restore ลง DB เปล่า 1 ครั้งจริง** — backup ที่ไม่เคย restore ไม่นับว่ามี
- [x] **15. กันเทสต์ล้าง DB จริง** — `tests/conftest.py:8,27` import `AsyncSessionLocal` ตัวจริงแล้ว `delete()` ตรง ๆ ถ้าใครรัน `pytest` บน VM ที่มี prod `.env` **ข้อมูลจริงหายทันที** → assert ชื่อ DB ต้องลงท้าย `_test`
- [x] **16. ตารางแอดมินบนมือถือ (ของแถม 2 คำ)** — `EquipmentManagePage.jsx:376` + `UsersPage.jsx:67` ใช้ `overflow-hidden` ตาราง 8 คอลัมน์ถูกตัดทิ้ง เลื่อนไม่ได้ → `overflow-x-auto` (`AuditLogPage.jsx:40` ทำถูกอยู่แล้ว)

---

## ข้ามไปก่อน — ตัดสินใจแล้ว ไม่ใช่ลืม

ทุกข้อข้างล่างเป็นปัญหาจริงที่ตรวจเจอ แต่ **ประเมินแล้วว่ารอได้** สำหรับ pilot บน LAN คณะ
ไม่ใช่ของที่มองข้าม — ถ้าเงื่อนไขใน *กลับมาทำเมื่อ* เกิดขึ้นเมื่อไหร่ ต้องทำทันที

### ความปลอดภัย

- ~~**TLS / HTTPS (certbot)**~~ — **ทำแล้ว 17 ส.ค. 2026** (feedback แอดมินหลังทดลองใช้จริง ขอปิดช่องดักรหัสผ่านระหว่างทางก่อน pilot จริง)
  - ยังไม่มี domain จึงใช้ **self-signed cert** แทน certbot ไปก่อน: `./gen-self-signed-cert.sh <ip-vm>` สร้าง cert (SAN=IP, อายุ 2 ปี) mount เข้า `docker-compose.prod.yml` ที่ `/etc/nginx/certs/`, `nginx.conf` เปิด `listen 443 ssl` แล้ว + `:80` redirect ไป `:443` ทั้งหมด + เพิ่ม security headers (HSTS/X-Frame-Options/X-Content-Type-Options/Referrer-Policy)
  - ผลข้างเคียงที่ต้องแจ้งผู้ใช้: เบราว์เซอร์จะเตือน "ไม่ปลอดภัย" ครั้งแรก (cert ไม่มี CA รับรอง) กด "ขั้นสูง > ไปต่อ" ได้ปกติ — เข้ารหัสจริง แค่ไม่มีใครยืนยันตัวตน server
  - *กลับมาทำเมื่อมี domain จริง:* สลับจาก self-signed ไปเป็น certbot แค่เปลี่ยนไฟล์ cert ใน `certs/` เป็นของ Let's Encrypt (path เดิมใน nginx.conf ไม่ต้องแก้)

- **Refresh token เพิกถอนไม่ได้ / ไม่มี logout / ไม่ rotate**
  - *รอได้เพราะ:* token อายุ 7 วัน อยู่ใน LAN ปิด และแอดมินตัดสิทธิ์ทันทีได้ด้วย `is_active` (`auth_service.py:110`) ซึ่งเช็คทุก request
  - *กลับมาทำเมื่อ:* token รั่วจริง หรือเปิดออกอินเทอร์เน็ต — จุดที่เจ็บสุดคือรีเซ็ตรหัสผ่านแล้ว session เก่ายังใช้ได้ (`auth_service.py:136-149`)

- **ปิด `/docs` `/redoc` `/openapi.json`**
  - *รอได้เพราะ:* อยู่หลัง LAN และตรวจครบทั้ง 9 router แล้วว่า**ไม่มี endpoint แอดมินตัวไหนหลุด `require_admin` เลย** รู้ผัง API ก็ยิงไม่ได้อยู่ดี ระหว่าง pilot ทีมได้ใช้ทดสอบมากกว่าเสีย
  - *กลับมาทำเมื่อ:* เปิดออกนอก LAN — ตอนนี้ `config.py` ยังไม่มี `DEBUG` ให้ gate ต้องเพิ่มก่อน

- **Container รันเป็น root · ไม่มี TrustedHostMiddleware · ไม่เช็ค magic byte ของรูป**
  - *รอได้เพราะ:* ต้องเจาะเข้ามาถึงใน LAN ให้ได้ก่อนถึงจะใช้ประโยชน์ได้ และ `.dockerignore` (ข้อ 4) ตัดความเสี่ยงหลักคือ secret ติดไปกับ image ออกไปแล้ว
  - *กลับมาทำเมื่อ:* ก่อนเปิดสาธารณะ หรือหลัง pilot ผ่าน

### คุณภาพ / กระบวนการ

- **Structured logging** (แทน `print()` 8 จุด)
  - *รอได้เพราะ:* `docker compose logs` อ่านได้อยู่ และ log rotation จากข้อ 2 กันดิสก์ VM เต็มแล้ว ซึ่งเป็นความเสี่ยงจริงข้อเดียว
  - *กลับมาทำเมื่อ:* ต้องไล่บั๊ก production ย้อนหลังเกิน 30MB — จุดที่จะเจ็บคือ `borrow_service.py` กลืน error อีเมล 6 จุดแบบเงียบ ๆ

- **CI / GitHub Actions**
  - *รอได้เพราะ:* แก้โค้ดคนเดียว รัน `pytest` เองก่อน commit ได้ ยังไม่มีใครแก้ทับกัน
  - *กลับมาทำเมื่อ:* มีคนแก้โค้ดพร้อมกันมากกว่า 1 คน

- **Pin `requirements.txt`** (ตอนนี้ `>=` เกือบทั้งหมด)
  - *รอได้เพราะ:* image ถูก build ครั้งเดียวแล้วใช้ยาวตลอด pilot ไม่ได้ rebuild บ่อยจนเวอร์ชันเลื่อน
  - *กลับมาทำเมื่อ:* ก่อนส่งมอบจริง หรือก่อน rebuild บนเครื่องอื่น — `pip freeze > requirements.lock` พอ

### UI / โครงสร้างโค้ด

- **Sidebar เป็น drawer บนมือถือ**
  - *รอได้เพราะ:* `Sidebar.jsx:51` เป็น `w-56` ตายตัว ไม่มี responsive prefix สักตัว → ต้องรื้อ layout ใหม่ทั้งชั้น งานใหญ่กว่าที่เห็น และข้อ 16 แก้ส่วนที่เจ็บที่สุด (ตารางเลื่อนไม่ได้) ไปแล้ว
  - *กลับมาทำเมื่อ:* แอดมินต้องรับคืนของหน้างานด้วยมือถือจริง

- **แตก component `borrow/` `equipment/` ที่ยังเป็นโฟลเดอร์ว่าง**
  - *รอได้เพราะ:* เป็นหนี้โครงสร้างล้วน ๆ ผู้ใช้ไม่รู้สึกอะไรเลย และการรื้อก่อนวันขึ้นระบบเสี่ยงทำของที่ใช้ได้อยู่พัง
  - *กลับมาทำเมื่อ:* ต้องแก้ `EquipmentManagePage.jsx` (884 บรรทัด) ครั้งต่อไป — แตกตอนนั้นคุ้มกว่า

- **`search` param ใน `GET /users`**
  - *รอได้เพราะ:* มี filter `role` + `major` แล้ว (`routers/users.py:44-53`) และผู้ใช้ ~300 คนกดดูทีละหน้าก็เจอ
  - *กลับมาทำเมื่อ:* แอดมินบ่นว่าหาคนไม่เจอ

- **LINE OA notification**
  - *รอได้เพราะ:* นอกขอบเขตเฟสนี้ตาม CLAUDE.md §11 และยังไม่มี Channel Access Token (`notification_service.py:58` มี TODO คาไว้)
  - *กลับมาทำเมื่อ:* อาจารย์ยืนยัน token มาแล้ว

---

## Verification

### ตรวจแล้วบนเครื่อง dev (2 ส.ค.)

- [x] 1. **Build ผ่าน** — `docker compose -f docker-compose.prod.yml build` สำเร็จทั้ง 3 image
- [x] 2. **Stack ขึ้น** — db healthy → backend รอจนพร้อมแล้วค่อยบูต, log เห็น `alembic upgrade` ถึง `0016 (head)`
- [x] 3. **SPA + proxy** — หน้าแรก 200, `/admin/equipment` คืน `index.html` ไม่ 404, `/api/health` → `{"status":"ok"}`, `/api/equipment` ไม่มี token → 401
- [x] 4. **สร้าง admin** — `create_admin.py` สร้างบัญชีได้ แล้ว login ผ่าน nginx ได้ token จริง, `/api/settings` + `/api/audit-logs` ตอบ 200 ด้วย token / 401 ถ้าไม่มี
- [x] 5. **Race condition** — เทสต์ `test_stock_race.py` ผ่าน **และพิสูจน์แล้วว่าพังถ้าถอด `with_for_update()` ออก** (เทสต์เวอร์ชันแรกที่ยิง 2 ใบพร้อมกันเฉย ๆ ผ่านทั้งที่ยังไม่มี lock — ใช้ไม่ได้ จึงเขียนใหม่ให้บังคับชนแน่นอน)
- [x] 6. **CHECK constraint** — `UPDATE equipment SET quantity_available=-1` โดน `IntegrityError` ปฏิเสธ
- [x] 7. **Rate limit** — ยิง login ผิดรวด: `401 ×6` แล้ว `429 ×14`; `/api/health` ยิงติดกัน 8 ครั้งยังได้ 200 (ไม่โดนลูกหลง)
- [x] 8. **Regression** — `pytest` 113 ตัวผ่านหมด + `npm test` 5 ตัวผ่าน

**ตรวจซ้ำ 13 ส.ค. (หลังแก้ ENABLE_EMAIL + บั๊กที่เจอจาก QA)** — ยก `docker-compose.prod.yml` จริงด้วย `.env` จริงที่ root (port ชั่วคราวกัน 80 ชนของเครื่อง dev เอง ไม่กระทบขั้นตอนจริงบน VM ที่ port 80 ว่าง): build ผ่านทั้ง 3 image, `alembic` ขึ้นถึง `0016 (head)` บน DB เปล่า, backend healthcheck ผ่าน, warning `ENABLE_EMAIL=false` ขึ้นถูกต้อง, `/` และ deep-link route คืน 200, `/api/health` + `/api/auth/login` proxy ผ่าน nginx ถูกต้อง, `frontend/public/notification.wav` bundle เข้า image และโหลดผ่าน nginx ได้จริง (439,718 bytes ตรงต้นฉบับ), บั๊ก `student_id` ที่เพิ่งแก้ทำงานถูกใน container (422 ตามคาด) — ลบ container/volume/image ทดสอบออกหมดแล้ว ไม่ค้าง

### ยังต้องทำบน VM จริง

- [x] ~~9. ทดสอบ SMTP~~ — **เลื่อนออกไปตั้งใจ**: รอบ pilot นี้ตั้ง `ENABLE_EMAIL=false` (default ใน `config.py`) + `DEV_AUTO_VERIFY_EMAIL=true` แทน สมัครแล้วใช้ได้ทันทีไม่ต้องรอเมล (ทดสอบแล้วจริงในเบราว์เซอร์) — **แต่หน้าลงทะเบียนยังขึ้นข้อความ "ตรวจสอบอีเมลของคุณ" หลอกอยู่** ต้องบอกผู้ทดสอบล่วงหน้าว่าไม่ต้องรอเมล กดกลับไปหน้า login แล้ว login ได้เลย → กลับมาทำเมื่อพร้อมต่อ SMTP จริง: ตั้ง `ENABLE_EMAIL=true` + `MAIL_*` ใน `.env` แล้วค่อยทดสอบข้อนี้
- [ ] 10. **End-to-end บนเบราว์เซอร์** — ยื่นคำขอ → อนุมัติ (สต็อกลด) → ต่อเวลา → รับคืน durable `ok` (สต็อกคืน) + วัสดุ `used_up` (สต็อกไม่คืน) → `completed` → โหลด PDF ได้ → audit log ครบ
  **(13 ส.ค.)** ทำ flow นี้เต็มบนเบราว์เซอร์จริงแล้วที่เครื่อง dev (ไม่ใช่ VM) ด้วย 3 persona (นักศึกษา 2 + admin จริง) — ผ่านหมดรวมถึงเสียงแจ้งเตือนจริง ยังเหลือแค่ทำซ้ำบน VM จริงเพื่อตัดปัจจัยเรื่อง network/LAN ออก
- [ ] 11. **Backup/restore ซ้อมจริง 1 รอบ** — `backup_db.sh` → `tar tzf` ต้อง**เห็นไฟล์รูปจริง** → `restore_db.sh` ลง DB แล้ว login ได้
- [ ] 12. **Scheduler** — ตั้ง `due_date` ย้อนหลัง เรียก `_check_overdue()` มือ → แจ้งเตือนครั้งเดียวไม่ซ้ำ และคนที่ต่อเวลาแล้วต้องไม่ถูกทวง

---

---

## ขั้นตอน deploy บน VM

```bash
git pull
cp .env.prod.example .env

# แก้ .env อย่างน้อย 4 ค่านี้:
#   SECRET_KEY        → openssl rand -hex 32
#   POSTGRES_PASSWORD → openssl rand -hex 24
#   FRONTEND_URL / APP_BASE_URL → http://<ip-ของ-vm>   (ไม่ต้องใส่ :8000)
#   MAIL_*            → ถ้ามี SMTP ของคณะ
#
# ENABLE_EMAIL ปล่อย false (default) ไว้ก่อนสำหรับรอบ pilot นี้ — ไม่ต้องแก้
# ตั้ง true พร้อม MAIL_* ค่อยเปิดตอนพร้อมส่งอีเมลจริง (ไม่ต้องแก้โค้ด)

docker compose -f docker-compose.prod.yml up --build -d
docker compose -f docker-compose.prod.yml logs -f backend   # ดูว่า alembic ขึ้นถึง head

# สร้างแอดมินคนแรก (ไม่มีทางทำผ่านหน้าเว็บ)
docker compose -f docker-compose.prod.yml exec backend python scripts/create_admin.py

# ตั้ง cron backup ตี 2 ทุกวัน
crontab -e
# 0 2 * * * bash /path/to/TermPJ/backend/scripts/backup_db.sh >> /var/log/eqb-backup.log 2>&1
```

เข้าใช้งานที่ `http://<ip-ของ-vm>/` — เปิดแค่ port 80 ทางเดียว backend กับ db ไม่โผล่ออกนอก

**ถ้า `.env` ตั้ง `FRONTEND_URL` ผิด** ลิงก์ยืนยันอีเมลกับรีเซ็ตรหัสผ่านจะพาผู้ใช้ไปผิดที่ — ตรวจข้อนี้ก่อนเปิดให้คนอื่นใช้
