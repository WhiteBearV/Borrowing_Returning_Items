import { useEffect, useState } from 'react'
import { usersApi } from '../../api/usersApi.js'
import ConfirmModal from '../../components/common/ConfirmModal.jsx'
import Pagination from '../../components/common/Pagination.jsx'

const MAJOR_LABEL = { comp_eng: 'วิศวกรรมคอมพิวเตอร์', digital_design: 'ออกแบบดิจิทัล' }
// ดร. เพิ่มจาก RegisterPage.jsx เพราะ admin สร้างบัญชีอาจารย์ได้ด้วย ไม่ใช่แค่นักศึกษา
const TITLES = ['นาย', 'นาง', 'นางสาว', 'ดร.']

export default function UsersPage() {
  const [data, setData] = useState({ items: [], total: 0 })
  const [page, setPage] = useState(1)
  const [roleFilter, setRoleFilter] = useState('')
  const [loading, setLoading] = useState(true)
  const [confirm, setConfirm] = useState(null)
  const [showAdd, setShowAdd] = useState(false)

  const load = () => {
    setLoading(true)
    usersApi.list({ role: roleFilter || undefined, page, page_size: 20 }).then(setData).finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [roleFilter, page])

  const toggleStatus = (user) => {
    const label = user.is_active ? 'ปิดการใช้งาน' : 'เปิดการใช้งาน'
    setConfirm({
      title: `${label}บัญชี`,
      message: `${label} "${user.full_name}" ?`,
      confirmLabel: label,
      danger: user.is_active,
      onConfirm: async () => { setConfirm(null); await usersApi.updateStatus(user.id, !user.is_active); load() },
    })
  }

  const deleteUser = (user) => setConfirm({
    title: 'ลบบัญชีถาวร',
    message: `ลบบัญชี "${user.full_name}" ออกจากระบบถาวร?\nประวัติการยืมทั้งหมดจะถูกลบด้วย`,
    confirmLabel: 'ลบถาวร',
    danger: true,
    onConfirm: async () => {
      setConfirm(null)
      try { await usersApi.deleteUser(user.id); load() }
      catch (e) { alert(e.response?.data?.detail ?? 'ลบไม่สำเร็จ') }
    },
  })

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-6">
        <h1 className="text-2xl font-light text-gray-800">จัดการผู้ใช้</h1>
        <div className="flex items-center gap-3">
          <select value={roleFilter} onChange={(e) => { setRoleFilter(e.target.value); setPage(1) }}
            className="flex-1 sm:flex-none rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500">
            <option value="">ทุก role</option>
            <option value="student">นักศึกษา</option>
            <option value="admin">Admin</option>
          </select>
          <button onClick={() => setShowAdd(true)}
            className="rounded-full bg-primary-600 px-4 py-2 text-sm font-semibold text-white hover:bg-primary-700">
            + เพิ่มผู้ใช้
          </button>
        </div>
      </div>

      {loading ? (
        <p className="text-center text-gray-400 py-16">กำลังโหลด…</p>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                {['ชื่อ', 'อีเมล', 'รหัสนักศึกษา', 'สาขา', 'สถานะ', ''].map((h) => (
                  <th key={h} className="px-4 py-2.5 text-left text-xs font-semibold text-gray-500">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {data.items.map((u) => (
                <tr key={u.id} className={`hover:bg-gray-50 ${!u.is_active ? 'opacity-50' : ''}`}>
                  <td className="px-4 py-2.5 font-medium text-gray-800">
                    {u.full_name}
                    {u.role === 'admin' && <span className="ml-2 text-xs bg-purple-100 text-purple-700 px-1.5 py-0.5 rounded">admin</span>}
                  </td>
                  <td className="px-4 py-2.5 text-gray-500">{u.email}</td>
                  <td className="px-4 py-2.5 text-gray-500 font-mono text-xs">{u.student_id ?? '—'}</td>
                  <td className="px-4 py-2.5 text-gray-500 text-xs">{MAJOR_LABEL[u.major] ?? '—'}</td>
                  <td className="px-4 py-2.5">
                    {u.email_verified
                      ? <span className="text-xs text-green-600">ยืนยันแล้ว</span>
                      : <span className="text-xs text-yellow-600">รอยืนยัน</span>}
                  </td>
                  <td className="px-4 py-2.5 flex items-center gap-3">
                    <button onClick={() => toggleStatus(u)}
                      className={`text-xs hover:underline ${u.is_active ? 'text-red-500' : 'text-green-600'}`}>
                      {u.is_active ? 'ปิดใช้งาน' : 'เปิดใช้งาน'}
                    </button>
                    {!u.is_active && (
                      <button onClick={() => deleteUser(u)}
                        className="text-xs text-red-700 hover:underline font-medium">
                        ลบถาวร
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.items.length === 0 && <p className="text-center text-gray-400 py-10">ไม่พบผู้ใช้</p>}
        </div>
      )}

      <Pagination page={page} total={data.total} pageSize={20} onChange={setPage} />

      {confirm && (
        <ConfirmModal
          title={confirm.title}
          message={confirm.message}
          confirmLabel={confirm.confirmLabel}
          danger={confirm.danger}
          onConfirm={confirm.onConfirm}
          onCancel={() => setConfirm(null)}
        />
      )}

      {showAdd && (
        <AddUserModal
          onClose={() => setShowAdd(false)}
          onCreated={() => { setShowAdd(false); setPage(1); load() }}
        />
      )}
    </div>
  )
}

function AddUserModal({ onClose, onCreated }) {
  const [form, setForm] = useState({
    role: 'student', title: '', first_name: '', last_name: '', email: '', password: '',
    student_id: '', username: '', major: 'comp_eng',
  })
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })

  const submit = async (e) => {
    e.preventDefault()
    setError('')
    setSaving(true)
    // ส่งเฉพาะ field ที่เกี่ยวกับ role นั้น ๆ (ค่าว่าง -> undefined)
    const payload = {
      role: form.role,
      full_name: `${form.title}${form.first_name.trim()} ${form.last_name.trim()}`.trim(),
      email: form.email,
      password: form.password,
      student_id: form.role === 'student' ? form.student_id || undefined : undefined,
      major: form.role === 'student' ? form.major : undefined,
      username: form.role === 'admin' ? form.username || undefined : undefined,
    }
    try {
      await usersApi.create(payload)
      onCreated()
    } catch (err) {
      setError(err.response?.data?.detail ?? 'สร้างบัญชีไม่สำเร็จ')
    } finally {
      setSaving(false)
    }
  }

  const input = 'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500'

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center px-4 z-50">
      <form onSubmit={submit} className="w-full max-w-md bg-white rounded-2xl shadow-lg p-6 space-y-3">
        <h2 className="text-lg font-bold text-gray-800">เพิ่มผู้ใช้ใหม่</h2>

        {error && <div className="rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">{error}</div>}

        <div className="flex gap-2">
          {['student', 'admin'].map((r) => (
            <button type="button" key={r} onClick={() => setForm({ ...form, role: r })}
              className={`flex-1 rounded-lg py-2 text-sm font-medium border ${form.role === r ? 'bg-primary-600 text-white border-primary-600' : 'bg-white text-gray-600 border-gray-300'}`}>
              {r === 'student' ? 'นักศึกษา' : 'Admin'}
            </button>
          ))}
        </div>

        <div className="flex gap-2">
          <select
            className="w-28 flex-none rounded-lg border border-gray-300 px-2 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
            required value={form.title} onChange={set('title')}
          >
            <option value="">คำนำหน้า</option>
            {TITLES.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
          <input className={input} placeholder="ชื่อ" required value={form.first_name} onChange={set('first_name')} />
          <input className={input} placeholder="นามสกุล" required value={form.last_name} onChange={set('last_name')} />
        </div>
        <input className={input} type="email" placeholder="อีเมล" required value={form.email} onChange={set('email')} />
        <input className={input} type="password" placeholder="รหัสผ่าน" required minLength={6} value={form.password} onChange={set('password')} />

        {form.role === 'student' ? (
          <>
            <input className={input} placeholder="รหัสนักศึกษา" value={form.student_id} onChange={set('student_id')} />
            <select className={input} value={form.major} onChange={set('major')}>
              <option value="comp_eng">วิศวกรรมคอมพิวเตอร์</option>
              <option value="digital_design">ออกแบบดิจิทัล</option>
            </select>
          </>
        ) : (
          <input className={input} placeholder="ชื่อผู้ใช้ (username) สำหรับล็อกอิน" value={form.username} onChange={set('username')} />
        )}

        <div className="flex gap-2 pt-2">
          <button type="button" onClick={onClose}
            className="flex-1 rounded-full border border-gray-300 py-2 text-sm font-medium text-gray-600 hover:bg-gray-50">
            ยกเลิก
          </button>
          <button type="submit" disabled={saving}
            className="flex-1 rounded-full bg-primary-600 py-2 text-sm font-semibold text-white hover:bg-primary-700 disabled:opacity-50">
            {saving ? 'กำลังสร้าง…' : 'สร้างบัญชี'}
          </button>
        </div>
      </form>
    </div>
  )
}
