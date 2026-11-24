import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuthContext } from '../context/AuthContext.jsx'
import { authApi } from '../api/authApi.js'
import { isStaff } from '../utils/role.js'

export default function LoginPage() {
  const { login } = useAuthContext()
  const navigate = useNavigate()
  const location = useLocation()
  const [form, setForm] = useState({ identifier: '', password: '' })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [showPw, setShowPw] = useState(false)
  // บัญชีที่ยังไม่ยืนยันอีเมล — ให้ส่งลิงก์ใหม่/แก้อีเมลที่พิมพ์ผิดได้เอง (feedback 16 พ.ย. 69)
  const [unverified, setUnverified] = useState(false)
  const [newEmail, setNewEmail] = useState('')
  const [resendMsg, setResendMsg] = useState('')
  const [resending, setResending] = useState(false)

  const handleResend = async () => {
    setResendMsg('')
    setResending(true)
    try {
      const res = await authApi.resendVerification(form.identifier, form.password, newEmail.trim())
      setResendMsg(`ส่งลิงก์ยืนยันไปที่ ${res.email} แล้ว — เปิดอีเมลนั้นแล้วกดลิงก์ (ลิงก์เก่าใช้ไม่ได้แล้ว)`)
      setNewEmail('')
    } catch (err) {
      setResendMsg(err.response?.data?.detail ?? 'ส่งไม่สำเร็จ')
    } finally {
      setResending(false)
    }
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setUnverified(false)
    setResendMsg('')
    setLoading(true)
    try {
      const user = await login(form.identifier, form.password)
      // มาจากลิงก์ที่ต้องล็อกอินก่อน (เช่น สแกน QR อุปกรณ์) — ProtectedRoute ฝาก path เดิมไว้ใน state.from
      // กลับไปหน้านั้นแทนหน้าแรก ไม่งั้นต้องเข้าไปหาอุปกรณ์ที่สแกนมาเองอีกรอบ
      const from = location.state?.from
      const dest = from ? `${from.pathname}${from.search ?? ''}` : (isStaff(user) ? '/admin/dashboard' : '/dashboard')
      navigate(dest, { replace: true })
    } catch (err) {
      const detail = err.response?.data?.detail
      if (err.response?.status === 403 && String(detail).startsWith('Email not verified')) {
        setUnverified(true)
        setError('ยังไม่ได้ยืนยันอีเมล — เปิดอีเมลที่ใช้สมัครแล้วกดลิงก์ยืนยัน')
      } else {
        setError(detail ?? 'เข้าสู่ระบบไม่สำเร็จ')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 px-4">
      <div className="w-full max-w-sm bg-white rounded-2xl shadow p-8">
        <h1 className="text-2xl font-light text-gray-800 mb-1">เข้าสู่ระบบ</h1>
        <p className="text-sm text-gray-500 mb-5">ระบบยืม-คืนอุปกรณ์</p>

        {error && (
          <div className="mb-4 rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {unverified && (
          <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 space-y-2">
            <p className="font-medium">ไม่ได้รับอีเมล หรือพิมพ์อีเมลผิดตอนสมัคร?</p>
            <p className="text-xs">ใส่อีเมลที่ถูกต้อง (เว้นว่าง = ส่งไปอีเมลเดิมอีกครั้ง) แล้วกดส่งลิงก์ใหม่</p>
            <input
              type="email"
              value={newEmail}
              onChange={(e) => setNewEmail(e.target.value)}
              placeholder="อีเมลที่ถูกต้อง @cdti.ac.th"
              className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
            />
            <button
              type="button"
              onClick={handleResend}
              disabled={resending}
              className="w-full rounded-full border border-amber-400 bg-white py-1.5 text-sm font-medium hover:bg-amber-100 disabled:opacity-50"
            >
              {resending ? 'กำลังส่ง…' : 'ส่งลิงก์ยืนยันใหม่'}
            </button>
            {resendMsg && <p className="text-xs">{resendMsg}</p>}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              รหัสประจำตัว
            </label>
            <input
              type="text"
              required
              autoFocus
              autoComplete="username"
              value={form.identifier}
              onChange={(e) => setForm({ ...form, identifier: e.target.value })}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
              placeholder="รหัสนักศึกษา หรือ ชื่อผู้ใช้งาน"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">รหัสผ่าน</label>
            <div className="relative">
              <input
                type={showPw ? 'text' : 'password'}
                required
                maxLength={72}
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 pr-10 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
              />
              <button
                type="button"
                aria-label="กดค้างเพื่อแสดงรหัสผ่าน"
                onMouseDown={() => setShowPw(true)}
                onMouseUp={() => setShowPw(false)}
                onMouseLeave={() => setShowPw(false)}
                onTouchStart={() => setShowPw(true)}
                onTouchEnd={() => setShowPw(false)}
                className="absolute inset-y-0 right-0 px-3 text-gray-400 hover:text-gray-600 select-none"
              >
                {showPw ? '🙈' : '👁'}
              </button>
            </div>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-full bg-primary-600 py-2 text-sm font-semibold text-white hover:bg-primary-700 disabled:opacity-50 transition-colors"
          >
            {loading ? 'กำลังเข้าสู่ระบบ…' : 'เข้าสู่ระบบ'}
          </button>
        </form>

        <p className="mt-6 text-center text-sm text-gray-500">
          ยังไม่มีบัญชี?{' '}
          <Link to="/register" className="text-primary-600 hover:underline font-medium">
            ลงทะเบียน
          </Link>
        </p>
        <p className="mt-2 text-center">
          <Link to="/forgot-password" className="text-xs text-gray-400 hover:text-gray-600">
            ลืมรหัสผ่าน?
          </Link>
          <span className="mx-2 text-xs text-gray-300">·</span>
          <a href="/manual/borrower.html" target="_blank" rel="noopener" className="text-xs text-gray-400 hover:text-gray-600">
            คู่มือการใช้งาน
          </a>
        </p>
      </div>
    </div>
  )
}
