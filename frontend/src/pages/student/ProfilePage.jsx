import { useState } from 'react'
import { api } from '../../api/axiosInstance.js'
import { useAuthContext } from '../../context/AuthContext.jsx'

const MAJORS = [
  { value: 'comp_eng', label: 'วิศวกรรมคอมพิวเตอร์' },
  { value: 'digital_design', label: 'ออกแบบดิจิทัล' },
]

const imgSrc = (url) => (url?.startsWith('/') ? `${import.meta.env.VITE_API_URL || 'http://localhost:8000'}${url}` : url)

export default function ProfilePage() {
  const { user, setUser } = useAuthContext()
  const [form, setForm] = useState({ full_name: user?.full_name ?? '', major: user?.major ?? '' })
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState('')
  const [uploading, setUploading] = useState(false)

  const uploadAvatar = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    setError('')
    try {
      const fd = new FormData()
      fd.append('file', file)
      // override header ให้ axios ตั้ง multipart boundary เอง (default instance เป็น json)
      const res = await api.post('/users/me/avatar', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
      setUser(res.data)
    } catch (err) {
      setError(err.response?.data?.detail ?? 'อัปโหลดรูปไม่สำเร็จ')
    } finally {
      setUploading(false)
    }
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setSaving(true)
    setError('')
    try {
      await api.patch('/users/me', { full_name: form.full_name, major: form.major || undefined })
      setSaved(true)
      setTimeout(() => setSaved(false), 2500)
    } catch (err) {
      setError(err.response?.data?.detail ?? 'บันทึกไม่สำเร็จ')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="max-w-md mx-auto px-4 py-8">
      <h1 className="text-2xl font-light text-gray-800 mb-6">โปรไฟล์</h1>

      <div className="bg-white rounded-2xl border border-gray-200 shadow-sm p-6 space-y-5">
        {/* Avatar */}
        <div className="flex flex-col items-center gap-3 pb-4 border-b border-gray-100">
          {user?.avatar_url ? (
            <img src={imgSrc(user.avatar_url)} alt="avatar"
              className="w-24 h-24 rounded-full object-cover border border-gray-200" />
          ) : (
            <div className="w-24 h-24 rounded-full bg-primary-100 flex items-center justify-center text-3xl font-bold text-primary-600">
              {(user?.full_name ?? '?').trim().charAt(0)}
            </div>
          )}
          <label className="text-sm text-primary-600 hover:underline cursor-pointer">
            {uploading ? 'กำลังอัปโหลด…' : 'เปลี่ยนรูปโปรไฟล์'}
            <input type="file" accept="image/*" onChange={uploadAvatar} disabled={uploading} className="hidden" />
          </label>
        </div>

        {/* Read-only fields */}
        <div className="space-y-3 pb-4 border-b border-gray-100">
          {[
            ['อีเมล', user?.email],
            ['รหัสนักศึกษา', user?.student_id ?? '—'],
            ['Role', user?.role],
          ].map(([label, val]) => (
            <div key={label} className="flex justify-between text-sm">
              <span className="text-gray-500">{label}</span>
              <span className="text-gray-800 font-medium">{val}</span>
            </div>
          ))}
        </div>

        {/* Editable fields */}
        {error && <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">ชื่อ-นามสกุล</label>
            <input
              type="text"
              required
              value={form.full_name}
              onChange={(e) => setForm({ ...form, full_name: e.target.value })}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">สาขา</label>
            <select
              value={form.major}
              onChange={(e) => setForm({ ...form, major: e.target.value })}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500"
            >
              <option value="">— ไม่ระบุ —</option>
              {MAJORS.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
            </select>
          </div>
          <button
            type="submit"
            disabled={saving}
            className="w-full rounded-full bg-primary-600 py-2 text-sm font-semibold text-white hover:bg-primary-700 disabled:opacity-50"
          >
            {saving ? 'กำลังบันทึก…' : saved ? '✓ บันทึกแล้ว' : 'บันทึก'}
          </button>
        </form>
      </div>
    </div>
  )
}
