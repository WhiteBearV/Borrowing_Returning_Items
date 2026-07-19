import { api } from './axiosInstance.js'

export const bundleApi = {
  list: () => api.get('/bundles').then((r) => r.data),
  create: (body) => api.post('/bundles', body).then((r) => r.data),
  update: (id, body) => api.patch(`/bundles/${id}`, body).then((r) => r.data),
  remove: (id) => api.delete(`/bundles/${id}`),
}
