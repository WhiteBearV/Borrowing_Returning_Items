import { api } from './axiosInstance.js'

// รายชื่อนักศึกษาที่สาขารับรอง — ใช้ตรวจตอนสมัครใช้งาน (เฟส 9)
export const eligibleStudentsApi = {
  list: (params) => api.get('/eligible-students', { params }).then((r) => r.data),
  // รับ .xls (ของจริงจากสำนักทะเบียน) / .xlsx / .csv / .pdf — นำเข้าซ้ำได้ อัปเดตทับด้วยรหัสนักศึกษา
  import: (file) => {
    const fd = new FormData()
    fd.append('file', file)
    return api.post('/eligible-students/import', fd,
      { headers: { 'Content-Type': 'multipart/form-data' } }).then((r) => r.data)
  },
  remove: (id) => api.delete(`/eligible-students/${id}`),
}
