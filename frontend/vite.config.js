import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
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
