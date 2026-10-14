import axios from 'axios'

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000',
  headers: { 'Content-Type': 'application/json' },
})

// ใส่ JWT header ทุก request
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// endpoint ที่โหลดไฟล์ (responseType: 'blob') พอ error กลับมาเป็น JSON ก็ยังถูกอ่านเป็น Blob
// ทำให้ err.response.data.detail อ่านไม่ได้ทุกจุดที่ใช้ blob — แกะกลับเป็น object ให้ที่เดียวจบ
async function unwrapBlobError(error) {
  const data = error.response?.data
  if (data instanceof Blob && data.type.includes('json')) {
    try {
      error.response.data = JSON.parse(await data.text())
    } catch {
      // เนื้อหาไม่ใช่ JSON จริง ปล่อยเป็น Blob เดิม ไม่ต้องทำอะไรเพิ่ม
    }
  }
  return error
}

const PUBLIC_PATHS = ['/login', '/register', '/verify-email', '/forgot-password', '/reset-password']
// ข้อความ validation ที่ผู้ใช้เจอบ่อย — ที่เหลือใช้ข้อความจาก backend ตามเดิม
const VALIDATION_TH = {
  string_too_short: 'กรอกข้อมูลสั้นเกินไปหรือเว้นว่าง',
  string_too_long: 'กรอกข้อมูลยาวเกินไป',
  missing: 'กรอกข้อมูลไม่ครบ',
}

// Refresh token เมื่อได้ 401
api.interceptors.response.use(
  (res) => res,
  async (error) => {
    await unwrapBlobError(error)
    // 422 ของ FastAPI ส่ง detail เป็น "อาร์เรย์ของ object" — 24 หน้าที่แสดง detail ตรง ๆ จะทำ React ล่มทั้งหน้า (หน้าขาว)
    // เจอจริง: ล็อกอินรหัสผ่านยาวเกิน 72 ตัว / บันทึกชื่อว่างในโปรไฟล์ (QA รอบ 5, R5-08) แปลงเป็นข้อความที่จุดเดียวตรงนี้
    const detail = error.response?.data?.detail
    if (Array.isArray(detail)) {
      error.response.data.detail = detail.map((d) => VALIDATION_TH[d?.type] ?? d?.msg ?? String(d)).join(', ')
    }
    const original = error.config
    if (error.response?.status === 401 && !original._retry) {
      original._retry = true
      const refresh = localStorage.getItem('refresh_token')
      if (refresh) {
        try {
          const { data } = await axios.post(
            `${api.defaults.baseURL}/auth/refresh`,
            { refresh_token: refresh },
          )
          localStorage.setItem('access_token', data.access_token)
          original.headers.Authorization = `Bearer ${data.access_token}`
          return api(original)
        } catch {
          localStorage.removeItem('access_token')
          localStorage.removeItem('refresh_token')
          // หน้าสาธารณะไม่ต้องเด้ง — เดิม session เก่าที่หมดอายุค้างในเบราว์เซอร์ทำให้ลิงก์รีเซ็ตรหัสผ่าน/ยืนยันอีเมล
          // จากอีเมลถูกพาไปหน้า login แทน (R5-01) หน้าที่ต้องล็อกอิน ProtectedRoute พาไปเองอยู่แล้ว
          if (!PUBLIC_PATHS.includes(window.location.pathname)) window.location.href = '/login'
        }
      }
    }
    return Promise.reject(error)
  },
)
