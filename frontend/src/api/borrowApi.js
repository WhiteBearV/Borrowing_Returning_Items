import { api } from './axiosInstance.js'

export const borrowApi = {
  create: (data) => api.post('/borrow-requests', data).then((r) => r.data),
  list: (params) => api.get('/borrow-requests', { params }).then((r) => r.data),
  get: (id) => api.get(`/borrow-requests/${id}`).then((r) => r.data),
  cancel: (id) => api.patch(`/borrow-requests/${id}/cancel`).then((r) => r.data),
  approve: (id) => api.patch(`/borrow-requests/${id}/approve`).then((r) => r.data),
  reject: (id, rejection_reason) =>
    api.patch(`/borrow-requests/${id}/reject`, { rejection_reason }).then((r) => r.data),
  renewItem: (id, itemId) =>
    api.post(`/borrow-requests/${id}/items/${itemId}/renew`).then((r) => r.data),
  returnItem: (id, itemId, data) =>
    api.post(`/borrow-requests/${id}/items/${itemId}/return`, data).then((r) => r.data),
  returnAll: (id) => api.post(`/borrow-requests/${id}/return-all`).then((r) => r.data),
  downloadPdf: (id) =>
    api.get(`/borrow-requests/${id}/pdf`, { responseType: 'blob' }).then((r) => r.data),
  downloadReturnPdf: (id) =>
    api.get(`/borrow-requests/${id}/return-pdf`, { responseType: 'blob' }).then((r) => r.data),
  previewPdf: (data) =>
    api.post('/borrow-requests/preview-pdf', data, { responseType: 'blob' }).then((r) => r.data),
  remind: (id) => api.post(`/borrow-requests/${id}/remind`).then((r) => r.data),
  deleteRequest: (id) => api.delete(`/borrow-requests/${id}`),
}
