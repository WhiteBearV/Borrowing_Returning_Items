# HANDOFF — ระบบยืม-คืนอุปกรณ์

อัปเดต: 22 กันยายน 2569 | เวอร์ชัน 2.0 (`1da1c22`) | ผู้พัฒนา: วีรภัทร สาลีผล

เอกสารนี้สำหรับนักพัฒนาที่มารับช่วงต่อ — สรุปว่าระบบอยู่ตรงไหน ไฟล์ไหนสำคัญ และกฎอะไรห้ามพัง
**วิธีติดตั้ง/ตั้งค่า/deploy ทั้งหมดอยู่ใน [`README.md`](README.md)** (ไม่เขียนซ้ำที่นี่ เพื่อไม่ให้ข้อมูลเก่าไม่เท่ากัน)

---

## 1. เริ่มต้น

| ต้องการ | ดูที่ |
|---|---|
| ติดตั้งเครื่อง dev | README หัวข้อ 2–3 |
| ความหมายของตัวแปรใน `.env` | README หัวข้อ 4 |
| ติดตั้ง / อัปเดตบนเซิร์ฟเวอร์ | README หัวข้อ 5–6 |
| ค่าในหน้า "การตั้งค่าระบบ" | README หัวข้อ 7 |
| สร้างบัญชีผู้ดูแลคนแรก | `python scripts/create_admin.py --superadmin <อีเมล> '<ชื่อ>'` (README 3.4) — **ไม่ต้องแทรก SQL เองแล้ว** |
| แต่ละเวอร์ชันเปลี่ยนอะไร | [`PATCH_NOTES.md`](PATCH_NOTES.md) |

---

## 2. สถานะปัจจุบัน (v2.0)

### เสร็จแล้ว ✅
| ส่วน | สถานะ |
|---|---|
| สมัคร/ยืนยันอีเมล/ล็อกอิน (รหัสนักศึกษา/username/อีเมล)/ลืมรหัสผ่าน · ยอมรับ PDPA | ✅ |
| สิทธิ์ 3 ระดับ (student / admin / superadmin) + คำขอแก้ไขข้อมูล + หน้าตรวจสอบระบบ | ✅ |
| รายชื่อนักศึกษาที่รับรอง (นำเข้า xls/xlsx/csv/pdf) + คิวอนุมัติผู้สมัคร + ชั้นปี/เทียบโอน | ✅ |
| อุปกรณ์: CRUD, 3 ประเภท (ครุภัณฑ์/วัสดุใช้ซ้ำ/วัสดุสิ้นเปลือง), รูป, QR, ชุดอุปกรณ์, ชิ้นส่วน, นำเข้าทะเบียน, แก้ไขหลายรายการ | ✅ |
| ทะเบียน/การเงิน: วันที่ได้มา, อายุ, ค่าเสื่อม/มูลค่าตามบัญชี · ค่าคุณภาพอุปกรณ์ | ✅ |
| ยืม: ตะกร้า, วันคืนรายชิ้น, อนุมัติบางชิ้น, เลือกหน่วยที่จ่าย, นัดรับ/นัดคืน, ต่อเวลาแบบขออนุมัติ, ใบยืมที่เซ็นแล้ว | ✅ |
| คืน: สรุปผลตามประเภท, รูปหลักฐานความเสียหาย, ค่าปรับ + ค่าเสียหาย (freeze ตอนรับคืน) | ✅ |
| PDF ใบยืม/ใบคืน/ใบรับเข้า/ใบปลดระวาง (ฟอนต์ไทย) | ✅ |
| Dashboard · สถิติความคุ้มค่า (เลือกช่วงเวลา/รายเดือน) · หน้าค่าปรับ · Audit Log (ประโยคไทย) · Settings | ✅ |
| Scheduler: แจ้งเตือนใกล้ครบกำหนด/เกินกำหนดทุกวันตาม `notify_time` (เวลาไทย) | ✅ |
| Deploy: Docker Compose + nginx HTTPS (self-signed) + backup/restore script | ✅ |
| เทส backend 457 ตัว (pytest) | ✅ |

### ยังค้างอยู่ 🔴
| งาน | Priority | หมายเหตุ |
|---|---|---|
| Deploy v2.0 ขึ้น VM (172.16.46.134) | สูง | โค้ดบน VM ยังเป็น `695f9b7` · ต้องสร้าง SuperAdmin + นำเข้ารายชื่อนักศึกษาหลังอัปเดต (ดู PATCH_NOTES) |
| `backup_db.sh` ยังไม่สำรอง volume `private_uploads_data` + ทิ้งไฟล์ 0 ไบต์ตอนล้ม | สูง | ใบยืมที่เซ็นแล้วทำใหม่ไม่ได้ |
| Backup นอกเครื่อง (off-site) | กลาง | ตอนนี้ backup อยู่บน VM เครื่องเดียว |
| กรอก "วันที่ได้มา" ของอุปกรณ์ (1,472/1,473 ชิ้นยังว่าง) | กลาง | ค่าเสื่อม/ต้นทุนเป็นค่าประมาณจนกว่าจะกรอก |
| ยืนยัน `ALLOWED_EMAIL_DOMAINS` กับอาจารย์ | กลาง | CLAUDE.md หัวข้อ 10 |
| บล็อกการยืมของคนที่ค้างชำระค่าปรับ | ต่ำ | ตั้งใจยังไม่ทำ — เพิ่มเงื่อนไขใน `create_request` จุดเดียวเมื่อพร้อม |
| LINE OA notification | ต่ำ | Stretch goal · ยังไม่มี token |

---

## 3. ไฟล์ที่ต้องรู้

```
backend/app/
  services/borrow_service.py      ← workflow ยืม-อนุมัติ-คืน-ต่อเวลา + ค่าปรับ (_compute_fine)
  services/equipment_service.py   ← อุปกรณ์, ลำดับจ่ายของ (dispatch_order), คุณภาพ, ค่าเสื่อม (daily_depreciation/book_value)
  services/dashboard_service.py   ← Dashboard, สถิติความคุ้มค่า (get_utilization/_monthly_usage), ค่าปรับ
  services/settings_service.py    ← สิทธิ์แก้ settings รายคีย์ (ADMIN_EDITABLE_KEYS) + ตรวจค่า
  services/auth_service.py        ← สมัคร (เทียบรายชื่อที่รับรอง) / ล็อกอิน
  services/student_import_service.py ← อ่านไฟล์รายชื่อจากสำนักทะเบียน
  utils/scheduler.py              ← งานแจ้งเตือนรายวัน + reschedule_daily_jobs
  utils/duedate.py                ← effective_due_date (วันคืนที่ใช้จริง) + fmt_date
  utils/study_year.py             ← สูตรชั้นปี/ปีการศึกษา
  utils/roles.py                  ← is_staff / is_superadmin
  utils/pdf.py                    ← เอกสาร PDF ทั้งหมด (ฟอนต์ใน utils/fonts/)
  dependencies.py                 ← get_db / get_current_user / require_admin / require_superadmin

frontend/src/
  pages/student/ · pages/admin/   ← หน้าต่าง ๆ
  api/                            ← axios แยก domain (ห้ามเรียก axios ตรงในหน้า)
  utils/formatDate.js             ← formatDate / todayTH / daysSinceTH (วันที่ วว/ดด/ปปปป เวลาไทย)
  utils/role.js · utils/fine.js · utils/dueDate.js ← คู่แฝดของฝั่ง backend (ต้องตรงกัน)
  components/common/DateInput.jsx ← ใช้แทน <input type="date"> ทุกที่
  components/audit/auditLabels.js ← ป้ายภาษาไทยของ action/ฟิลด์ในหน้า Audit
```

---

## 4. กฎที่ห้ามพัง (รายละเอียดเต็มอยู่ใน `CLAUDE.md`)

- **รับคืน/สรุปผลได้เฉพาะเจ้าหน้าที่** — `require_admin()` · นักศึกษากดคืนเองไม่ได้
- **ห้าม auto-mark `returned = true` ตอนอนุมัติ** ทั้งครุภัณฑ์และวัสดุ — วัสดุต้องให้แอดมินสรุปผลภายหลัง
  (คู่มือเวอร์ชันเก่าเขียนว่าวัสดุสิ้นเปลืองคืนอัตโนมัติ — **ไม่จริงแล้ว**)
- **ค่าที่เกี่ยวกับกติกาอ่านจากตาราง `settings` เท่านั้น** ห้าม hardcode · สิทธิ์แก้แยกรายคีย์ ต้องตรงกันทั้ง backend/frontend
- **business logic อยู่ใน `services/`** router แค่ validate → เรียก service → คืนค่า · ห้าม query DB ใน router
- **สูตรที่ต้องมีจุดเดียว** (ห้ามเขียนซ้ำที่อื่น): `effective_due_date` · `_compute_fine` · `borrowed_days_expr` ·
  `daily_depreciation` · `compute_study_year` · `year_group_key` · `dispatch_order` · ฝั่งเว็บ `todayTH`/`formatDate`
- **ทุก action ของเจ้าหน้าที่ (และฝั่งผู้ยืม) ต้องลง audit** ผ่าน `audit_service.log_action` ก่อน commit
  + เพิ่มป้ายไทยใน `auditLabels.js` ทุกครั้งที่มี action/ฟิลด์ใหม่
- **วัน/เวลาเป็นเวลาไทยเสมอ** · แสดงผล วว/ดด/ปปปป (ค.ศ.)
- **ข้อมูลส่วนบุคคล:** ใบยืมที่เซ็นแล้วอยู่ใน `PRIVATE_UPLOAD_DIR` เท่านั้น · repo GitHub เป็น **public**
  ห้าม commit ไฟล์รายชื่อนักศึกษา/`.env`/ไฟล์สำรอง

---

## 5. รันเทส

```bash
cd backend && source venv/bin/activate
PYTEST_ALLOW_DB=1 pytest        # เครื่อง dev (DB ไม่ได้ลงท้าย _test) — ห้ามรันบน production
```

เทสทุกไฟล์ต้องลบข้อมูลที่ตัวเองสร้างทิ้งใน `finally` (รวม `audit_logs` ของบัญชีทดสอบ) — รายละเอียดใน README หัวข้อ 9

---

## 6. Reference

- [`README.md`](README.md) — ติดตั้ง / ตั้งค่า / deploy / backup / แก้ปัญหา
- [`PATCH_NOTES.md`](PATCH_NOTES.md) — การเปลี่ยนแปลงแต่ละเวอร์ชัน
- `CLAUDE.md` — บริบทโปรเจกต์ครบถ้วน (conventions, business rules, ตารางสิทธิ์)
- `docs/02-system-design.md` — DB schema, API endpoints
- `docs/naming-convention.md` — มาตรฐานการตั้งชื่ออุปกรณ์
- `Report/` — บันทึกความคืบหน้ารายวัน
- Swagger: `http://localhost:8000/docs` (เปิดหลังรัน backend)
