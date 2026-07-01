import { api } from './axiosInstance.js'

export const equipmentApi = {
  list: (params) => api.get('/equipment', { params }).then((r) => r.data),
  get: (id) => api.get(`/equipment/${id}`).then((r) => r.data),
  create: (data) => api.post('/equipment', data).then((r) => r.data),
  update: (id, data) => api.patch(`/equipment/${id}`, data).then((r) => r.data),
  retire: (id) => api.delete(`/equipment/${id}`),
  deletePermanent: (id) => api.delete(`/equipment/${id}/permanent`),
  qrcode: (id) => api.get(`/equipment/${id}/qrcode`, { responseType: 'blob' }).then((r) => r.data),
  listCategories: () => api.get('/equipment-categories').then((r) => r.data),
  createCategory: (data) => api.post('/equipment-categories', data).then((r) => r.data),
}
