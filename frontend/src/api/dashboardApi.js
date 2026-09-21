import { api } from './axiosInstance.js'

export const dashboardApi = {
  summary: () => api.get('/dashboard/summary').then((r) => r.data),
  // สถิติความคุ้มค่ารายหน่วย — item_type ว่าง = ครุภัณฑ์ + วัสดุใช้ซ้ำ (ของที่ได้คืน), 'all' = ทุกประเภท
  // from/to (YYYY-MM-DD) ต้องมาคู่กัน ไม่ส่ง = สะสมตั้งแต่เข้าระบบ
  utilization: (item_type, from, to) =>
    api.get('/dashboard/utilization', {
      params: { item_type: item_type || undefined, date_from: from || undefined, date_to: to || undefined },
    }).then((r) => r.data),
  // ค่าปรับทั้งหมด + ยอดรวมแยกสถานะ — กรอง/เรียงฝั่ง client เหมือนหน้าความคุ้มค่า
  fines: () => api.get('/dashboard/fines').then((r) => r.data),
  finesCsv: () => api.get('/dashboard/fines/export', { responseType: 'blob' }).then((r) => r.data),
}
