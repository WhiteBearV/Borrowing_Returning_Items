import { api } from './axiosInstance.js'

// ป้ายอัตราค่าปรับคืนเกินกำหนดรายรุ่น (23 พ.ย. 69) — ดู: เจ้าหน้าที่ · สร้าง/แก้/ลบ: ผู้ดูแลสูงสุด
export const fineRateApi = {
  list: () => api.get('/fine-rates').then((r) => r.data),
  create: (data) => api.post('/fine-rates', data).then((r) => r.data),
  update: (id, data) => api.patch(`/fine-rates/${id}`, data).then((r) => r.data),
  remove: (id) => api.delete(`/fine-rates/${id}`),
}
