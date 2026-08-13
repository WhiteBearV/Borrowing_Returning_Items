#!/usr/bin/env bash
# กู้ฐานข้อมูล + รูป จากไฟล์ที่ backup_db.sh สร้างไว้
#
#   bash backend/scripts/restore_db.sh /var/backups/equipment-borrow/db-20260802-020000.dump
#
# ถ้ามีไฟล์ uploads-<stamp>.tar.gz อยู่ข้าง ๆ กันจะกู้รูปให้ด้วยอัตโนมัติ
#
# มีสคริปต์นี้เพราะขั้นตอนกู้ที่เขียนเป็นคำสั่ง manual ในเอกสาร ไม่มีใครกล้ารันตอนของจริงหาย
# และ backup ที่ไม่เคยลอง restore เลย ไม่ต่างอะไรกับไม่มี backup — ซ้อมกู้ก่อนอย่างน้อย 1 ครั้ง
set -euo pipefail

DUMP="${1:?ใช้: bash restore_db.sh <ไฟล์ db-*.dump>}"
[[ -s "$DUMP" ]] || { echo "ไม่พบไฟล์ หรือไฟล์ว่างเปล่า: $DUMP" >&2; exit 1; }

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
COMPOSE=(docker compose -f "$REPO_ROOT/docker-compose.prod.yml")

set -a; source "$REPO_ROOT/.env"; set +a
: "${POSTGRES_USER:?ต้องมี POSTGRES_USER ใน .env}"
: "${POSTGRES_DB:?ต้องมี POSTGRES_DB ใน .env}"

echo "กำลังจะเขียนทับฐานข้อมูล '$POSTGRES_DB' ทั้งหมดด้วย $DUMP"
echo "ข้อมูลปัจจุบันจะหายถาวร"
read -r -p "พิมพ์ yes เพื่อยืนยัน: " confirm
[[ "$confirm" == "yes" ]] || { echo "ยกเลิก"; exit 1; }

# หยุด backend ก่อน ไม่งั้น connection ที่ค้างอยู่จะทำให้ DROP DATABASE ไม่ผ่าน
echo "[1/4] หยุด backend"
"${COMPOSE[@]}" stop backend

echo "[2/4] สร้างฐานข้อมูลใหม่"
"${COMPOSE[@]}" exec -T db psql -U "$POSTGRES_USER" -d postgres \
  -c "DROP DATABASE IF EXISTS \"$POSTGRES_DB\";" \
  -c "CREATE DATABASE \"$POSTGRES_DB\" OWNER \"$POSTGRES_USER\";"

echo "[3/4] กู้ข้อมูล"
"${COMPOSE[@]}" exec -T db pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner < "$DUMP"

# ไฟล์รูปคู่กัน ตั้งชื่อด้วย stamp เดียวกัน
UPLOADS="${DUMP/db-/uploads-}"
UPLOADS="${UPLOADS%.dump}.tar.gz"
if [[ -s "$UPLOADS" ]]; then
  echo "[4/4] กู้รูปจาก $UPLOADS"
  "${COMPOSE[@]}" start backend
  "${COMPOSE[@]}" exec -T backend tar xzf - -C /app < "$UPLOADS"
else
  echo "[4/4] ไม่พบ $UPLOADS — ข้ามการกู้รูป (path รูปใน DB จะชี้ไปไฟล์ที่ไม่มีอยู่)"
  "${COMPOSE[@]}" start backend
fi

# dump เก่ากว่าโค้ดปัจจุบันจะขาด migration ล่าสุด ต้องไล่ให้ทันก่อนใช้งาน
echo "ไล่ migration ให้ทันโค้ดปัจจุบัน"
"${COMPOSE[@]}" exec -T backend alembic upgrade head

echo "เสร็จ — ลองเข้าเว็บแล้ว login ดูว่าข้อมูลกลับมาครบ"
