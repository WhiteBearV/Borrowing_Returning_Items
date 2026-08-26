import { api } from './axiosInstance.js'

export const equipmentApi = {
  list: (params) => api.get('/equipment', { params }).then((r) => r.data),
  get: (id) => api.get(`/equipment/${id}`).then((r) => r.data),
  // อุปกรณ์รุ่นเดียวกันหลายหน่วย (ครุภัณฑ์/วัสดุ) ยุบเป็นการ์ดเดียว — หน้ายืมของนักศึกษาใช้ตัวนี้
  listGrouped: (params) => api.get('/equipment/grouped', { params }).then((r) => r.data),
  getGrouped: (id) => api.get(`/equipment/grouped/${id}`).then((r) => r.data),
  create: (data) => api.post('/equipment', data).then((r) => r.data),
  update: (id, data) => api.patch(`/equipment/${id}`, data).then((r) => r.data),
  retire: (id, reason) => api.delete(`/equipment/${id}`, { params: reason ? { reason } : {} }),
  // ปลดระวางหลายรายการพร้อมกันแบบ best-effort — เหตุผลเดียวกันใช้กับทุกชิ้น คืน { retired: [id], failed: [{equipment_id, reason}] }
  bulkRetire: (equipment_ids, reason) => api.post('/equipment/bulk-retire', { equipment_ids, reason }).then((r) => r.data),
  // แยกวัสดุ (material) ก้อนเดียวที่ quantity_total > 1 เป็นรายชิ้นคนละรหัส — คืนหน่วยใหม่ทั้งหมด
  split: (id) => api.post(`/equipment/${id}/split`).then((r) => r.data),
  // เติมของเข้าคลัง (ซื้อเพิ่ม) — พิมพ์แค่จำนวนที่เพิ่ม ระบบตัดสินเองว่าจะบวกเข้าแถวเดิม (ก้อน/สิ้นเปลือง)
  // หรือสร้างแถวใหม่แยกรหัส (ครุภัณฑ์/วัสดุที่แยกรายชิ้นแล้ว)
  restock: (id, count) => api.post(`/equipment/${id}/restock`, { count }).then((r) => r.data),
  // บันทึกว่าตรวจนับอุปกรณ์ชิ้นนี้ทางกายภาพแล้ว — note/photo_urls ไม่บังคับ
  audit: (id, note, photo_urls) => api.post(`/equipment/${id}/audit`, { note, photo_urls }).then((r) => r.data),
  // ปรับยอดคงเหลือให้ตรงกับการนับจริง (SET ตรง ๆ ต่างจาก restock ที่บวกเพิ่ม) — เหตุผลบังคับ, รูปไม่บังคับ
  adjustStock: (id, newAvailable, reason, photoUrls) =>
    api.post(`/equipment/${id}/adjust-stock`, { new_available: newAvailable, reason, photo_urls: photoUrls }).then((r) => r.data),
  // ใบรับเข้าคลัง (receipt) / ใบปลดระวาง (disposal) เป็น PDF ตามช่วงวันที่
  stockDocument: (kind, date_from, date_to) =>
    api.get('/equipment/stock-document', { params: { kind, date_from, date_to }, responseType: 'blob' }).then((r) => r.data),
  // บันทึกขออนุมัติซ่อมแซมครุภัณฑ์ — ของที่สถานะชำรุด/กำลังซ่อมทั้งหมด
  repairDocument: () =>
    api.get('/equipment/repair-document', { responseType: 'blob' }).then((r) => r.data),
  deletePermanent: (id) => api.delete(`/equipment/${id}/permanent`),
  // ลบถาวรหลายรายการพร้อมกันแบบ best-effort — คืน { deleted: [id], failed: [{equipment_id, reason}] }
  bulkDelete: (equipment_ids) => api.post('/equipment/bulk-delete', { equipment_ids }).then((r) => r.data),
  // แก้ไขฟิลด์ปลอดภัยของหลายหน่วยพร้อมกัน (all-or-nothing) — คืน { updated: [...] }
  bulkUpdate: (equipment_ids, update) => api.patch('/equipment/bulk-update', { equipment_ids, update }).then((r) => r.data),
  // นำเข้าจากไฟล์ทะเบียน (Excel): อ่านไฟล์ → ดูร่าง → ยืนยัน
  importPreview: (file) => {
    const fd = new FormData()
    fd.append('file', file)
    return api.post('/equipment/import/preview', fd, { headers: { 'Content-Type': 'multipart/form-data' } }).then((r) => r.data)
  },
  // body = ร่างที่แอดมินตรวจ/แก้แล้ว: { filename, rows: [{ code, action, name, location, status, category, reason }] }
  importCommit: (importId, body) =>
    api.post(`/equipment/import/${importId}/commit`, body).then((r) => r.data),
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
