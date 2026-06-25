import { useEffect, useState } from 'react'
import { usersApi } from '../../api/usersApi.js'

const MAJOR_LABEL = { comp_eng: 'วิศวกรรมคอมพิวเตอร์', digital_design: 'ออกแบบดิจิทัล' }

export default function UsersPage() {
  const [data, setData] = useState({ items: [], total: 0 })
  const [page, setPage] = useState(1)
  const [roleFilter, setRoleFilter] = useState('')
  const [loading, setLoading] = useState(true)

  const load = () => {
    setLoading(true)
    usersApi.list({ role: roleFilter || undefined, page, page_size: 20 }).then(setData).finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [roleFilter, page])

  const toggleStatus = async (user) => {
    const label = user.is_active ? 'ปิดการใช้งาน' : 'เปิดการใช้งาน'
    if (!confirm(`${label} บัญชี "${user.full_name}" ?`)) return
    await usersApi.updateStatus(user.id, !user.is_active)
    load()
  }

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-800">จัดการผู้ใช้</h1>
        <select value={roleFilter} onChange={(e) => { setRoleFilter(e.target.value); setPage(1) }}
          className="rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500">
          <option value="">ทุก role</option>
          <option value="student">นักศึกษา</option>
          <option value="admin">Admin</option>
        </select>
      </div>

      {loading ? (
        <p className="text-center text-gray-400 py-16">กำลังโหลด…</p>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
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
                  <td className="px-4 py-2.5">
                    <button onClick={() => toggleStatus(u)}
                      className={`text-xs hover:underline ${u.is_active ? 'text-red-500' : 'text-green-600'}`}>
                      {u.is_active ? 'ปิดใช้งาน' : 'เปิดใช้งาน'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.items.length === 0 && <p className="text-center text-gray-400 py-10">ไม่พบผู้ใช้</p>}
        </div>
      )}

      {data.total > 20 && (
        <div className="flex justify-center items-center gap-3 mt-6">
          <button disabled={page === 1} onClick={() => setPage(page - 1)} className="px-3 py-1 text-sm rounded border disabled:opacity-40 hover:bg-gray-50">← ก่อนหน้า</button>
          <span className="text-sm text-gray-500">หน้า {page} / {Math.ceil(data.total / 20)}</span>
          <button disabled={page >= Math.ceil(data.total / 20)} onClick={() => setPage(page + 1)} className="px-3 py-1 text-sm rounded border disabled:opacity-40 hover:bg-gray-50">ถัดไป →</button>
        </div>
      )}
    </div>
  )
}
