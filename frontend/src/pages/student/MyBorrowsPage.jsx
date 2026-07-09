import { useEffect, useState } from 'react'
import { borrowApi } from '../../api/borrowApi.js'
import Pagination from '../../components/common/Pagination.jsx'

const STATUS_STYLE = {
  pending:   'bg-yellow-100 text-yellow-700',
  approved:  'bg-blue-100 text-blue-700',
  rejected:  'bg-red-100 text-red-700',
  cancelled: 'bg-gray-100 text-gray-500',
  completed: 'bg-green-100 text-green-700',
}
const STATUS_LABEL = {
  pending: 'รออนุมัติ', approved: 'อนุมัติแล้ว', rejected: 'ถูกปฏิเสธ',
  cancelled: 'ยกเลิกแล้ว', completed: 'คืนครบแล้ว',
}
const ITEM_CONDITION_LABEL = {
  ok: 'คืนแล้ว', damaged: 'เสียหาย', lost: 'สูญหาย',
  returned_full: 'คืนครบ', used_up: 'ใช้หมด', discarded: 'เสียหาย/ทิ้ง',
}

export default function MyBorrowsPage() {
  const [data, setData] = useState({ items: [], total: 0 })
  const [page, setPage] = useState(1)
  const [expanded, setExpanded] = useState(null)
  const [loading, setLoading] = useState(true)

  const load = () => {
    setLoading(true)
    borrowApi.list({ page, page_size: 10 }).then(setData).finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [page])

  const cancel = async (id) => {
    if (!confirm('ยืนยันการยกเลิกคำขอ?')) return
    await borrowApi.cancel(id)
    load()
  }

  const renew = async (reqId, itemId) => {
    await borrowApi.renewItem(reqId, itemId)
    load()
  }

  const saveBlob = (blob, filename) => {
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
  }
  const downloadPdf = async (id, code) => saveBlob(await borrowApi.downloadPdf(id), `${code}.pdf`)
  const downloadReturnPdf = async (id, code) =>
    saveBlob(await borrowApi.downloadReturnPdf(id), `${code}-ใบรับคืน.pdf`)

  return (
    <div className="max-w-3xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-bold text-gray-800 mb-6">คำขอยืมของฉัน</h1>

      {loading ? (
        <p className="text-center text-gray-400 py-16">กำลังโหลด…</p>
      ) : data.items.length === 0 ? (
        <p className="text-center text-gray-400 py-16">ยังไม่มีคำขอยืม</p>
      ) : (
        <div className="space-y-3">
          {data.items.map((req) => (
            <div key={req.id} className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
              {/* Header row */}
              <button
                onClick={() => setExpanded(expanded === req.id ? null : req.id)}
                className="w-full flex items-center justify-between px-4 py-3 hover:bg-gray-50 text-left"
              >
                <div className="flex items-center gap-3">
                  <span className="font-mono text-sm font-semibold text-gray-700">{req.request_code}</span>
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${STATUS_STYLE[req.status]}`}>
                    {STATUS_LABEL[req.status]}
                  </span>
                  {req.is_overdue && (
                    <span className="text-xs px-2 py-0.5 rounded-full bg-red-100 text-red-600 font-medium">เกินกำหนด</span>
                  )}
                </div>
                <div className="flex items-center gap-3">
                  {req.due_date && (
                    <span className="text-xs text-gray-400">ครบ {req.due_date}</span>
                  )}
                  <span className="text-gray-400 text-xs">{expanded === req.id ? '▲' : '▼'}</span>
                </div>
              </button>

              {/* Expanded detail */}
              {expanded === req.id && (
                <div className="border-t px-4 py-3 space-y-3">
                  {req.purpose && <p className="text-sm text-gray-500">วัตถุประสงค์: {req.purpose}</p>}
                  {req.rejection_reason && (
                    <p className="text-sm text-red-600">เหตุผลที่ปฏิเสธ: {req.rejection_reason}</p>
                  )}

                  {/* Items */}
                  <div className="divide-y divide-gray-100 rounded-lg border border-gray-100 overflow-hidden">
                    {req.items.map((item) => (
                      <div key={item.id} className="flex items-center justify-between px-3 py-2 text-sm">
                        <div>
                          <span className="text-gray-700">{item.equipment_name ?? item.equipment_id}</span>
                          <span className="ml-2 text-xs text-gray-400">×{item.quantity}</span>
                          {item.returned ? (
                            <span className={`ml-2 text-xs ${['ok', 'returned_full'].includes(item.condition_on_return) ? 'text-green-600' : 'text-red-500'}`}>
                              {ITEM_CONDITION_LABEL[item.condition_on_return] ?? 'คืนแล้ว'}
                            </span>
                          ) : (
                            req.status === 'approved' && item.item_type_snapshot === 'consumable' &&
                            <span className="ml-2 text-xs text-blue-500">เบิกแล้ว (รอสรุป)</span>
                          )}
                          {item.renewed_count > 0 && (
                            <span className="ml-2 text-xs text-blue-500">ต่อเวลา {item.renewed_count}×</span>
                          )}
                        </div>
                        {req.status === 'approved' && !item.returned && item.item_type_snapshot === 'durable' && (
                          <button
                            onClick={() => renew(req.id, item.id)}
                            className="text-xs text-blue-600 hover:underline"
                          >
                            ต่อเวลา
                          </button>
                        )}
                      </div>
                    ))}
                  </div>

                  {/* Actions */}
                  <div className="flex gap-2 pt-1">
                    {req.status === 'pending' && (
                      <button
                        onClick={() => cancel(req.id)}
                        className="text-sm text-red-600 hover:underline"
                      >
                        ยกเลิกคำขอ
                      </button>
                    )}
                    {(req.status === 'approved' || req.status === 'completed') && (
                      <button
                        onClick={() => downloadPdf(req.id, req.request_code)}
                        className="text-sm text-blue-600 hover:underline"
                      >
                        ใบยืม PDF
                      </button>
                    )}
                    {req.status === 'completed' && (
                      <button
                        onClick={() => downloadReturnPdf(req.id, req.request_code)}
                        className="text-sm text-emerald-600 hover:underline"
                      >
                        ใบรับคืน PDF
                      </button>
                    )}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <Pagination page={page} total={data.total} pageSize={10} onChange={setPage} />
    </div>
  )
}
