import { api } from './axiosInstance.js'

export const changeRequestApi = {
  create: (data) => api.post('/change-requests', data).then((r) => r.data),
  list: (params) => api.get('/change-requests', { params }).then((r) => r.data),
  approve: (id, decision_note) =>
    api.patch(`/change-requests/${id}/approve`, { decision_note }).then((r) => r.data),
  reject: (id, decision_note) =>
    api.patch(`/change-requests/${id}/reject`, { decision_note }).then((r) => r.data),
  systemCheck: () => api.get('/change-requests/system-check').then((r) => r.data),
  // วัดการเชื่อมต่อหน้าบ้าน↔หลังบ้านจากเบราว์เซอร์จริง: เวลาไป-กลับ (ms) + เวลาที่เซิร์ฟเวอร์ใช้ (header X-Process-Time)
  // ส่วนต่าง = เวลาที่เสียระหว่างทาง (เครือข่าย/nginx) — /health แตะฐานข้อมูลจริงด้วย จึงวัดครบทั้งเส้น
  ping: async () => {
    const started = performance.now()
    const r = await api.get('/health')
    return { total: performance.now() - started, server: Number(r.headers['x-process-time']) || 0 }
  },
}
