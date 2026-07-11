import { api } from './axiosInstance.js'

export const equipmentApi = {
  list: (params) => api.get('/equipment', { params }).then((r) => r.data),
  get: (id) => api.get(`/equipment/${id}`).then((r) => r.data),
  create: (data) => api.post('/equipment', data).then((r) => r.data),
  update: (id, data) => api.patch(`/equipment/${id}`, data).then((r) => r.data),
  retire: (id, reason) => api.delete(`/equipment/${id}`, { params: reason ? { reason } : {} }),
  // ใบรับเข้าคลัง (receipt) / ใบปลดระวาง (disposal) เป็น PDF ตามช่วงวันที่
  stockDocument: (kind, date_from, date_to) =>
    api.get('/equipment/stock-document', { params: { kind, date_from, date_to }, responseType: 'blob' }).then((r) => r.data),
  deletePermanent: (id) => api.delete(`/equipment/${id}/permanent`),
  uploadImage: (file) => {
    const fd = new FormData()
    fd.append('file', file)
    // ต้อง override ให้ axios ตั้ง multipart boundary เอง (default ของ instance เป็น application/json)
    return api.post('/equipment/upload-image', fd, { headers: { 'Content-Type': 'multipart/form-data' } }).then((r) => r.data)
  },
  qrcode: (id) => api.get(`/equipment/${id}/qrcode`, { responseType: 'blob' }).then((r) => r.data),
  listCategories: () => api.get('/equipment-categories').then((r) => r.data),
  createCategory: (data) => api.post('/equipment-categories', data).then((r) => r.data),
  updateCategory: (id, data) => api.patch(`/equipment-categories/${id}`, data).then((r) => r.data),
  deleteCategory: (id) => api.delete(`/equipment-categories/${id}`),
}
