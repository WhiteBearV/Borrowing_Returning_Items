import { useEffect, useState } from 'react'
import { borrowApi } from '../../api/borrowApi.js'
import Pagination from '../../components/common/Pagination.jsx'
import { openPdf } from '../../utils/openPdf.js'
import { formatDate } from '../../utils/formatDate.js'

export default function BorrowRequestsPage() {
  const [data, setData] = useState({ items: [], total: 0 })
  const [page, setPage] = useState(1)
  const [expanded, setExpanded] = useState(null)
  const [rejectId, setRejectId] = useState(null)
  const [rejectReason, setRejectReason] = useState('')
  const [loading, setLoading] = useState(true)
  const [actionError, setActionError] = useState('')

  const load = () => {
    setLoading(true)
    borrowApi.list({ status: 'pending', page, page_size: 20 }).then(setData).finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [page])

  const approve = async (id) => {
    setActionError('')
    try {
      await borrowApi.approve(id)
      load()
    } catch (err) {
      // เช่น ของบางชิ้นสต็อกหมดระหว่างรออนุมัติ — ต้องบอกแอดมิน ไม่ใช่เงียบ
      setActionError(err?.response?.data?.detail ?? 'อนุมัติไม่สำเร็จ')
    }
  }

  // เปิดใบร่างฉบับเดียวกับที่นักศึกษาส่งมา (backend ออกใบร่างให้เองเมื่อคำขอยัง pending)
  const viewDraft = async (id) => openPdf(await borrowApi.downloadPdf(id))

  const reject = async () => {
    if (!rejectReason.trim()) return
    setActionError('')
    try {
      await borrowApi.reject(rejectId, rejectReason)
      setRejectId(null)
      setRejectReason('')
      load()
    } catch (err) {
      setActionError(err?.response?.data?.detail ?? 'ปฏิเสธไม่สำเร็จ')
    }
  }

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-bold text-gray-800 mb-6">คำขอรออนุมัติ</h1>

      {actionError && (
        <div className="mb-4 rounded-lg bg-red-50 border border-red-200 px-4 py-2.5 text-sm text-red-600 flex justify-between gap-3">
          <span>{actionError}</span>
          <button onClick={() => setActionError('')} className="text-red-400 hover:text-red-600 leading-none">×</button>
        </div>
      )}

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
                  <p className="text-sm text-gray-500">
                    วันที่ขอคืน: <span className="font-medium text-gray-700">{formatDate(req.requested_due_date)}</span>
                  </p>

                  <div className="rounded-lg border border-gray-100 overflow-hidden divide-y divide-gray-100">
                    {req.items.map((item) => (
                      <div key={item.id} className="flex justify-between px-3 py-2 text-sm text-gray-700">
                        <span>
                          {item.equipment_code && (
                            <span className="mr-2 font-mono text-xs text-gray-400">{item.equipment_code}</span>
                          )}
                          {item.equipment_name ?? item.equipment_id}
                        </span>
                        <span className="text-gray-400">×{item.quantity}</span>
                      </div>
                    ))}
                  </div>

                  <div className="flex gap-3 pt-1">
                    <button
                      onClick={() => viewDraft(req.id)}
                      className="rounded-lg border border-gray-300 px-4 py-1.5 text-sm font-semibold text-gray-700 hover:bg-gray-50"
                    >
                      ดูใบร่าง PDF
                    </button>
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

      <Pagination page={page} total={data.total} pageSize={20} onChange={setPage} />

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
