import { api } from './axiosInstance.js'

export const borrowApi = {
  create: (data) => api.post('/borrow-requests', data).then((r) => r.data),
  list: (params) => api.get('/borrow-requests', { params }).then((r) => r.data),
  get: (id) => api.get(`/borrow-requests/${id}`).then((r) => r.data),
  // ยกเลิกคำขอต้องมีเหตุผลเสมอ (8 ก.ย. 69) — backend 400 ถ้าเว้นว่าง
  cancel: (id, reason) => api.patch(`/borrow-requests/${id}/cancel`, { reason }).then((r) => r.data),
  // items = [{ item_id, approved, due_date, rejection_reason }] — ไม่ส่ง = อนุมัติทั้งใบ
  // pickup = { pickup_at, pickup_location, pickup_note } — ไม่ส่ง/เป็น null = ไม่ได้นัดรับล่วงหน้า
  approve: (id, items, pickup) =>
    api.patch(`/borrow-requests/${id}/approve`,
      items || pickup ? { ...(items ? { items } : {}), ...(pickup ?? {}) } : undefined,
    ).then((r) => r.data),
  reject: (id, rejection_reason) =>
    api.patch(`/borrow-requests/${id}/reject`, { rejection_reason }).then((r) => r.data),
  // นักศึกษายื่นคำขอต่อเวลา (เลือกวันที่+เหตุผลเอง) — ยังไม่ใช่การต่อเวลาจริง แค่แจ้ง admin ให้มาอนุมัติ
  renewRequest: (id, itemId, requested_date, reason) =>
    api.post(`/borrow-requests/${id}/items/${itemId}/renew-request`, { requested_date, reason }).then((r) => r.data),
  renewApprove: (id, itemId) =>
    api.post(`/borrow-requests/${id}/items/${itemId}/renew-approve`).then((r) => r.data),
  renewReject: (id, itemId, rejection_reason) =>
    api.post(`/borrow-requests/${id}/items/${itemId}/renew-reject`, { rejection_reason }).then((r) => r.data),
  // นัดวัน-เวลา-สถานที่บังคับตั้งแต่เฟส 4 — แอดมินต้องรู้ล่วงหน้าว่าใครจะมาคืนอะไรกี่โมง
  requestReturn: (id, itemIds, returnAppointAt, returnAppointLocation) =>
    api.post(`/borrow-requests/${id}/request-return`, {
      item_ids: itemIds,
      return_appoint_at: returnAppointAt,
      return_appoint_location: returnAppointLocation,
    }).then((r) => r.data),
  // อัปโหลดใบยืมที่เซ็นแล้ว (PDF/รูปถ่าย) — ไฟล์ล่าสุดไฟล์เดียวต่อคำขอ อัปใหม่ = ทับของเดิม
  uploadSignedForm: (id, file) => {
    const fd = new FormData()
    fd.append('file', file)
    // ต้อง override ให้ axios ตั้ง multipart boundary เอง (default ของ instance เป็น application/json)
    return api.post(`/borrow-requests/${id}/signed-form`, fd,
      { headers: { 'Content-Type': 'multipart/form-data' } }).then((r) => r.data)
  },
  // ไฟล์ใบเซ็นไม่มี URL สาธารณะแล้ว (เฟส 7) — ต้องโหลดผ่าน endpoint ที่ตรวจสิทธิ์แล้วเปิดจาก blob
  downloadSignedForm: (id) =>
    api.get(`/borrow-requests/${id}/signed-form`, { responseType: 'blob' }).then((r) => r.data),
  // เซ็นบนหน้าจอ (เฟส 11) — blob จาก canvas ทั้งคู่ ลายเซ็นเจ้าหน้าที่เว้นได้
  handover: (id, borrowerBlob, staffBlob) => {
    const fd = new FormData()
    fd.append('borrower_signature', borrowerBlob, 'borrower.png')
    if (staffBlob) fd.append('staff_signature', staffBlob, 'staff.png')
    return api.post(`/borrow-requests/${id}/handover`, fd,
      { headers: { 'Content-Type': 'multipart/form-data' } }).then((r) => r.data)
  },
  signReturn: (id, borrowerBlob, staffBlob) => {
    const fd = new FormData()
    fd.append('borrower_signature', borrowerBlob, 'borrower.png')
    if (staffBlob) fd.append('staff_signature', staffBlob, 'staff.png')
    return api.post(`/borrow-requests/${id}/sign-return`, fd,
      { headers: { 'Content-Type': 'multipart/form-data' } }).then((r) => r.data)
  },
  // ลายเซ็นไม่มี URL สาธารณะ — โหลดผ่าน endpoint ที่ตรวจสิทธิ์แล้วเปิดจาก blob (เหมือนใบยืมที่เซ็นแล้ว)
  downloadSignature: (id, kind) =>
    api.get(`/borrow-requests/${id}/signature/${kind}`, { responseType: 'blob' }).then((r) => r.data),
  returnItem: (id, itemId, data) =>
    api.post(`/borrow-requests/${id}/items/${itemId}/return`, data).then((r) => r.data),
  returnAll: (id) => api.post(`/borrow-requests/${id}/return-all`).then((r) => r.data),
  // ค่าปรับ (เฟส 6) — แก้ยอด/บันทึกชำระ = เจ้าหน้าที่ · ยกเว้น = superadmin เท่านั้น
  updateFine: (id, itemId, data) =>
    api.patch(`/borrow-requests/${id}/items/${itemId}/fine`, data).then((r) => r.data),
  payFine: (id, itemId) =>
    api.patch(`/borrow-requests/${id}/items/${itemId}/fine/pay`).then((r) => r.data),
  waiveFine: (id, itemId, reason) =>
    api.patch(`/borrow-requests/${id}/items/${itemId}/fine/waive`, { reason }).then((r) => r.data),
  downloadPdf: (id) =>
    api.get(`/borrow-requests/${id}/pdf`, { responseType: 'blob' }).then((r) => r.data),
  downloadReturnPdf: (id) =>
    api.get(`/borrow-requests/${id}/return-pdf`, { responseType: 'blob' }).then((r) => r.data),
  previewPdf: (data) =>
    api.post('/borrow-requests/preview-pdf', data, { responseType: 'blob' }).then((r) => r.data),
  remind: (id) => api.post(`/borrow-requests/${id}/remind`).then((r) => r.data),
  deleteRequest: (id) => api.delete(`/borrow-requests/${id}`),
}
