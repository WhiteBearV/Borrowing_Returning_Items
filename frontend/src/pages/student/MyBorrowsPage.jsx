import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { borrowApi } from '../../api/borrowApi.js'
import { openPdf } from '../../utils/openPdf.js'
import { formatDate } from '../../utils/formatDate.js'
import Pagination from '../../components/common/Pagination.jsx'
import BorrowStatusBadge from '../../components/borrow/BorrowStatusBadge.jsx'
import EmptyState from '../../components/common/EmptyState.jsx'

const ITEM_CONDITION_LABEL = {
  ok: 'คืนแล้ว', damaged: 'เสียหาย', lost: 'สูญหาย',
  returned_full: 'คืนครบ', used_up: 'ใช้หมด', discarded: 'เสียหาย/ทิ้ง',
}

export default function MyBorrowsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const highlightId = searchParams.get('request')
  const [data, setData] = useState({ items: [], total: 0 })
  const [page, setPage] = useState(1)
  const [expanded, setExpanded] = useState(highlightId)
  const [loading, setLoading] = useState(true)
  const [selectedItems, setSelectedItems] = useState(new Set())
  const highlightRef = useRef(null)

  const load = () => {
    setLoading(true)
    borrowApi.list({ page, page_size: 10 }).then(setData).finally(() => setLoading(false))
  }

  // poll ทุก 4 วิ mirror BorrowRequestsPage.jsx/NotificationBell.jsx — เห็นสถานะที่แอดมินอัปเดตแล้ว
  // (อนุมัติ/ปฏิเสธ/รับคืน) เองอัตโนมัติ ไม่ต้องกด refresh เอง
  useEffect(() => {
    load()
    const id = setInterval(load, 4000)
    return () => clearInterval(id)
  }, [page])

  // มาจากลิงก์แจ้งเตือน — คำขอที่ต้องการอาจไม่อยู่ในหน้าปัจจุบันที่โหลดมา (มีแบ่งหน้า)
  // ดึงมาแสดงแยกต่างหากแล้ว scroll ไปหาเลย ไม่ต้องเดาว่าอยู่หน้าไหน
  useEffect(() => {
    if (!highlightId) return
    borrowApi.get(highlightId).then((req) => {
      setData((d) => (d.items.some((i) => i.id === req.id) ? d : { ...d, items: [req, ...d.items] }))
      setExpanded(req.id)
    }).catch(() => {})
  }, [highlightId])

  useEffect(() => {
    if (highlightId && highlightRef.current) {
      highlightRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' })
      setSearchParams({}, { replace: true }) // เคลียร์ query กันค้างตอน refresh/แชร์ลิงก์ซ้ำ
    }
  }, [highlightId, data.items])

  const toggleExpand = (id) => {
    setExpanded(expanded === id ? null : id)
    setSelectedItems(new Set())
  }

  const cancel = async (id) => {
    if (!confirm('ยืนยันการยกเลิกคำขอ?')) return
    await borrowApi.cancel(id)
    load()
  }

  const renew = async (reqId, itemId) => {
    await borrowApi.renewItem(reqId, itemId)
    load()
  }

  const toggleSelect = (itemId) => {
    setSelectedItems((prev) => {
      const next = new Set(prev)
      if (next.has(itemId)) next.delete(itemId)
      else next.add(itemId)
      return next
    })
  }

  const requestReturn = async (reqId) => {
    if (!confirm('ยืนยันว่าต้องการแจ้งขอคืนอุปกรณ์ที่เลือกใช่หรือไม่?')) return
    await borrowApi.requestReturn(reqId, [...selectedItems])
    setSelectedItems(new Set())
    load()
  }

  const viewPdf = async (id) => openPdf(await borrowApi.downloadPdf(id))
  const viewReturnPdf = async (id) => openPdf(await borrowApi.downloadReturnPdf(id))

  return (
    <div className="max-w-3xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-light text-gray-800 mb-6">คำขอยืมของฉัน</h1>

      {loading ? (
        <EmptyState>กำลังโหลด…</EmptyState>
      ) : data.items.length === 0 ? (
        <EmptyState>ยังไม่มีคำขอยืม</EmptyState>
      ) : (
        <div className="space-y-3">
          {data.items.map((req) => {
          const selectableIds = req.status === 'approved'
            ? req.items.filter((i) => !i.returned && !i.return_requested).map((i) => i.id)
            : []
          const allSelected = selectableIds.length > 0 && selectableIds.every((id) => selectedItems.has(id))
          return (
            <div key={req.id} ref={req.id === highlightId ? highlightRef : null}
              className={`bg-white rounded-xl border shadow-sm overflow-hidden ${req.id === highlightId ? 'border-primary-400 ring-2 ring-primary-100' : 'border-gray-200'}`}>
              {/* Header row */}
              <button
                onClick={() => toggleExpand(req.id)}
                className="w-full flex items-center justify-between px-4 py-3 hover:bg-gray-50 text-left"
              >
                <div className="flex items-center gap-3">
                  <span className="font-mono text-sm font-semibold text-gray-700">{req.request_code}</span>
                  <BorrowStatusBadge status={req.status} />
                  {req.is_overdue && (
                    <span className="text-xs px-2 py-0.5 rounded-full bg-red-100 text-red-600 font-medium">เกินกำหนด</span>
                  )}
                </div>
                <div className="flex items-center gap-3">
                  {req.due_date && (
                    <span className="text-xs text-gray-400">ครบ {formatDate(req.due_date)}</span>
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
                        <div className="flex items-center gap-2">
                          {selectableIds.includes(item.id) && (
                            <input
                              type="checkbox"
                              checked={selectedItems.has(item.id)}
                              onChange={() => toggleSelect(item.id)}
                              className="rounded border-gray-300"
                            />
                          )}
                          <div>
                            <span className="text-gray-700">{item.equipment_name ?? item.equipment_id}</span>
                            <span className="ml-2 text-xs text-gray-400">×{item.quantity}</span>
                            {item.returned ? (
                              <span className={`ml-2 text-xs ${['ok', 'returned_full'].includes(item.condition_on_return) ? 'text-green-600' : 'text-red-500'}`}>
                                {ITEM_CONDITION_LABEL[item.condition_on_return] ?? 'คืนแล้ว'}
                              </span>
                            ) : item.return_requested ? (
                              <span className="ml-2 text-xs text-purple-600">รอ Admin ยืนยันคืน</span>
                            ) : (
                              req.status === 'approved' && item.item_type_snapshot === 'consumable' &&
                              <span className="ml-2 text-xs text-primary-500">เบิกแล้ว (รอสรุป)</span>
                            )}
                            {item.renewed_count > 0 && (
                              <span className="ml-2 text-xs text-primary-500">ต่อเวลา {item.renewed_count}×</span>
                            )}
                          </div>
                        </div>
                        {req.status === 'approved' && !item.returned && item.item_type_snapshot === 'durable' && (
                          <button
                            onClick={() => renew(req.id, item.id)}
                            className="text-xs text-primary-600 hover:underline"
                          >
                            ต่อเวลา
                          </button>
                        )}
                      </div>
                    ))}
                  </div>

                  {/* เลือกทั้งหมด + แจ้งขอคืน */}
                  {selectableIds.length > 0 && (
                    <div className="flex items-center justify-between">
                      {selectableIds.length > 1 ? (
                        <button
                          onClick={() => setSelectedItems(allSelected ? new Set() : new Set(selectableIds))}
                          className="text-xs text-gray-500 hover:underline"
                        >
                          {allSelected ? 'ยกเลิกเลือกทั้งหมด' : 'เลือกทั้งหมด'}
                        </button>
                      ) : <span />}
                      {selectedItems.size > 0 && (
                        <button
                          onClick={() => requestReturn(req.id)}
                          className="text-xs font-semibold text-purple-600 hover:underline"
                        >
                          แจ้งขอคืนที่เลือก ({selectedItems.size})
                        </button>
                      )}
                    </div>
                  )}

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
                    {/* ดูใบคำขอได้ทุกสถานะ — ที่ยังไม่อนุมัติออกเป็น "ใบร่าง" (ฉบับเดียวกับที่แอดมินตรวจ) */}
                    <button
                      onClick={() => viewPdf(req.id)}
                      className="text-sm text-primary-600 hover:underline"
                    >
                      {req.status === 'pending' ? 'ดูใบร่างคำขอ' : 'ดูใบยืม'}
                    </button>
                    {req.status === 'completed' && (
                      <button
                        onClick={() => viewReturnPdf(req.id)}
                        className="text-sm text-emerald-600 hover:underline"
                      >
                        ดูใบรับคืน
                      </button>
                    )}
                  </div>
                </div>
              )}
            </div>
          )})}
        </div>
      )}

      <Pagination page={page} total={data.total} pageSize={10} onChange={setPage} />
    </div>
  )
}
