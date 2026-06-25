import { useEffect, useState } from 'react'
import { borrowApi } from '../../api/borrowApi.js'

const STATUS_STYLE = {
  pending: 'bg-yellow-100 text-yellow-700', approved: 'bg-blue-100 text-blue-700',
  rejected: 'bg-red-100 text-red-700', cancelled: 'bg-gray-100 text-gray-500',
  completed: 'bg-green-100 text-green-700',
}
const STATUS_LABEL = { pending: 'รออนุมัติ', approved: 'อนุมัติแล้ว', rejected: 'ปฏิเสธ', cancelled: 'ยกเลิก', completed: 'คืนครบ' }
const CONDITION_OPTIONS = [{ value: 'ok', label: 'ปกติ' }, { value: 'damaged', label: 'เสียหาย' }, { value: 'lost', label: 'สูญหาย' }]

function ReturnModal({ requestId, itemId, onClose, onDone }) {
  const [condition, setCondition] = useState('ok')
  const [note, setNote] = useState('')
  const [loading, setLoading] = useState(false)

  const submit = async () => {
    setLoading(true)
    try {
      await borrowApi.returnItem(requestId, itemId, { condition_on_return: condition, damage_note: note || undefined })
      onDone()
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 px-4">
      <div className="bg-white rounded-2xl p-6 w-full max-w-sm shadow-xl space-y-4">
        <h2 className="font-bold text-gray-800">ยืนยันรับคืนอุปกรณ์</h2>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">สภาพอุปกรณ์</label>
          <select value={condition} onChange={(e) => setCondition(e.target.value)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500">
            {CONDITION_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
        {condition !== 'ok' && (
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">บันทึกความเสียหาย</label>
            <textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="อธิบายความเสียหาย…" />
          </div>
        )}
        <div className="flex gap-3">
          <button onClick={onClose} className="flex-1 rounded-lg border py-2 text-sm text-gray-600 hover:bg-gray-50">ยกเลิก</button>
          <button onClick={submit} disabled={loading}
            className="flex-1 rounded-lg bg-blue-600 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50">
            {loading ? 'กำลังบันทึก…' : 'ยืนยันรับคืน'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default function AllBorrowsPage() {
  const [data, setData] = useState({ items: [], total: 0 })
  const [filterStatus, setFilterStatus] = useState('')
  const [page, setPage] = useState(1)
  const [expanded, setExpanded] = useState(null)
  const [returnTarget, setReturnTarget] = useState(null) // { requestId, itemId }
  const [loading, setLoading] = useState(true)

  const load = () => {
    setLoading(true)
    borrowApi.list({ status: filterStatus || undefined, page, page_size: 20 }).then(setData).finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [filterStatus, page])

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-800">ประวัติการยืมทั้งหมด</h1>
        <select value={filterStatus} onChange={(e) => { setFilterStatus(e.target.value); setPage(1) }}
          className="rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500">
          <option value="">ทุกสถานะ</option>
          {Object.entries(STATUS_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
      </div>

      {loading ? (
        <p className="text-center text-gray-400 py-16">กำลังโหลด…</p>
      ) : data.items.length === 0 ? (
        <p className="text-center text-gray-400 py-16">ไม่พบรายการ</p>
      ) : (
        <div className="space-y-3">
          {data.items.map((req) => (
            <div key={req.id} className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
              <button
                onClick={() => setExpanded(expanded === req.id ? null : req.id)}
                className="w-full flex items-center justify-between px-4 py-3 hover:bg-gray-50 text-left"
              >
                <div className="flex items-center gap-3">
                  <span className="font-mono text-sm font-semibold text-gray-700">{req.request_code}</span>
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${STATUS_STYLE[req.status]}`}>{STATUS_LABEL[req.status]}</span>
                  {req.is_overdue && <span className="text-xs px-2 py-0.5 rounded-full bg-red-100 text-red-600 font-medium">เกินกำหนด</span>}
                </div>
                <div className="flex items-center gap-3">
                  {req.due_date && <span className="text-xs text-gray-400">ครบ {req.due_date}</span>}
                  <span className="text-xs text-gray-400">{expanded === req.id ? '▲' : '▼'}</span>
                </div>
              </button>

              {expanded === req.id && (
                <div className="border-t px-4 py-3 space-y-3">
                  {req.purpose && <p className="text-sm text-gray-500">วัตถุประสงค์: {req.purpose}</p>}

                  <div className="rounded-lg border border-gray-100 overflow-hidden divide-y divide-gray-100">
                    {req.items.map((item) => (
                      <div key={item.id} className="flex items-center justify-between px-3 py-2 text-sm">
                        <div className="flex items-center gap-2">
                          <span className="text-gray-700">{item.equipment_id}</span>
                          <span className="text-gray-400">×{item.quantity}</span>
                          {item.returned && <span className="text-xs text-green-600">คืนแล้ว{item.condition_on_return !== 'ok' ? ` (${item.condition_on_return})` : ''}</span>}
                        </div>
                        {req.status === 'approved' && !item.returned && item.item_type_snapshot === 'durable' && (
                          <button
                            onClick={() => setReturnTarget({ requestId: req.id, itemId: item.id })}
                            className="text-xs rounded-lg bg-blue-50 text-blue-600 px-3 py-1 hover:bg-blue-100 font-medium"
                          >
                            รับคืน
                          </button>
                        )}
                      </div>
                    ))}
                  </div>

                  {(req.status === 'approved' || req.status === 'completed') && (
                    <button
                      onClick={async () => {
                        const blob = await borrowApi.downloadPdf(req.id)
                        const url = URL.createObjectURL(blob)
                        Object.assign(document.createElement('a'), { href: url, download: `${req.request_code}.pdf` }).click()
                        URL.revokeObjectURL(url)
                      }}
                      className="text-sm text-blue-600 hover:underline"
                    >
                      ดาวน์โหลด PDF
                    </button>
                  )}
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

      {returnTarget && (
        <ReturnModal
          requestId={returnTarget.requestId}
          itemId={returnTarget.itemId}
          onClose={() => setReturnTarget(null)}
          onDone={() => { setReturnTarget(null); load() }}
        />
      )}
    </div>
  )
}
