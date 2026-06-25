import { useEffect, useState } from 'react'
import { borrowApi } from '../../api/borrowApi.js'

export default function BorrowRequestsPage() {
  const [data, setData] = useState({ items: [], total: 0 })
  const [page, setPage] = useState(1)
  const [expanded, setExpanded] = useState(null)
  const [rejectId, setRejectId] = useState(null)
  const [rejectReason, setRejectReason] = useState('')
  const [loading, setLoading] = useState(true)

  const load = () => {
    setLoading(true)
    borrowApi.list({ status: 'pending', page, page_size: 20 }).then(setData).finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [page])

  const approve = async (id) => {
    await borrowApi.approve(id)
    load()
  }

  const reject = async () => {
    if (!rejectReason.trim()) return
    await borrowApi.reject(rejectId, rejectReason)
    setRejectId(null)
    setRejectReason('')
    load()
  }

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-bold text-gray-800 mb-6">คำขอรออนุมัติ</h1>

      {loading ? (
        <p className="text-center text-gray-400 py-16">กำลังโหลด…</p>
      ) : data.items.length === 0 ? (
        <p className="text-center text-gray-400 py-16">ไม่มีคำขอรออนุมัติ</p>
      ) : (
        <div className="space-y-3">
          {data.items.map((req) => (
            <div key={req.id} className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
              <button
                onClick={() => setExpanded(expanded === req.id ? null : req.id)}
                className="w-full flex items-center justify-between px-4 py-3 hover:bg-gray-50 text-left"
              >
                <div>
                  <span className="font-mono text-sm font-semibold text-gray-700">{req.request_code}</span>
                  <span className="ml-3 text-sm text-gray-500">{req.items.length} รายการ</span>
                </div>
                <span className="text-xs text-gray-400">{new Date(req.requested_at).toLocaleDateString('th-TH')} {expanded === req.id ? '▲' : '▼'}</span>
              </button>

              {expanded === req.id && (
                <div className="border-t px-4 py-3 space-y-3">
                  {req.purpose && <p className="text-sm text-gray-500">วัตถุประสงค์: {req.purpose}</p>}

                  <div className="rounded-lg border border-gray-100 overflow-hidden divide-y divide-gray-100">
                    {req.items.map((item) => (
                      <div key={item.id} className="flex justify-between px-3 py-2 text-sm text-gray-700">
                        <span>{item.equipment_id}</span>
                        <span className="text-gray-400">×{item.quantity}</span>
                      </div>
                    ))}
                  </div>

                  <div className="flex gap-3 pt-1">
                    <button
                      onClick={() => approve(req.id)}
                      className="rounded-lg bg-green-600 px-4 py-1.5 text-sm font-semibold text-white hover:bg-green-700"
                    >
                      อนุมัติ
                    </button>
                    <button
                      onClick={() => { setRejectId(req.id); setRejectReason('') }}
                      className="rounded-lg border border-red-300 px-4 py-1.5 text-sm font-semibold text-red-600 hover:bg-red-50"
                    >
                      ปฏิเสธ
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {data.total > 20 && (
        <div className="flex justify-center items-center gap-3 mt-6">
          <button disabled={page === 1} onClick={() => setPage(page - 1)} className="px-3 py-1 text-sm rounded border disabled:opacity-40 hover:bg-gray-50">← ก่อนหน้า</button>
          <span className="text-sm text-gray-500">หน้า {page} / {Math.ceil(data.total / 20)}</span>
          <button disabled={page >= Math.ceil(data.total / 20)} onClick={() => setPage(page + 1)} className="px-3 py-1 text-sm rounded border disabled:opacity-40 hover:bg-gray-50">ถัดไป →</button>
        </div>
      )}

      {/* Reject modal */}
      {rejectId && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 px-4">
          <div className="bg-white rounded-2xl p-6 w-full max-w-sm shadow-xl">
            <h2 className="font-bold text-gray-800 mb-3">ระบุเหตุผลที่ปฏิเสธ</h2>
            <textarea
              autoFocus
              rows={3}
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              placeholder="เหตุผล…"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-red-400 resize-none"
            />
            <div className="flex gap-3 mt-4">
              <button onClick={() => setRejectId(null)} className="flex-1 rounded-lg border py-2 text-sm text-gray-600 hover:bg-gray-50">ยกเลิก</button>
              <button
                disabled={!rejectReason.trim()}
                onClick={reject}
                className="flex-1 rounded-lg bg-red-600 py-2 text-sm font-semibold text-white hover:bg-red-700 disabled:opacity-50"
              >
                ยืนยันปฏิเสธ
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
