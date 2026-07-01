import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuthContext } from '../context/AuthContext.jsx'

export default function LoginPage() {
  const { login } = useAuthContext()
  const navigate = useNavigate()
  const [role, setRole] = useState('student')
  const [form, setForm] = useState({ identifier: '', password: '' })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleTabChange = (newRole) => {
    setRole(newRole)
    setForm({ identifier: '', password: '' })
    setError('')
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const user = await login(form.identifier, form.password)
      navigate(user.role === 'admin' ? '/admin/dashboard' : '/dashboard', { replace: true })
    } catch (err) {
      setError(err.response?.data?.detail ?? 'เข้าสู่ระบบไม่สำเร็จ')
    } finally {
      setLoading(false)
    }
  }

  const isStudent = role === 'student'

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 px-4">
      <div className="w-full max-w-sm bg-white rounded-2xl shadow p-8">
        <h1 className="text-2xl font-bold text-gray-800 mb-1">เข้าสู่ระบบ</h1>
        <p className="text-sm text-gray-500 mb-5">ระบบยืม-คืนอุปกรณ์</p>

        {/* Tab */}
        <div className="flex rounded-lg bg-gray-100 p-1 mb-6">
          <button
            type="button"
            onClick={() => handleTabChange('student')}
            className={`flex-1 rounded-md py-1.5 text-sm font-medium transition-colors ${
              isStudent ? 'bg-white text-gray-800 shadow-sm' : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            นักศึกษา
          </button>
          <button
            type="button"
            onClick={() => handleTabChange('admin')}
            className={`flex-1 rounded-md py-1.5 text-sm font-medium transition-colors ${
              !isStudent ? 'bg-white text-gray-800 shadow-sm' : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            ผู้ดูแลระบบ
          </button>
        </div>

        {error && (
          <div className="mb-4 rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              {isStudent ? 'รหัสนักศึกษา' : 'ชื่อผู้ใช้งาน'}
            </label>
            <input
              key={role}
              type="text"
              required
              autoFocus
              autoComplete={isStudent ? 'username' : 'username'}
              value={form.identifier}
              onChange={(e) => setForm({ ...form, identifier: e.target.value })}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder={isStudent ? 'เช่น 6501234567' : 'เช่น JohnSmi'}
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">รหัสผ่าน</label>
            <input
              type="password"
              required
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-lg bg-blue-600 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {loading ? 'กำลังเข้าสู่ระบบ…' : 'เข้าสู่ระบบ'}
          </button>
        </form>

        {isStudent && (
          <p className="mt-6 text-center text-sm text-gray-500">
            ยังไม่มีบัญชี?{' '}
            <Link to="/register" className="text-blue-600 hover:underline font-medium">
              ลงทะเบียน
            </Link>
          </p>
        )}
        <p className="mt-2 text-center">
          <Link to="/forgot-password" className="text-xs text-gray-400 hover:text-gray-600">
            ลืมรหัสผ่าน?
          </Link>
        </p>
      </div>
    </div>
  )
}
