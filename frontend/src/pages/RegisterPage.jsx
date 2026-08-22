import { useState } from 'react'
import { Link } from 'react-router-dom'
import { authApi } from '../api/authApi.js'

const MAJORS = [
  { value: 'comp_eng', label: 'วิศวกรรมคอมพิวเตอร์' },
  { value: 'digital_design', label: 'ออกแบบดิจิทัล' },
]

const TITLES = ['นาย', 'นาง', 'นางสาว']

export default function RegisterPage() {
  const [form, setForm] = useState({
    title: '',
    first_name: '',
    last_name: '',
    student_id: '',
    email: '',
    password: '',
    major: '',
  })
  const [error, setError] = useState('')
  const [success, setSuccess] = useState(false)
  const [loading, setLoading] = useState(false)

  const set = (field) => (e) => setForm({ ...form, [field]: e.target.value })

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await authApi.register({
        full_name: `${form.title}${form.first_name.trim()} ${form.last_name.trim()}`,
        student_id: form.student_id.trim(),
        email: form.email.trim(),
        password: form.password,
        major: form.major,
      })
      setSuccess(true)
    } catch (err) {
      // detail อาจเป็น string (HTTPException) หรือ array ของ Pydantic error object (validation error)
      const detail = err.response?.data?.detail
      setError(Array.isArray(detail) ? detail.map((d) => d.msg).join(', ') : (detail ?? 'ลงทะเบียนไม่สำเร็จ'))
    } finally {
      setLoading(false)
    }
  }

  if (success) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 px-4">
        <div className="w-full max-w-sm bg-white rounded-2xl shadow p-8 text-center">
          <div className="text-4xl mb-4">📧</div>
          <h2 className="text-xl font-light text-gray-800 mb-2">ตรวจสอบอีเมลของคุณ</h2>
          <p className="text-sm text-gray-500 mb-6">
            เราส่งลิงก์ยืนยันไปที่ <span className="font-medium text-gray-700">{form.email}</span> แล้ว
            กรุณากดลิงก์ในอีเมลก่อนเข้าสู่ระบบ
          </p>
          <Link to="/login" className="text-primary-600 hover:underline text-sm font-medium">
            กลับไปหน้าเข้าสู่ระบบ
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 px-4 py-12">
      <div className="w-full max-w-sm bg-white rounded-2xl shadow p-8">
        <h1 className="text-2xl font-light text-gray-800 mb-1">ลงทะเบียน</h1>
        <p className="text-sm text-gray-500 mb-6">ระบบยืม-คืนอุปกรณ์</p>

        {error && (
          <div className="mb-4 rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="flex gap-2">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                คำนำหน้า <span className="text-red-500">*</span>
              </label>
              <select
                required
                value={form.title}
                onChange={set('title')}
                className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 bg-white"
              >
                <option value="">—</option>
                {TITLES.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </div>
            <div className="flex-1">
              <label className="block text-sm font-medium text-gray-700 mb-1">
                ชื่อ <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                required
                autoFocus
                value={form.first_name}
                onChange={set('first_name')}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
                placeholder="ชื่อจริง"
              />
            </div>
            <div className="flex-1">
              <label className="block text-sm font-medium text-gray-700 mb-1">
                นามสกุล <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                required
                value={form.last_name}
                onChange={set('last_name')}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
                placeholder="นามสกุล"
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              รหัสนักศึกษา <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              required
              pattern="\d{10}"
              value={form.student_id}
              onChange={set('student_id')}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
              placeholder="65XXXXXXXX"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              อีเมล <span className="text-red-500">*</span>
            </label>
            <input
              type="email"
              required
              value={form.email}
              onChange={set('email')}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
              placeholder="email@cdti.ac.th"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              รหัสผ่าน <span className="text-red-500">*</span>
            </label>
            <input
              type="password"
              required
              minLength={8}
              value={form.password}
              onChange={set('password')}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
              placeholder="อย่างน้อย 8 ตัวอักษร"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              สาขา <span className="text-red-500">*</span>
            </label>
            <select
              required
              value={form.major}
              onChange={set('major')}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 bg-white"
            >
              <option value="">— เลือกสาขา —</option>
              {MAJORS.map((m) => (
                <option key={m.value} value={m.value}>{m.label}</option>
              ))}
            </select>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-full bg-primary-600 py-2 text-sm font-semibold text-white hover:bg-primary-700 disabled:opacity-50 transition-colors"
          >
            {loading ? 'กำลังลงทะเบียน…' : 'ลงทะเบียน'}
          </button>
        </form>

        <p className="mt-6 text-center text-sm text-gray-500">
          มีบัญชีแล้ว?{' '}
          <Link to="/login" className="text-primary-600 hover:underline font-medium">
            เข้าสู่ระบบ
          </Link>
        </p>
      </div>
    </div>
  )
}
