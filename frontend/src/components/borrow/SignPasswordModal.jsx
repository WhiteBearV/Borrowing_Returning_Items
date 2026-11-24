import { useState } from 'react'
import { createPortal } from 'react-dom'

/** ลงชื่ออิเล็กทรอนิกส์ด้วยรหัสผ่านของตัวเอง (23 พ.ย. 69) — ใช้ตอนยื่นคำขอ และลงชื่อใบยืม/ใบคืนจากหน้า "การยืมของฉัน"
 *  onSign(password) ต้อง throw เมื่อไม่สำเร็จ (รหัสผิด = 400) ข้อความจาก backend จะขึ้นในกล่องนี้ */
export default function SignPasswordModal({ title, children, confirmLabel = 'ลงชื่อ', onSign, onClose }) {
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const submit = async (e) => {
    e.preventDefault()
    if (!password) return
    setBusy(true)
    setError('')
    try {
      await onSign(password)
    } catch (err) {
      const detail = err.response?.data?.detail ?? ''
      setError(/incorrect password/i.test(detail) ? 'รหัสผ่านไม่ถูกต้อง' : (detail || 'ลงชื่อไม่สำเร็จ'))
      setBusy(false)
    }
  }

  return createPortal(
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50 px-4">
      <form onSubmit={submit} className="bg-white rounded-2xl p-6 w-full max-w-md shadow-xl space-y-4">
        <h2 className="font-bold text-gray-800 text-lg">{title}</h2>
        {children}
        <label className="block text-sm">
          <span className="text-gray-700">รหัสผ่านของคุณ (ใช้ลงชื่อแทนลายมือชื่อ)</span>
          <input type="password" autoFocus autoComplete="current-password" value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary-500" />
        </label>
        {error && <p className="text-sm text-red-600">{error}</p>}
        <div className="flex gap-3 pt-1">
          <button type="button" onClick={onClose} disabled={busy}
            className="flex-1 rounded-full border border-gray-200 py-2 text-sm text-gray-600 hover:bg-gray-50">
            ยกเลิก
          </button>
          <button type="submit" disabled={busy || !password}
            className="flex-1 rounded-full bg-primary-600 py-2 text-sm font-semibold text-white hover:bg-primary-700 disabled:opacity-50">
            {busy ? 'กำลังลงชื่อ…' : confirmLabel}
          </button>
        </div>
      </form>
    </div>,
    document.body
  )
}
