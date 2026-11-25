#!/usr/bin/env bash
# ส่ง backup รายวัน (ผลจาก backup_db.sh) ขึ้น Google Drive ของคณะแบบเข้ารหัส — สำเนานอกเครื่อง (off-site)
#
# ทำไมต้องมี: backup ใน /var/backups อยู่บน VM เดียวกับระบบ ถ้าดิสก์/VM เสียก็หายพร้อมกัน
# ทำไมต้องเข้ารหัส: ไฟล์มีข้อมูลส่วนบุคคลนักศึกษา (ชื่อ/รหัส/ใบยืมที่เซ็นแล้ว) — PDPA
#   ใน Drive เห็นแต่ไฟล์ชื่อมั่ว ๆ ที่อ่านไม่ออก บัญชีหลุดข้อมูลก็ไม่หลุด
#
# ต้องตั้ง rclone ไว้ก่อน 2 remote (root): gdrive (Drive บัญชีคณะ) + gdrive-crypt (crypt → gdrive:BEARS-backup)
# รหัสถอดเก็บนอกเซิร์ฟเวอร์ด้วย — หายแล้วกู้ backup จาก Drive ไม่ได้
#
# ใช้:  bash backend/scripts/offsite_backup.sh
# cron ต่อท้าย backup (ส่งเฉพาะเมื่อ backup สำเร็จ):
#   0 2 * * * bash .../backup_db.sh >> /var/log/eqb-backup.log 2>&1 && bash .../offsite_backup.sh >> /var/log/eqb-offsite.log 2>&1
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/var/backups/equipment-borrow}"
REMOTE="${OFFSITE_REMOTE:-gdrive-crypt:daily}"
# 2 ชั้น (ผู้ใช้ขอย้อนได้ 1–3 ปี 25 พ.ย. 69): รายวันเก็บ 90 วัน + backup วันที่ 1 ของเดือนเก็บ 3 ปี
# ~9 GB แทน ~75 GB ถ้าเก็บรายวันครบ 3 ปี
KEEP_DAYS="${OFFSITE_KEEP_DAYS:-90}"
MONTHLY_REMOTE="${OFFSITE_MONTHLY_REMOTE:-gdrive-crypt:monthly}"
MONTHLY_KEEP_DAYS="${OFFSITE_MONTHLY_KEEP_DAYS:-1095}"
# โฟลเดอร์นี้ mount เข้า backend (docker-compose.prod.yml) ให้หน้าตรวจสอบระบบเตือนเมื่อส่งไม่สำเร็จ
STATUS_FILE="${OFFSITE_STATUS_FILE:-/var/backups/eqb-status/offsite.status}"
mkdir -p "$(dirname "$STATUS_FILE")"

trap 'echo "[$(date -Is)] ล้มเหลว" >&2; echo "FAILED $(date -Is)" > "$STATUS_FILE"' ERR

echo "[$(date -Is)] ส่งไฟล์ใหม่ขึ้น $REMOTE"
# copy = ส่งเฉพาะไฟล์ที่ยังไม่มีบน Drive ไม่ลบอะไรที่ปลายทาง (ฝั่งเครื่องเก็บ 7 วัน ฝั่ง Drive เก็บนานกว่า)
rclone copy "$BACKUP_DIR" "$REMOTE" --include 'db-*.dump' --include 'uploads-*.tar.gz' --transfers 2

# ตรวจว่าไฟล์บน Drive ถอดรหัสแล้วตรงกับต้นฉบับจริง (เทียบ checksum ผ่าน crypt) ไม่ใช่แค่ส่งผ่าน
echo "[$(date -Is)] ตรวจ checksum"
rclone cryptcheck "$BACKUP_DIR" "$REMOTE" --one-way --include 'db-*.dump' --include 'uploads-*.tar.gz'

# รายเดือน = ไฟล์ของวันที่ 1 (ชื่อ db-YYYYMM01-HHMMSS.dump) — copy ซ้ำไม่ส่งใหม่ถ้ามีแล้ว
echo "[$(date -Is)] ส่ง backup วันที่ 1 ของเดือนขึ้น $MONTHLY_REMOTE"
rclone mkdir "$MONTHLY_REMOTE"  # ยังไม่ถึงวันที่ 1 = ไม่มีโฟลเดอร์ แล้ว delete ด้านล่างล้ม
rclone copy "$BACKUP_DIR" "$MONTHLY_REMOTE" --include 'db-??????01-*.dump' --include 'uploads-??????01-*.tar.gz'

echo "[$(date -Is)] ลบไฟล์บน Drive ที่เก่ากว่า $KEEP_DAYS วัน / รายเดือนเก่ากว่า $MONTHLY_KEEP_DAYS วัน (ลบจริง ไม่เข้าถังขยะ)"
rclone delete "$REMOTE" --min-age "${KEEP_DAYS}d" --drive-use-trash=false
rclone delete "$MONTHLY_REMOTE" --min-age "${MONTHLY_KEEP_DAYS}d" --drive-use-trash=false

echo "OK $(date -Is) $(rclone lsf "$REMOTE" | wc -l) files" > "$STATUS_FILE"
echo "[$(date -Is)] เสร็จ — บน Drive มี $(rclone lsf "$REMOTE" | wc -l) ไฟล์"
