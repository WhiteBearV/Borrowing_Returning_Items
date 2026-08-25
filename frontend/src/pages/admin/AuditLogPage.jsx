import { useEffect, useState } from 'react'
import { auditApi } from '../../api/auditApi.js'
import Pagination from '../../components/common/Pagination.jsx'
import EmptyState from '../../components/common/EmptyState.jsx'

// ป้ายภาษาไทยของแต่ละ action ให้อ่านเข้าใจว่าใครทำอะไร
const ACTION_LABEL = {
  approve_request: 'อนุมัติคำขอ',
  reject_request: 'ปฏิเสธคำขอ',
  confirm_return: 'รับคืนอุปกรณ์',
  create_equipment: 'เพิ่มอุปกรณ์',
  update_equipment: 'แก้ไขอุปกรณ์',
  retire_equipment: 'ปลดระวางอุปกรณ์',
  delete_equipment: 'ลบอุปกรณ์',
  split_equipment: 'แยกอุปกรณ์เป็นรายชิ้น',
}
const actionLabel = (a) => ACTION_LABEL[a] ?? a

function DetailModal({ log, onClose }) {
  const rows = [
    ['ผู้ทำ', `${log.actor_name ?? '—'}${log.actor_identifier ? ` (${log.actor_identifier})` : ''}`],
    ['การกระทำ', actionLabel(log.action)],
    ['เวลา', new Date(log.created_at).toLocaleString('th-TH')],
    ['ตาราง', log.target_table],
    ['Target ID', log.target_id],
  ]
  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50 px-4" onClick={onClose}>
      <div className="bg-white rounded-2xl p-6 w-full max-w-md shadow-xl space-y-4" onClick={(e) => e.stopPropagation()}>
        <h2 className="font-bold text-gray-800">รายละเอียด Log</h2>
        <div className="space-y-2 text-sm">
          {rows.map(([k, v]) => (
            <div key={k} className="flex gap-3">
              <span className="w-24 shrink-0 text-gray-400">{k}</span>
              <span className="font-mono text-xs break-all text-gray-700">{v}</span>
            </div>
          ))}
        </div>
        {log.detail && (
          <div>
            <p className="text-xs text-gray-400 mb-1">ข้อมูลเพิ่มเติม</p>
            <pre className="bg-gray-50 rounded-lg p-3 text-xs text-gray-700 overflow-x-auto whitespace-pre-wrap break-all">
              {JSON.stringify(log.detail, null, 2)}
            </pre>
          </div>
        )}
        <button onClick={onClose} className="w-full rounded-full border py-2 text-sm text-gray-600 hover:bg-gray-50">ปิด</button>
      </div>
    </div>
  )
}

export default function AuditLogPage() {
  const [data, setData] = useState({ items: [], total: 0 })
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState(null)

  useEffect(() => {
    setLoading(true)
    auditApi.list({ page, page_size: 25 }).then(setData).finally(() => setLoading(false))
  }, [page])

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-light text-gray-800 mb-6">Audit Log</h1>

      {loading ? (
        <EmptyState>กำลังโหลด…</EmptyState>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                {['เวลา', 'ผู้ทำ', 'การกระทำ', 'รายละเอียด', ''].map((h) => (
                  <th key={h} className="px-4 py-2.5 text-left text-xs font-semibold text-gray-500">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {data.items.map((log) => (
                <tr key={log.id} className="hover:bg-gray-50 cursor-pointer" onClick={() => setSelected(log)}>
                  <td className="px-4 py-2.5 text-xs text-gray-400 whitespace-nowrap">
                    {new Date(log.created_at).toLocaleString('th-TH')}
                  </td>
                  <td className="px-4 py-2.5 text-xs text-gray-700 whitespace-nowrap">
                    {log.actor_name ?? '—'}
                    {log.actor_identifier && <span className="text-gray-400"> ({log.actor_identifier})</span>}
                  </td>
                  <td className="px-4 py-2.5 text-xs text-gray-700">{actionLabel(log.action)}</td>
                  <td className="px-4 py-2.5 text-xs text-gray-500 truncate max-w-[220px]">
                    {log.detail ? JSON.stringify(log.detail) : '—'}
                  </td>
                  <td className="px-4 py-2.5 text-xs text-primary-600 whitespace-nowrap">ดูรายละเอียด →</td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.items.length === 0 && <EmptyState className="py-10">ยังไม่มี log</EmptyState>}
        </div>
      )}

      <Pagination page={page} total={data.total} pageSize={25} onChange={setPage} />

      {selected && <DetailModal log={selected} onClose={() => setSelected(null)} />}
    </div>
  )
}
