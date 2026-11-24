import { api } from './axiosInstance.js'

export const authApi = {
  register: (data) => api.post('/auth/register', data).then((r) => r.data),
  verifyEmail: (token) => api.post('/auth/verify-email', { token }).then((r) => r.data),
  // แก้อีเมลที่พิมพ์ผิด/ส่งลิงก์ยืนยันใหม่ — เฉพาะบัญชีที่ยังไม่ยืนยัน (16 พ.ย. 69)
  resendVerification: (identifier, password, new_email) =>
    api.post('/auth/resend-verification', { identifier, password, new_email: new_email || null }).then((r) => r.data),
  login: (identifier, password) => api.post('/auth/login', { identifier, password }).then((r) => r.data),
  refresh: (refresh_token) => api.post('/auth/refresh', { refresh_token }).then((r) => r.data),
  forgotPassword: (email) => api.post('/auth/forgot-password', { email }).then((r) => r.data),
  resetPassword: (token, new_password) =>
    api.post('/auth/reset-password', { token, new_password }).then((r) => r.data),
  // พรีวิวปีการศึกษา/ชั้นปีจากรหัสนักศึกษา (เฟส 10) — public, โชว์ใต้ช่องรหัสนักศึกษาตอนสมัคร
  // กดรับทราบ Patch Note — จำในบัญชี ไม่ใช่ในเบราว์เซอร์
  markPatchSeen: (version) => api.post('/users/me/patch-seen', { version }),
  studyYearPreview: (student_id, study_years = 4) =>
    api.get('/auth/study-year-preview', { params: { student_id, study_years } }).then((r) => r.data),
}
