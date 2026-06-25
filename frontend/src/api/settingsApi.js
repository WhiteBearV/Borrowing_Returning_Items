import { api } from './axiosInstance.js'

export const settingsApi = {
  list: () => api.get('/settings').then((r) => r.data),
  update: (key, value) => api.patch(`/settings/${key}`, { value }).then((r) => r.data),
}
