import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { borrowApi } from '../../api/borrowApi.js'
import { equipmentApi } from '../../api/equipmentApi.js'
import ConfirmModal from '../../components/common/ConfirmModal.jsx'
import Pagination from '../../components/common/Pagination.jsx'
import { ReturnModal, CONDITION_LABEL } from '../../components/borrow/ReturnModal.jsx'
import { SignatureModal, SIGNATURE_LABEL } from '../../components/borrow/SignatureModal.jsx'
import BorrowStatusBadge, { STATUS_LABEL } from '../../components/borrow/BorrowStatusBadge.jsx'
import { openPdf } from '../../utils/openPdf.js'
import { formatDate, formatDateTime } from '../../utils/formatDate.js'
import { itemDueDate, hasOwnDueDate } from '../../utils/dueDate.js'
import EmptyState from '../../components/common/EmptyState.jsx'

const imgSrc = (url) => (url?.startsWith('/') ? `${import.meta.env.VITE_API_URL || 'http://localhost:8000'}${url}` : url)

export default function AllBorrowsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const highlightId = searchParams.get('request')
  const [data, setData] = useState({ items: [], total: 0 })
  const [filterStatus, setFilterStatus] = useState('')
  const [overdueOnly, setOverdueOnly] = useState(false)
  const [search, setSearch] = useState('')
  const [filterCategory, setFilterCategory] = useState('')
  const [filterType, setFilterType] = useState('')
  const [categories, setCategories] = useState([])
  const [page, setPage] = useState(1)
  const [expanded, setExpanded] = useState(highlightId)
  const [returnTarget, setReturnTarget] = useState(null) // { requestId, itemId }
  const [signTarget, setSignTarget] = useState(null) // { id, code, mode } — เซ็นรับของ/รับคืน (เฟส 11)
  const [confirmDelete, setConfirmDelete] = useState(null) // { id, code }
  const [loading, setLoading] = useState(true)
  const highlightRef = useRef(null)

  const load = () => {
    setLoading(true)
    borrowApi.list({
      status: filterStatus || undefined, overdue_only: overdueOnly || undefined,
      search: search || undefined, page, page_size: 20,
      category_id: filterCategory || undefined, item_type: filterType || undefined,
    }).then(setData).finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [filterStatus, overdueOnly, search, page, filterCategory, filterType])

  useEffect(() => { equipmentApi.listCategories().then(setCategories).catch(() => {}) }, [])

  // มาจากลิงก์แจ้งเตือน — คำขออาจไม่อยู่ในหน้า/ตัวกรองสถานะปัจจุบัน ดึงมาแสดงแยกแล้ว scroll ไปหา
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
      setSearchParams({}, { replace: true })
    }
  }, [highlightId, data.items])

  return (
    <div className="px-6 py-8">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-6">
        <h1 className="text-2xl font-light text-gray-800">ประวัติการยืมทั้งหมด</h1>
        <div className="flex flex-col sm:flex-row gap-3 sm:w-auto">
        <input
          type="text"
          value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(1) }}
          placeholder="ค้นหาชื่อ/รหัสนักศึกษา/ชื่ออุปกรณ์…"
          className="w-full sm:w-64 rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500"
        />
        <select
          value={overdueOnly ? 'overdue' : filterStatus}
          onChange={(e) => {
            const v = e.target.value
            setOverdueOnly(v === 'overdue')
            setFilterStatus(v === 'overdue' ? '' : v)
            setPage(1)
          }}
          className="w-full sm:w-48 shrink-0 rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500"
        >
          <option value="">ทุกสถานะ</option>
          {Object.entries(STATUS_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          <option value="overdue">เกินกำหนด</option>
        </select>
        <select value={filterCategory} onChange={(e) => { setFilterCategory(e.target.value); setPage(1) }}
          className="w-full sm:w-44 shrink-0 rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500">
          <option value="">ทุกหมวดหมู่</option>
          {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <select value={filterType} onChange={(e) => { setFilterType(e.target.value); setPage(1) }}
          className="w-full sm:w-40 shrink-0 rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500">
          <option value="">ทุกประเภท</option>
          <option value="durable">ครุภัณฑ์</option>
          <option value="material">วัสดุใช้ซ้ำ</option>
          <option value="consumable">วัสดุสิ้นเปลือง</option>
        </select>
        </div>
      </div>

      {loading ? (
        <EmptyState>กำลังโหลด…</EmptyState>
      ) : data.items.length === 0 ? (
        <EmptyState>ไม่พบรายการ</EmptyState>
      ) : (
        <div className="space-y-3">
          {data.items.map((req) => (
            <div key={req.id} ref={req.id === highlightId ? highlightRef : null}
              className={`bg-white rounded-xl border shadow-sm overflow-hidden ${req.id === highlightId ? 'border-primary-400 ring-2 ring-primary-100' : 'border-gray-200'}`}>
              <button
                onClick={() => setExpanded(expanded === req.id ? null : req.id)}
                className="w-full flex items-center justify-between px-4 py-3 hover:bg-gray-50 text-left"
              >
                <div className="flex flex-col gap-1 min-w-0">
                  <div className="flex items-center gap-3">
                    <span className="font-mono text-sm font-semibold text-gray-700">{req.request_code}</span>
                    <BorrowStatusBadge status={req.status} />
                    {req.is_overdue && <span className="text-xs px-2 py-0.5 rounded-full bg-red-100 text-red-600 font-medium">เกินกำหนด</span>}
                  </div>
                  <span className="text-xs text-gray-500 truncate">
                    ผู้ยืม: {req.student_name ?? '—'}{req.student_number ? ` (${req.student_number})` : ''}
                  </span>
                </div>
                <div className="flex items-center gap-3">
                  {req.due_date && <span className="text-xs text-gray-400">ครบ {formatDate(req.due_date)}</span>}
                  <span className="text-xs text-gray-400">{expanded === req.id ? '▲' : '▼'}</span>
                </div>
              </button>

              {expanded === req.id && (
                <div className="border-t px-4 py-3 space-y-3">
                  {req.pickup_at && (
                    <p className="text-sm text-blue-700">
                      นัดรับของ: {formatDateTime(req.pickup_at)}
                      {req.pickup_location ? ` ที่ ${req.pickup_location}` : ''}
                    </p>
                  )}
                  {req.purpose && <p className="text-sm text-gray-500">วัตถุประสงค์: {req.purpose}</p>}
                  {/* จ่ายของแล้ว (เฟส 11) — ลายเซ็นเปิดดูผ่าน endpoint ที่ตรวจสิทธิ์ ไม่มี URL สาธารณะ */}
                  {req.handover_at && (
                    <p className="text-sm text-gray-600">
                      จ่ายของแล้ว {formatDateTime(req.handover_at)}
                      {req.handover_by_name ? ` โดย ${req.handover_by_name}` : ''}
                      {req.signatures?.map((kind) => (
                        <button key={kind}
                          onClick={async () => openPdf(await borrowApi.downloadSignature(req.id, kind))}
                          className="ml-2 text-primary-600 hover:underline">
                          ✍ {SIGNATURE_LABEL[kind]}
                        </button>
                      ))}
                    </p>
                  )}
                  {/* ใบยืมที่ผู้ยืมเซ็นแล้วอัปโหลดมา — แอดมินต้องเปิดตรวจก่อนจ่ายของได้โดยไม่ต้องรอกระดาษ */}
                  {req.signed_form_file && (
                    <p className="text-sm">
                      <button onClick={async () => openPdf(await borrowApi.downloadSignedForm(req.id))}
                        className="text-emerald-700 hover:underline">
                        📎 ใบยืมที่เซ็นแล้ว ({formatDateTime(req.signed_form_at)})
                      </button>
                    </p>
                  )}

                  <div className="rounded-lg border border-gray-100 overflow-hidden divide-y divide-gray-100">
                    {req.items.map((item) => {
                      const isConsumable = item.item_type_snapshot === 'consumable'
                      return (
                      <div key={item.id} className="flex items-start justify-between px-3 py-2 text-sm gap-2">
                        <div className="min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-gray-700">{item.equipment_name ?? item.equipment_id}</span>
                            <span className="text-gray-400">×{item.quantity}</span>
                            {isConsumable && <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-50 text-amber-600">วัสดุสิ้นเปลือง</span>}
                            {item.returned ? (
                              <span className={`text-xs ${['ok', 'returned_full'].includes(item.condition_on_return) ? 'text-green-600' : 'text-red-500'}`}>
                                {CONDITION_LABEL[item.condition_on_return] ?? 'สรุปแล้ว'}
                              </span>
                            ) : (
                              req.status === 'approved' && <span className="text-xs text-primary-500">{isConsumable ? 'เบิกแล้ว (รอสรุป)' : 'ยังไม่คืน'}</span>
                            )}
                            {!item.returned && item.return_requested && (
                              <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700 font-medium">
                                นัดคืน {item.return_appoint_at ? formatDateTime(item.return_appoint_at) : 'แล้ว'}
                                {item.return_appoint_location ? ` · ${item.return_appoint_location}` : ''}
                              </span>
                            )}
                            {/* รายการที่ได้ต่อเวลาแล้วมีวันครบกำหนดของตัวเอง ต่างจากวันของทั้งคำขอที่หัวแถว */}
                            {item.extended_due_date && !item.returned ? (
                              <span className="text-xs font-medium text-green-700">
                                กำหนดคืนใหม่ {formatDate(item.extended_due_date)}
                              </span>
                            ) : (
                              !item.returned && hasOwnDueDate(item, req) && (
                                <span className="text-xs font-medium text-gray-600">
                                  คืน {formatDate(itemDueDate(item, req))}
                                </span>
                              )
                            )}
                            {item.item_status === 'rejected' && (
                              <span className="text-xs text-red-500">
                                ไม่อนุมัติ{item.rejection_reason ? `: ${item.rejection_reason}` : ''}
                              </span>
                            )}
                          </div>
                          {item.damage_note && <p className="text-xs text-gray-400 mt-0.5">หมายเหตุ: {item.damage_note}</p>}
                          {item.damage_photo_urls?.length > 0 && (
                            <div className="mt-1 flex flex-wrap gap-1.5">
                              {item.damage_photo_urls.map((url) => (
                                <a key={url} href={imgSrc(url)} target="_blank" rel="noreferrer">
                                  <img src={imgSrc(url)} alt="ความเสียหาย" className="w-12 h-12 rounded object-cover border" />
                                </a>
                              ))}
                            </div>
                          )}
                        </div>
                        {req.status === 'approved' && !item.returned && item.item_status !== 'rejected' && (
                          <button
                            onClick={() => setReturnTarget({ requestId: req.id, item, req })}
                            className="shrink-0 text-xs rounded-lg bg-primary-50 text-primary-600 px-3 py-1 hover:bg-primary-100 font-medium"
                          >
                            {isConsumable ? 'สรุปผล' : 'รับคืน'}
                          </button>
                        )}
                      </div>
                    )})}
                  </div>

                  <div className="flex items-center gap-4 pt-1">
                    {/* จ่ายของ + เซ็นรับบนหน้าจอ (เฟส 11) — ไม่บังคับ แต่ถ้าทำแล้วลายเซ็นจะขึ้นบนใบยืม */}
                    {req.status === 'approved' && !req.signatures?.includes('handover_borrower') && (
                      <button
                        onClick={() => setSignTarget({ id: req.id, code: req.request_code, mode: 'handover' })}
                        className="text-sm rounded-lg bg-primary-50 text-primary-700 px-3 py-1 hover:bg-primary-100 font-medium border border-primary-200"
                      >
                        จ่ายของ + เซ็นรับ
                      </button>
                    )}
                    {req.items?.some((i) => i.returned) && !req.signatures?.includes('return_borrower') && (
                      <button
                        onClick={() => setSignTarget({ id: req.id, code: req.request_code, mode: 'return' })}
                        className="text-sm rounded-lg bg-emerald-50 text-emerald-700 px-3 py-1 hover:bg-emerald-100 font-medium border border-emerald-200"
                      >
                        เซ็นรับคืน
                      </button>
                    )}
                    {req.status === 'approved' && req.items.some((i) => !i.returned && i.item_type_snapshot === 'durable') && (
                      <button
                        onClick={() => setConfirmDelete({ id: req.id, code: req.request_code, action: 'returnAll' })}
                        className="text-sm rounded-lg bg-green-50 text-green-700 px-3 py-1 hover:bg-green-100 font-medium border border-green-200"
                      >
                        รับคืนครุภัณฑ์ทั้งหมด
                      </button>
                    )}
                    <button
                      onClick={async () => openPdf(await borrowApi.downloadPdf(req.id))}
                      className="text-sm text-primary-600 hover:underline"
                    >
                      {req.status === 'pending' ? 'ดูใบร่างคำขอ' : 'ดูใบยืม'}
                    </button>
                    {req.items?.some((i) => i.returned) && (
                      <button
                        onClick={async () => openPdf(await borrowApi.downloadReturnPdf(req.id))}
                        className="text-sm text-emerald-600 hover:underline"
                      >
                        ดูใบรับคืน
                      </button>
                    )}
                    {['completed', 'rejected', 'cancelled'].includes(req.status) && (
                      <button
                        onClick={() => setConfirmDelete({ id: req.id, code: req.request_code, action: 'delete' })}
                        className="text-sm text-red-500 hover:underline ml-auto"
                      >
                        ลบประวัติ
                      </button>
                    )}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <Pagination page={page} total={data.total} pageSize={20} onChange={setPage} />

      {signTarget && (
        <SignatureModal
          requestId={signTarget.id}
          requestCode={signTarget.code}
          mode={signTarget.mode}
          onClose={() => setSignTarget(null)}
          onDone={() => { setSignTarget(null); load() }}
        />
      )}

      {returnTarget && (
        <ReturnModal
          requestId={returnTarget.requestId}
          item={returnTarget.item}
          req={returnTarget.req}
          onClose={() => setReturnTarget(null)}
          onDone={() => { setReturnTarget(null); load() }}
        />
      )}

      {confirmDelete && (
        <ConfirmModal
          title={confirmDelete.action === 'delete' ? 'ลบประวัติการยืม' : 'รับคืนทั้งหมด'}
          message={confirmDelete.action === 'delete'
            ? `ลบประวัติ "${confirmDelete.code}" ถาวร?\nข้อมูลจะหายไปและไม่สามารถกู้คืนได้`
            : `รับคืนครุภัณฑ์ทุกชิ้นในคำขอ "${confirmDelete.code}" (สภาพปกติทั้งหมด)?\nวัสดุสิ้นเปลืองต้องสรุปผลทีละชิ้น`
          }
          confirmLabel={confirmDelete.action === 'delete' ? 'ลบถาวร' : 'ยืนยันรับคืน'}
          danger={confirmDelete.action === 'delete'}
          onConfirm={async () => {
            const { id, action } = confirmDelete
            setConfirmDelete(null)
            if (action === 'delete') await borrowApi.deleteRequest(id)
            else await borrowApi.returnAll(id)
            load()
          }}
          onCancel={() => setConfirmDelete(null)}
        />
      )}
    </div>
  )
}
