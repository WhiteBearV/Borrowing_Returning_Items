import { api } from './axiosInstance.js'

export const usersApi = {
  list: (params) => api.get('/users', { params }).then((r) => r.data),
  updateStatus: (id, is_active) => api.patch(`/users/${id}/status`, { is_active }).then((r) => r.data),
}
