import { api } from './axiosInstance.js'

// ตรวจครุภัณฑ์รายห้องด้วย QR (16 พ.ย. 69) — เจ้าหน้าที่เท่านั้น
export const stocktakeApi = {
  locations: () => api.get('/stocktake/locations').then((r) => r.data),
  roomItems: (location) => api.get('/stocktake/locations/items', { params: { location } }).then((r) => r.data),
  roomQrPdf: (location) =>
    api.get('/stocktake/locations/qr.pdf', { params: location ? { location } : {}, responseType: 'blob' }).then((r) => r.data),
  rounds: (location) => api.get('/stocktake/rounds', { params: location ? { location } : {} }).then((r) => r.data),
  start: (location) => api.post('/stocktake/rounds', { location }).then((r) => r.data),
  get: (id) => api.get(`/stocktake/rounds/${id}`).then((r) => r.data),
  scan: (id, scanned) => api.post(`/stocktake/rounds/${id}/scan`, {
    equipment_id: scanned.equipmentId ?? null, code: scanned.code ?? null,
  }).then((r) => r.data),
  finish: (id, note) => api.post(`/stocktake/rounds/${id}/finish`, { note: note || null }).then((r) => r.data),
  setCondition: (id, itemId, condition, note) =>
    api.post(`/stocktake/rounds/${id}/items/${itemId}/condition`, { condition, note: note || null }).then((r) => r.data),
  undo: (id, itemId) => api.post(`/stocktake/rounds/${id}/items/${itemId}/undo`).then((r) => r.data),
  summaryPreview: () => api.get('/stocktake/summary-preview').then((r) => r.data),
  summaryXlsx: () => api.get('/stocktake/summary.xlsx', { responseType: 'blob' }).then((r) => r.data),
  summaryPdf: () => api.get('/stocktake/summary.pdf', { responseType: 'blob' }).then((r) => r.data),
  reportPreview: (id) => api.get(`/stocktake/rounds/${id}/report-preview`).then((r) => r.data),
  reportXlsx: (id) => api.get(`/stocktake/rounds/${id}/report.xlsx`, { responseType: 'blob' }).then((r) => r.data),
  reportPdf: (id) => api.get(`/stocktake/rounds/${id}/report.pdf`, { responseType: 'blob' }).then((r) => r.data),
}
