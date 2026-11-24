import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'node:fs'
import http from 'node:http'

// https บน Dev — มือถือเปิดกล้องสแกน QR ได้เฉพาะ https ที่เชื่อถือ · สร้างด้วย ../gen-lan-ca.sh <ip> certs/dev
// ไม่มีไฟล์ = http เหมือนเดิม
const CERT_DIR = new URL('../certs/dev/', import.meta.url)
const hasCert = fs.existsSync(new URL('fullchain.pem', CERT_DIR))

// เสิร์ฟใบรับรองหลัก (ไม่มีกุญแจ) ที่ /ca.crt ให้หน้า /install-cert ดาวน์โหลด — บน Prod nginx ทำหน้าที่นี้
const serveCaCert = {
  name: 'serve-ca-cert',
  configureServer(server) {
    server.middlewares.use('/ca.crt', (_req, res) => {
      const file = new URL('ca.crt', CERT_DIR)
      if (!fs.existsSync(file)) { res.statusCode = 404; res.end(); return }
      res.setHeader('Content-Type', 'application/x-x509-ca-cert')
      res.setHeader('Content-Disposition', 'attachment; filename="cdti-borrow-ca.crt"')
      res.end(fs.readFileSync(file))
    })
  },
}

// พิมพ์ IP เปล่า ๆ เบราว์เซอร์จะเข้า http เสมอ แต่ Vite เปิด https พอร์ตเดียว รับ http ที่พอร์ตเดียวกันไม่ได้
// → เปิด http :5174 ไว้ redirect ไป https :5173 (Prod ไม่ต้อง: nginx :80 redirect ไป :443 อยู่แล้ว)
// ponytail: ไม่ดัก TLS บนพอร์ตเดียวกัน ซับซ้อนเกินไปสำหรับเครื่อง Dev
const httpRedirect = {
  name: 'http-redirect',
  configureServer(server) {
    if (!hasCert) return
    const port = server.config.server.port ?? 5173
    http.createServer((req, res) => {
      const host = (req.headers.host || 'localhost').replace(/:\d+$/, '')
      res.writeHead(301, { Location: `https://${host}:${port}${req.url}` })
      res.end()
    }).on('error', () => {}).listen(5174, '0.0.0.0')
  },
}

export default defineConfig({
  plugins: [react(), serveCaCert, httpRedirect],
  server: {
    port: 5173,
    https: hasCert ? {
      cert: fs.readFileSync(new URL('fullchain.pem', CERT_DIR)),
      key: fs.readFileSync(new URL('privkey.pem', CERT_DIR)),
    } : undefined,
    host: true, // ฟังทุก interface ให้มือถือ/เครื่องอื่นใน LAN เข้าถึงได้ — IP เครื่องไหนก็ได้ ไม่ต้องตั้งเอง
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        // ใส่ X-Forwarded-Host/-Proto ให้ backend รู้ IP/host จริงที่ browser ใช้เข้ามา (เช่น มือถือสแกน
        // QR ผ่าน LAN IP) — ใช้สร้าง URL ของ QR code ให้ตรงเครื่องเสมอ ไม่ต้องแก้ FRONTEND_URL ใน .env เอง
        xfwd: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
