import { api } from './axiosInstance.js'

export const changeRequestApi = {
  create: (data) => api.post('/change-requests', data).then((r) => r.data),
  list: (params) => api.get('/change-requests', { params }).then((r) => r.data),
  approve: (id, decision_note) =>
    api.patch(`/change-requests/${id}/approve`, { decision_note }).then((r) => r.data),
  reject: (id, decision_note) =>
    api.patch(`/change-requests/${id}/reject`, { decision_note }).then((r) => r.data),
  systemCheck: () => api.get('/change-requests/system-check').then((r) => r.data),
}
