#!/usr/bin/env bash
# สำรองฐานข้อมูล + รูปที่อัปโหลด แล้วลบไฟล์เก่าเกิน RETAIN_DAYS วัน
#
# ทำไมต้องมี: อาจารย์ห่วงว่า "ถ้า Postgres เสียจะทำยังไง" คำตอบคือกู้จาก backup
# ไม่ใช่ย้ายไป MySQL — ระบบผูกกับ JSONB/UUID ของ Postgres อยู่
#
# รูปอยู่บนดิสก์ (uploads/) ไม่ได้อยู่ใน DB จึงต้อง backup แยกอีกชุด
# ไม่งั้นกู้ DB มาแล้ว path รูปในตารางจะชี้ไปไฟล์ที่ไม่มีอยู่
#
# ใช้: bash backend/scripts/backup_db.sh
# ตั้ง cron ตี 2 ทุกวัน:  0 2 * * * bash /path/to/backend/scripts/backup_db.sh >> /var/log/eqb-backup.log 2>&1
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/var/backups/equipment-borrow}"
RETAIN_DAYS="${RETAIN_DAYS:-7}"
UPLOAD_DIR="${UPLOAD_DIR:-$(dirname "$0")/../uploads}"
STAMP="$(date +%Y%m%d-%H%M%S)"

# อ่าน DATABASE_URL จาก .env ถ้าไม่ได้ตั้งไว้ใน environment
if [[ -z "${DATABASE_URL:-}" && -f "$(dirname "$0")/../.env" ]]; then
  DATABASE_URL="$(grep -E '^DATABASE_URL=' "$(dirname "$0")/../.env" | cut -d= -f2-)"
fi
: "${DATABASE_URL:?ต้องมี DATABASE_URL (ตั้งใน env หรือ backend/.env)}"

# pg_dump ไม่รู้จัก +asyncpg ที่ SQLAlchemy ใช้ ต้องตัดออกก่อน
PG_URL="${DATABASE_URL/+asyncpg/}"

mkdir -p "$BACKUP_DIR"

echo "[$(date -Is)] dump ฐานข้อมูล → $BACKUP_DIR/db-$STAMP.dump"
# -Fc = custom format บีบอัดในตัว และ restore ทีละตารางได้
pg_dump -Fc "$PG_URL" -f "$BACKUP_DIR/db-$STAMP.dump"

if [[ -d "$UPLOAD_DIR" ]]; then
  echo "[$(date -Is)] เก็บรูป → $BACKUP_DIR/uploads-$STAMP.tar.gz"
  tar czf "$BACKUP_DIR/uploads-$STAMP.tar.gz" -C "$(dirname "$UPLOAD_DIR")" "$(basename "$UPLOAD_DIR")"
fi

echo "[$(date -Is)] ลบ backup เก่าเกิน $RETAIN_DAYS วัน"
find "$BACKUP_DIR" -name 'db-*.dump' -mtime "+$RETAIN_DAYS" -delete
find "$BACKUP_DIR" -name 'uploads-*.tar.gz' -mtime "+$RETAIN_DAYS" -delete

echo "[$(date -Is)] เสร็จ — ไฟล์ล่าสุด:"
ls -lh "$BACKUP_DIR" | tail -3
