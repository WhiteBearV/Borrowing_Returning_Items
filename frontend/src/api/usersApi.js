import { api } from './axiosInstance.js'

export const usersApi = {
  list: (params) => api.get('/users', { params }).then((r) => r.data),
  create: (data) => api.post('/users', data).then((r) => r.data),
  updateStatus: (id, is_active) => api.patch(`/users/${id}/status`, { is_active }).then((r) => r.data),
  // เปลี่ยนระดับสิทธิ์ — เฉพาะผู้ดูแลระบบสูงสุด (backend กันด้วย require_superadmin)
  updateRole: (id, role, reason) => api.patch(`/users/${id}/role`, { role, reason }).then((r) => r.data),
  // อนุมัติ/ปฏิเสธผู้สมัครที่ไม่ตรงรายชื่อของสาขา (เฟส 9)
  updateApproval: (id, approve, note) =>
    api.patch(`/users/${id}/approval`, { approve, note }).then((r) => r.data),
  deleteUser: (id) => api.delete(`/users/${id}`),
}
