#!/bin/sh
# สร้างใบรับรองสำหรับประทับตราดิจิทัลบนใบยืม/ใบคืน PDF (E-sign) — รันครั้งเดียวบน VM
#
#   ./gen-signing-cert.sh
#
# ได้ certs/signing/cert.pem + key.pem (โฟลเดอร์ certs/ อยู่ใน .gitignore — ห้าม commit key เด็ดขาด)
# docker-compose.prod.yml mount โฟลเดอร์นี้เข้า backend แบบอ่านอย่างเดียว · key หาย = ตราใหม่ใช้ key ใหม่ได้
# แต่ PDF เก่ายังตรวจได้ด้วยใบรับรองที่ฝังอยู่ในไฟล์ · มีใบรับรององค์กรเมื่อไหร่ วางทับสองไฟล์นี้แล้วรีสตาร์ต backend
set -e
mkdir -p certs/signing
if [ -f certs/signing/key.pem ]; then
  echo "มี certs/signing/key.pem อยู่แล้ว — ไม่สร้างทับ (ลบเองก่อนถ้าตั้งใจออกใหม่)"; exit 1
fi
openssl req -x509 -newkey rsa:3072 -sha256 -days 3650 -nodes \
  -keyout certs/signing/key.pem -out certs/signing/cert.pem \
  -subj "/O=CDTI/OU=Faculty of Digital Technology/CN=Equipment Borrowing System Document Seal" \
  -addext "keyUsage=critical,digitalSignature,nonRepudiation"
chmod 600 certs/signing/key.pem
echo "สร้างแล้ว: certs/signing/cert.pem, certs/signing/key.pem (อายุ 10 ปี)"
