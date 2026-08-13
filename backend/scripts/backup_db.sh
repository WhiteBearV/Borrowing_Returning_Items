#!/usr/bin/env bash
# สำรองฐานข้อมูล + รูปที่อัปโหลด แล้วลบไฟล์เก่าเกิน RETAIN_DAYS วัน
#
# ทำไมต้องมี: อาจารย์ห่วงว่า "ถ้า Postgres เสียจะทำยังไง" คำตอบคือกู้จาก backup
# ไม่ใช่ย้ายไป MySQL — ระบบผูกกับ JSONB/UUID ของ Postgres อยู่
#
# รูปอยู่บนดิสก์ (uploads/) ไม่ได้อยู่ใน DB จึงต้อง backup แยกอีกชุด
# ไม่งั้นกู้ DB มาแล้ว path รูปในตารางจะชี้ไปไฟล์ที่ไม่มีอยู่
#
# ทุกอย่างวิ่งผ่าน docker compose exec เพราะ deploy จริงไม่ publish port 5432
# ออกมาที่ host และไฟล์รูปจริงอยู่ใน volume uploads_data ไม่ใช่ backend/uploads
# บนดิสก์ — เวอร์ชันก่อนหน้า tar โฟลเดอร์ว่างบน host แล้วรายงานว่าสำเร็จ
#
# ใช้:  bash backend/scripts/backup_db.sh
# cron ตี 2 ทุกวัน:  0 2 * * * bash /path/to/TermPJ/backend/scripts/backup_db.sh >> /var/log/eqb-backup.log 2>&1
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
COMPOSE=(docker compose -f "$REPO_ROOT/docker-compose.prod.yml")

BACKUP_DIR="${BACKUP_DIR:-/var/backups/equipment-borrow}"
RETAIN_DAYS="${RETAIN_DAYS:-7}"
STAMP="$(date +%Y%m%d-%H%M%S)"

# ชื่อ DB/user อ่านจาก .env ที่ root ตัวเดียวกับที่ compose ใช้
set -a; source "$REPO_ROOT/.env"; set +a
: "${POSTGRES_USER:?ต้องมี POSTGRES_USER ใน .env}"
: "${POSTGRES_DB:?ต้องมี POSTGRES_DB ใน .env}"

mkdir -p "$BACKUP_DIR"

echo "[$(date -Is)] dump ฐานข้อมูล → $BACKUP_DIR/db-$STAMP.dump"
# -Fc = custom format บีบอัดในตัว และ restore ทีละตารางได้
# -T กัน docker จัดสรร TTY ซึ่งจะทำให้ binary stream เพี้ยน
"${COMPOSE[@]}" exec -T db pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB" \
  > "$BACKUP_DIR/db-$STAMP.dump"

echo "[$(date -Is)] เก็บรูปจาก volume → $BACKUP_DIR/uploads-$STAMP.tar.gz"
"${COMPOSE[@]}" exec -T backend tar czf - -C /app uploads \
  > "$BACKUP_DIR/uploads-$STAMP.tar.gz"

# backup ที่ว่างเปล่าคือ backup ที่ใช้กู้ไม่ได้ ต้องรู้ตั้งแต่ตอนนี้ ไม่ใช่ตอนของหาย
for f in "$BACKUP_DIR/db-$STAMP.dump" "$BACKUP_DIR/uploads-$STAMP.tar.gz"; do
  if [[ ! -s "$f" ]]; then
    echo "ผิดพลาด: $f ว่างเปล่า — backup ครั้งนี้ใช้ไม่ได้" >&2
    exit 1
  fi
done

echo "[$(date -Is)] ลบ backup เก่าเกิน $RETAIN_DAYS วัน"
find "$BACKUP_DIR" -name 'db-*.dump' -mtime "+$RETAIN_DAYS" -delete
find "$BACKUP_DIR" -name 'uploads-*.tar.gz' -mtime "+$RETAIN_DAYS" -delete

echo "[$(date -Is)] เสร็จ — ไฟล์ล่าสุด:"
ls -lh "$BACKUP_DIR" | tail -3
