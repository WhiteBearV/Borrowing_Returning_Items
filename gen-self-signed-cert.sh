#!/bin/sh
# สร้าง self-signed TLS cert สำหรับ pilot บน LAN คณะ (ยังไม่มีโดเมนจริง)
# รันครั้งเดียวบน VM ก่อน docker compose -f docker-compose.prod.yml up
#
#   ./gen-self-signed-cert.sh 192.168.1.164
#
# ได้ไฟล์ certs/fullchain.pem + certs/privkey.pem (gitignore ไว้แล้ว ห้าม commit)
# วันมีโดเมนจริง ให้เปลี่ยนไปใช้ certbot ออก cert แทน ดู DEPLOY-PLAN.md
set -e

IP="${1:?ใช้งาน: ./gen-self-signed-cert.sh <ip-ของ-vm>}"
mkdir -p certs
openssl req -x509 -newkey rsa:2048 -sha256 -days 730 -nodes \
  -keyout certs/privkey.pem -out certs/fullchain.pem \
  -subj "/CN=${IP}" \
  -addext "subjectAltName=IP:${IP}"

echo "สร้าง cert แล้ว: certs/fullchain.pem, certs/privkey.pem (อายุ 2 ปี)"
echo "เบราว์เซอร์จะเตือน 'ไม่ปลอดภัย' ครั้งแรกที่เข้า https://${IP} — กด 'ขั้นสูง > ไปต่อ' ได้ปกติ (เข้ารหัสจริง แค่ไม่มี CA รับรอง)"
