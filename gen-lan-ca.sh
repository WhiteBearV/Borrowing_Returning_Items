#!/bin/sh
# ใบรับรอง https ที่มือถือ "เชื่อถือได้" สำหรับเว็บที่เข้าด้วย IP ในวง LAN (ยังไม่มีโดเมนจริง)
# แทน gen-self-signed-cert.sh — iPhone/iPad ไม่ยอมให้หน้าเว็บใช้กล้องถ้าใบรับรองไม่น่าเชื่อถือ
#
#   ./gen-lan-ca.sh 172.16.46.130            # Prod (VM)  → certs/
#   ./gen-lan-ca.sh 172.20.56.217 certs/dev  # Dev        → certs/dev/ (vite เปิด https เองเมื่อเจอไฟล์)
#
# ได้: <dir>/ca.crt (ใบรับรองหลักของคณะ — แจกให้มือถือติดตั้งผ่านหน้า /install-cert)
#      <dir>/fullchain.pem + <dir>/privkey.pem (ใบของเซิร์ฟเวอร์ ใช้กับ nginx/vite)
#      <dir>/ca.key (กุญแจของ CA — ห้ามแจก ห้าม commit · certs/ ถูก gitignore อยู่แล้ว)
#
# รันซ้ำเมื่อ IP เปลี่ยน: ใช้ CA เดิม (ไม่ต้องติดตั้งบนมือถือใหม่) ออกแค่ใบเซิร์ฟเวอร์ใบใหม่
# วันมีโดเมนจริง ให้เปลี่ยนไปใช้ certbot แทน ดู DEPLOY-PLAN.md
set -e

IP="${1:?ใช้งาน: ./gen-lan-ca.sh <ip> [โฟลเดอร์ปลายทาง]}"
DIR="${2:-certs}"
mkdir -p "$DIR"
umask 077
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

if [ ! -f "$DIR/ca.key" ]; then
  # CA อายุ 10 ปี — เปลี่ยน CA = ทุกเครื่องต้องติดตั้งใหม่ จึงตั้งยาว
  openssl req -x509 -newkey rsa:2048 -sha256 -days 3650 -nodes \
    -keyout "$DIR/ca.key" -out "$DIR/ca.crt" \
    -subj "/O=CDTI Equipment Borrowing/CN=CDTI Equipment Borrowing Local CA" \
    -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
    -addext "keyUsage=critical,keyCertSign,cRLSign"
  echo "สร้าง CA ใหม่แล้ว: $DIR/ca.crt (มือถือต้องติดตั้งใบนี้ครั้งเดียว)"
else
  echo "ใช้ CA เดิม: $DIR/ca.crt (มือถือที่ติดตั้งไว้แล้วไม่ต้องทำใหม่)"
fi

openssl req -newkey rsa:2048 -sha256 -nodes \
  -keyout "$DIR/privkey.pem" -out "$TMP/server.csr" -subj "/CN=${IP}"
# Apple บังคับ: อายุ ≤ 825 วัน + SAN + EKU serverAuth ไม่งั้น iOS ไม่เชื่อแม้ติดตั้ง CA แล้ว
cat > "$TMP/ext.cnf" <<EOF
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=IP:${IP}
EOF
openssl x509 -req -in "$TMP/server.csr" -CA "$DIR/ca.crt" -CAkey "$DIR/ca.key" -CAcreateserial \
  -out "$TMP/server.crt" -days 800 -sha256 -extfile "$TMP/ext.cnf"
cat "$TMP/server.crt" "$DIR/ca.crt" > "$DIR/fullchain.pem"
chmod 644 "$DIR/ca.crt" "$DIR/fullchain.pem"

openssl verify -CAfile "$DIR/ca.crt" "$TMP/server.crt"
echo "ใบเซิร์ฟเวอร์สำหรับ https://${IP} อายุ 800 วัน: $DIR/fullchain.pem, $DIR/privkey.pem"
echo "มือถือ: เปิด https://${IP}/install-cert (หรือ :5173 บน Dev) แล้วทำตามขั้นตอนบนหน้าเว็บ"
