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

// Refresh token เมื่อได้ 401
api.interceptors.response.use(
  (res) => res,
  async (error) => {
    await unwrapBlobError(error)
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
          window.location.href = '/login'
        }
      }
    }
    return Promise.reject(error)
  },
)
