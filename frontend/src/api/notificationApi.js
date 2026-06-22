import { api } from './axiosInstance.js'

export const notificationApi = {
  listMine: (params) => api.get('/notifications/me', { params }).then((r) => r.data),
  markRead: (id) => api.patch(`/notifications/${id}/read`).then((r) => r.data),
}
