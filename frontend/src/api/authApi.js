import { api } from './axiosInstance.js'

export const authApi = {
  register: (data) => api.post('/auth/register', data).then((r) => r.data),
  verifyEmail: (token) => api.post('/auth/verify-email', { token }).then((r) => r.data),
  login: (email, password) => api.post('/auth/login', { email, password }).then((r) => r.data),
  refresh: (refresh_token) => api.post('/auth/refresh', { refresh_token }).then((r) => r.data),
  forgotPassword: (email) => api.post('/auth/forgot-password', { email }).then((r) => r.data),
  resetPassword: (token, new_password) =>
    api.post('/auth/reset-password', { token, new_password }).then((r) => r.data),
}
