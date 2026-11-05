import { api } from './axiosInstance.js'

export const feedbackApi = {
  // แจ้งปัญหา/ข้อเสนอแนะ + รูปหลักฐาน ≤3 รูป → อีเมลถึงผู้พัฒนา (backend: routers/feedback.py)
  send: ({ kind, detail, files }) => {
    const fd = new FormData()
    fd.append('kind', kind)
    fd.append('detail', detail)
    fd.append('page_url', window.location.href)
    files.forEach((f) => fd.append('files', f))
    return api.post('/feedback', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
  },
}
