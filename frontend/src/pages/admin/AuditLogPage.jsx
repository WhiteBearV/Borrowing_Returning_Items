import { useEffect, useState } from 'react'
import { auditApi } from '../../api/auditApi.js'
import Pagination from '../../components/common/Pagination.jsx'

export default function AuditLogPage() {
  const [data, setData] = useState({ items: [], total: 0 })
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    auditApi.list({ page, page_size: 25 }).then(setData).finally(() => setLoading(false))
  }, [page])

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-bold text-gray-800 mb-6">Audit Log</h1>

      {loading ? (
        <p className="text-center text-gray-400 py-16">กำลังโหลด…</p>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                {['เวลา', 'Action', 'Table', 'Target ID', 'Detail'].map((h) => (
                  <th key={h} className="px-4 py-2.5 text-left text-xs font-semibold text-gray-500">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {data.items.map((log) => (
                <tr key={log.id} className="hover:bg-gray-50">
                  <td className="px-4 py-2.5 text-xs text-gray-400 whitespace-nowrap">
                    {new Date(log.created_at).toLocaleString('th-TH')}
                  </td>
                  <td className="px-4 py-2.5 font-mono text-xs text-gray-700">{log.action}</td>
                  <td className="px-4 py-2.5 text-xs text-gray-500">{log.target_table}</td>
                  <td className="px-4 py-2.5 font-mono text-xs text-gray-400 truncate max-w-[120px]">{log.target_id}</td>
                  <td className="px-4 py-2.5 text-xs text-gray-500 truncate max-w-[200px]">
                    {log.detail ? JSON.stringify(log.detail) : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.items.length === 0 && <p className="text-center text-gray-400 py-10">ยังไม่มี log</p>}
        </div>
      )}

      <Pagination page={page} total={data.total} pageSize={25} onChange={setPage} />
    </div>
  )
}
