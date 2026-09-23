import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { borrowApi } from '../../api/borrowApi.js'
import { equipmentApi } from '../../api/equipmentApi.js'
import { openPdf } from '../../utils/openPdf.js'
import { formatDate, formatDateTime } from '../../utils/formatDate.js'
import { itemDueDate, hasOwnDueDate, overdueDays, maxOverdueDays } from '../../utils/dueDate.js'
import { FINE_STATUS, fineMoney } from '../../utils/fine.js'
import Pagination from '../../components/common/Pagination.jsx'
import BorrowStatusBadge, { STATUS_LABEL } from '../../components/borrow/BorrowStatusBadge.jsx'
import { RenewModal } from '../../components/borrow/RenewModal.jsx'
import { ReturnAppointModal } from '../../components/borrow/ReturnAppointModal.jsx'
import EmptyState from '../../components/common/EmptyState.jsx'
import ReasonModal, { CANCEL_REASONS } from '../../components/common/ReasonModal.jsx'
import { SIGNATURE_LABEL } from '../../components/borrow/SignatureModal.jsx'

const ITEM_CONDITION_LABEL = {
  ok: 'คืนแล้ว', damaged: 'เสียหาย', lost: 'สูญหาย',
  returned_full: 'คืนครบ', used_up: 'ใช้หมด', discarded: 'เสียหาย/ทิ้ง',
}

export default function MyBorrowsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const highlightId = searchParams.get('request')
  const [data, setData] = useState({ items: [], total: 0 })
  const [page, setPage] = useState(1)
  const [expanded, setExpanded] = useState(() => new Set(highlightId ? [highlightId] : []))
  const [loading, setLoading] = useState(true)
  const [selectedItems, setSelectedItems] = useState(new Set())
  const [renewTarget, setRenewTarget] = useState(null) // { reqId, item } — ขอต่อเวลา
  const [returnTarget, setReturnTarget] = useState(null) // { reqId, itemIds } — นัดคืน
  const [uploadingId, setUploadingId] = useState(null) // คำขอที่กำลังอัปโหลดใบยืมที่เซ็นแล้ว
  const [filterStatus, setFilterStatus] = useState('')
  const [filterCategory, setFilterCategory] = useState('')
  const [filterType, setFilterType] = useState('')
  const [categories, setCategories] = useState([])
  const highlightRef = useRef(null)
  // เปิดแถว "approved" ให้อัตโนมัติแค่ตอนโหลดข้อมูลครั้งแรก — poll รอบถัดไปจะไม่ทับแถวที่ผู้ใช้ยุบเอง
  const autoExpandedRef = useRef(false)

  // showLoading=false ตอน poll พื้นหลัง — เดิม setLoading(true) ทุกรอบทำหน้าทั้งหมดสลับไปเป็น
  // "กำลังโหลด…" ทุก 4 วิแล้วกลับมา ผู้ใช้เห็นเป็นจอกระพริบ (mirror BorrowRequestsPage.jsx, commit 06f2a09)
  const load = (showLoading = false) => {
    if (showLoading) setLoading(true)
    // own_only=true: no-op สำหรับนักศึกษา (backend กรองของตัวเองอยู่แล้ว) แต่จำเป็นเมื่อหน้านี้ถูก mount
    // ที่ /admin/my-borrows โดย admin กัน admin เห็นคำขอของทุกคน
    borrowApi.list({
      page, page_size: 10, own_only: true,
      status: filterStatus || undefined,
      category_id: filterCategory || undefined,
      item_type: filterType || undefined,
    }).then((d) => {
      setData(d)
      if (!autoExpandedRef.current) {
        autoExpandedRef.current = true
        setExpanded((prev) => {
          const next = new Set(prev)
          d.items.filter((r) => r.status === 'approved').forEach((r) => next.add(r.id))
          return next
        })
      }
    }).finally(() => { if (showLoading) setLoading(false) })
  }

  // poll ทุก 4 วิ mirror BorrowRequestsPage.jsx/NotificationBell.jsx — เห็นสถานะที่แอดมินอัปเดตแล้ว
  // (อนุมัติ/ปฏิเสธ/รับคืน) เองอัตโนมัติ ไม่ต้องกด refresh เอง — หยุด poll ระหว่าง RenewModal เปิดอยู่ กันโดน
  // re-render ทับตอนนักศึกษากำลังกรอกฟอร์ม
  useEffect(() => {
    if (renewTarget) return
    load(true)
    const id = setInterval(() => load(false), 4000)
    return () => clearInterval(id)
  }, [page, renewTarget, filterStatus, filterCategory, filterType])

  // หมวดหมู่โหลดครั้งเดียว — ใช้เติมตัวเลือกใน filter เท่านั้น ไม่ต้อง poll ตามรายการ
  useEffect(() => { equipmentApi.listCategories().then(setCategories).catch(() => {}) }, [])

  // มาจากลิงก์แจ้งเตือน — คำขอที่ต้องการอาจไม่อยู่ในหน้าปัจจุบันที่โหลดมา (มีแบ่งหน้า)
  // ดึงมาแสดงแยกต่างหากแล้ว scroll ไปหาเลย ไม่ต้องเดาว่าอยู่หน้าไหน
  useEffect(() => {
    if (!highlightId) return
    borrowApi.get(highlightId).then((req) => {
      setData((d) => (d.items.some((i) => i.id === req.id) ? d : { ...d, items: [req, ...d.items] }))
      setExpanded((prev) => new Set(prev).add(req.id))
    }).catch(() => {})
  }, [highlightId])

  useEffect(() => {
    if (highlightId && highlightRef.current) {
      highlightRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' })
      setSearchParams({}, { replace: true }) // เคลียร์ query กันค้างตอน refresh/แชร์ลิงก์ซ้ำ
    }
  }, [highlightId, data.items])

  const toggleExpand = (id) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
    setSelectedItems(new Set())
  }

  // ยกเลิกคำขอต้องมีเหตุผล (8 ก.ย. 69) — ของถูกกันไว้ให้แล้ว คนอื่นรอคิวอยู่ ต้องตอบได้ว่าทำไมถึงยกเลิก
  const [cancelTarget, setCancelTarget] = useState(null) // คำขอที่กำลังจะยกเลิก

  const toggleSelect = (itemId) => {
    setSelectedItems((prev) => {
      const next = new Set(prev)
      if (next.has(itemId)) next.delete(itemId)
      else next.add(itemId)
      return next
    })
  }

  // แจ้งขอคืน = เปิดโมดัลนัดวัน-เวลา-สถานที่ (บังคับตั้งแต่เฟส 4) ไม่ใช่ confirm เฉย ๆ อีกต่อไป
  const returnDone = () => {
    setReturnTarget(null)
    setSelectedItems(new Set())
    load(true)
  }

  // อัปโหลดใบยืมที่เซ็นแล้ว — ไฟล์ล่าสุดไฟล์เดียวต่อคำขอ อัปใหม่ = ทับของเดิม
  const uploadSignedForm = async (reqId, file) => {
    if (!file) return
    setUploadingId(reqId)
    try {
      await borrowApi.uploadSignedForm(reqId, file)
      load(true)
    } catch (e) {
      alert(e.response?.data?.detail ?? 'อัปโหลดไม่สำเร็จ')
    } finally {
      setUploadingId(null)
    }
  }

  const viewPdf = async (id) => openPdf(await borrowApi.downloadPdf(id))
  // ใบเซ็นเก็บในโฟลเดอร์ที่ไม่ได้เสิร์ฟสาธารณะ ต้องดึงผ่าน API ที่ตรวจสิทธิ์แล้วเปิดจาก blob
  const viewSignedForm = async (id) => openPdf(await borrowApi.downloadSignedForm(id))
  const viewReturnPdf = async (id) => openPdf(await borrowApi.downloadReturnPdf(id))
  const viewSignature = async (id, kind) => openPdf(await borrowApi.downloadSignature(id, kind))

  return (
    <div className="px-4 sm:px-6 py-8">
      <h1 className="text-2xl font-light text-gray-800 mb-4">คำขอยืมของฉัน</h1>

      {/* กรองที่ backend ไม่ใช่ในหน้านี้ — รายการถูกแบ่งหน้า กรองฝั่ง client จะได้ผลแค่หน้าที่โหลดมาแล้ว */}
      <div className="flex flex-col sm:flex-row gap-3 mb-4">
        <select value={filterStatus} onChange={(e) => { setFilterStatus(e.target.value); setPage(1) }}
          className="w-full sm:w-40 rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500">
          <option value="">ทุกสถานะ</option>
          {Object.entries(STATUS_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <select value={filterCategory} onChange={(e) => { setFilterCategory(e.target.value); setPage(1) }}
          className="w-full sm:w-44 rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500">
          <option value="">ทุกหมวดหมู่</option>
          {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <select value={filterType} onChange={(e) => { setFilterType(e.target.value); setPage(1) }}
          className="w-full sm:w-40 rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500">
          <option value="">ทุกประเภท</option>
          <option value="durable">ครุภัณฑ์</option>
          <option value="material">วัสดุใช้ซ้ำ</option>
          <option value="consumable">วัสดุสิ้นเปลือง</option>
        </select>
      </div>

      {loading ? (
        <EmptyState>กำลังโหลด…</EmptyState>
      ) : data.items.length === 0 ? (
        <EmptyState>{filterStatus || filterCategory || filterType ? 'ไม่พบคำขอที่ตรงกับตัวกรอง' : 'ยังไม่มีคำขอยืม'}</EmptyState>
      ) : (
        <div className="space-y-3">
          {data.items.map((req) => {
          const selectableIds = req.status === 'approved'
            ? req.items.filter((i) => !i.returned && !i.return_requested && i.item_status !== 'rejected').map((i) => i.id)
            : []
          const allSelected = selectableIds.length > 0 && selectableIds.every((id) => selectedItems.has(id))
          const lateDays = maxOverdueDays(req)
          // เวลาอัปเดตล่าสุดของใบคืน = ชิ้นสุดท้ายที่ถูกรับคืนจริง (ผู้ยืมต้องรู้ว่าใบสะท้อนถึงเมื่อไหร่)
          const lastReturnAt = req.items.filter((i) => i.returned_at)
            .map((i) => i.returned_at).sort().slice(-1)[0]
          return (
            <div key={req.id} ref={req.id === highlightId ? highlightRef : null}
              className={`bg-white rounded-xl border shadow-sm overflow-hidden ${req.id === highlightId ? 'border-primary-400 ring-2 ring-primary-100' : 'border-gray-200'}`}>
              {/* Header row */}
              <button
                onClick={() => toggleExpand(req.id)}
                className="w-full flex items-center justify-between px-4 py-3 hover:bg-gray-50 text-left"
              >
                <div className="flex flex-wrap items-center gap-3 min-w-0">
                  <span className="font-mono text-sm font-semibold text-gray-700">{req.request_code}</span>
                  <BorrowStatusBadge status={req.status} />
                  {/* บอกจำนวนวันที่เกิน ไม่ใช่แค่ "เกินกำหนด" — 1 วันกับ 30 วันคนละเรื่องกันสำหรับคนที่ต้องรีบคืน */}
                  {lateDays > 0 && (
                    <span className="text-xs px-2 py-0.5 rounded-full bg-red-100 text-red-700 font-medium">
                      เกินกำหนด {lateDays} วัน
                    </span>
                  )}
                  <span className="text-xs text-gray-400 truncate">
                    {req.items.length} รายการ{req.purpose ? ` · ${req.purpose}` : ''}
                  </span>
                </div>
                <div className="flex items-center gap-3 shrink-0">
                  {req.due_date && (
                    <span className="text-xs text-gray-400">ครบ {formatDate(req.due_date)}</span>
                  )}
                  <span className="text-gray-400 text-xs">{expanded.has(req.id) ? '▲' : '▼'}</span>
                </div>
              </button>

              {/* Expanded detail */}
              {expanded.has(req.id) && (
                <div className="border-t px-4 py-3 space-y-3">
                  {req.pickup_at && req.status === 'approved' && (
                    <div className="rounded-lg bg-blue-50 border border-blue-100 px-3 py-2 text-sm text-blue-800">
                      <b>นัดรับของ:</b> {formatDateTime(req.pickup_at)}
                      {req.pickup_location ? ` ที่ ${req.pickup_location}` : ''}
                      {req.pickup_note && <p className="text-xs text-blue-600 mt-0.5">{req.pickup_note}</p>}
                    </div>
                  )}
                  {req.status === 'approved' && !req.signed_form_file && (
                    <p className="rounded-lg bg-amber-50 border border-amber-200 px-3 py-2 text-xs text-amber-800">
                      อย่าลืม <b>ปริ้นใบยืมไปลงลายเซ็น</b> แล้วนำมาแสดงตอนรับของ
                      หรืออัปโหลดไฟล์ที่เซ็นแล้วเข้าระบบ (PDF/รูปถ่าย ไม่เกิน 10MB) ที่ส่วน "เอกสาร" ด้านล่าง
                    </p>
                  )}
                  {req.rejection_reason && (
                    <p className="text-sm text-red-600">เหตุผลที่ปฏิเสธ: {req.rejection_reason}</p>
                  )}
                  {req.cancel_reason && (
                    <p className="text-sm text-gray-500">เหตุผลที่ยกเลิก: {req.cancel_reason}</p>
                  )}

                  {/* ── รายการ ── */}
                  <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">รายการอุปกรณ์</p>
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
                              <span className="ml-2 text-xs text-purple-600">
                                รอ Admin ยืนยันคืน{item.return_appoint_at ? ` · นัด ${formatDateTime(item.return_appoint_at)}` : ''}
                                {item.return_appoint_location ? ` ที่ ${item.return_appoint_location}` : ''}
                              </span>
                            ) : (
                              req.status === 'approved' && item.item_type_snapshot === 'consumable' &&
                              <span className="ml-2 text-xs text-primary-500">เบิกแล้ว (รอสรุป)</span>
                            )}
                            {item.renewed_count > 0 && (
                              <span className="ml-2 text-xs text-primary-500">ต่อเวลา {item.renewed_count}×</span>
                            )}
                            {/* วันครบกำหนดใหม่หลังได้ต่อเวลา — backend ส่งค่านี้มาตลอดแต่ไม่เคยถูกแสดง
                                ผู้ยืมจึงเห็นแต่วันเดิมของทั้งคำขอ ไม่รู้ว่าจริง ๆ ต้องคืนวันไหน */}
                            {item.extended_due_date && !item.returned ? (
                              <span className="ml-2 text-xs font-medium text-green-700">
                                กำหนดคืนใหม่ {formatDate(item.extended_due_date)}
                              </span>
                            ) : (
                              /* วันคืนเฉพาะชิ้นนี้ (ไม่ตรงกับวันของทั้งใบที่หัวแถว) — ไม่โชว์ก็เท่ากับบอกวันผิด */
                              !item.returned && hasOwnDueDate(item, req) && (
                                <span className="ml-2 text-xs font-medium text-gray-600">
                                  คืน {formatDate(itemDueDate(item, req))}
                                </span>
                              )
                            )}
                            {/* เกินกำหนดรายชิ้น (8 ก.ย. 69) — ต้องรู้ว่า "ชิ้นไหน" ที่เกิน ไม่ใช่แค่ทั้งใบเกิน */}
                            {overdueDays(item, req) > 0 && (
                              <span className="ml-2 text-xs font-semibold px-1.5 py-0.5 rounded bg-red-100 text-red-700">
                                เกินกำหนด {overdueDays(item, req)} วัน
                              </span>
                            )}
                            {item.item_status === 'rejected' && (
                              <span className="ml-2 text-xs text-red-500">
                                ไม่อนุมัติ{item.rejection_reason ? `: ${item.rejection_reason}` : ''}
                              </span>
                            )}
                            {item.renew_requested ? (
                              <span className="ml-2 text-xs text-amber-600">
                                รอ Admin อนุมัติต่อเวลา ({formatDate(item.renew_requested_date)})
                              </span>
                            ) : item.renew_rejected_reason && (
                              <span className="ml-2 text-xs text-red-500">ต่อเวลาถูกปฏิเสธ: {item.renew_rejected_reason}</span>
                            )}
                            {/* ค่าปรับของตัวเองพร้อมที่มา — ต้องรู้ตั้งแต่ในระบบ ไม่ใช่รู้ตอนไปถึงเคาน์เตอร์ */}
                            {item.fine_status !== 'none' && (
                              <span className={`ml-2 text-xs font-medium px-1.5 py-0.5 rounded ${FINE_STATUS[item.fine_status]?.cls}`}>
                                ค่าปรับ {fineMoney(item.fine_total)} บาท
                                {item.fine_days_late > 0 && ` (ล่าช้า ${item.fine_days_late} วัน)`}
                                {' · '}{FINE_STATUS[item.fine_status]?.label}
                                {item.fine_waiver_name && ` โดย ${item.fine_waiver_name}`}
                              </span>
                            )}
                          </div>
                        </div>
                        {req.status === 'approved' && !item.returned && !item.renew_requested
                          && item.item_status !== 'rejected' && (
                          <button
                            onClick={() => setRenewTarget({ reqId: req.id, item })}
                            className="text-xs text-primary-600 hover:underline"
                          >
                            ต่อเวลา
                          </button>
                        )}
                      </div>
                    ))}
                  </div>

                  {/* ── การจัดการ ── */}
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
                          onClick={() => setReturnTarget({
                            reqId: req.id, itemIds: [...selectedItems], location: req.pickup_location,
                          })}
                          className="text-xs font-semibold text-purple-600 hover:underline"
                        >
                          แจ้งขอคืนที่เลือก ({selectedItems.size})
                        </button>
                      )}
                    </div>
                  )}

                  {/* ── เอกสาร ── ใบยืมกับใบคืนคนละบรรทัด พร้อมบอกว่าฉบับที่เห็นสะท้อนถึงเมื่อไหร่ */}
                  <div className="rounded-lg border border-gray-200 divide-y divide-gray-100">
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2">
                      {/* อัปโหลดใบที่เซ็นแล้ว = ใบนั้นแทนที่ใบยืมเปล่าไปเลย (8 ก.ย. 69) ไม่ต้องมี 2 ปุ่มให้เลือกผิด */}
                      {req.signed_form_file ? (
                        <>
                          <button onClick={() => viewSignedForm(req.id)}
                            className="text-sm font-medium text-emerald-700 hover:underline">
                            ดูใบยืมที่เซ็นแล้ว
                          </button>
                          <span className="text-xs text-gray-400">
                            อัปโหลดเมื่อ {formatDateTime(req.signed_form_at)}
                          </span>
                          <button onClick={() => viewPdf(req.id)}
                            className="text-xs text-gray-400 hover:underline">ดูใบเปล่าที่ระบบออกให้</button>
                        </>
                      ) : (
                        <button onClick={() => viewPdf(req.id)}
                          className="text-sm font-medium text-primary-600 hover:underline">
                          {req.status === 'pending' ? 'ดูใบร่างคำขอ'
                            : req.signatures?.includes('handover_borrower') ? 'ดูใบยืม (เซ็นบนหน้าจอแล้ว)' : 'ดูใบยืม (ยังไม่ได้เซ็น)'}
                        </button>
                      )}
                      {req.status === 'approved' && (
                        <label className={`ml-auto rounded-full border border-gray-300 px-3 py-1 text-xs font-medium
                          ${uploadingId === req.id ? 'opacity-50' : 'cursor-pointer hover:bg-gray-50'}`}>
                          {uploadingId === req.id ? 'กำลังอัปโหลด…'
                            : req.signed_form_file ? 'อัปโหลดใบใหม่ (ทับของเดิม)' : 'อัปโหลดใบที่เซ็นแล้ว'}
                          <input type="file" accept=".pdf,image/*" className="hidden"
                            disabled={uploadingId === req.id}
                            onChange={(e) => { uploadSignedForm(req.id, e.target.files[0]); e.target.value = '' }} />
                        </label>
                      )}
                    </div>
                    {/* ลายเซ็นบนหน้าจอ (เฟส 11) — ผู้ยืมเปิดดูของตัวเองได้ ผ่าน endpoint ที่ตรวจสิทธิ์ + ลง audit */}
                    {req.signatures?.length > 0 && (
                      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2">
                        {req.handover_at && (
                          <span className="text-xs text-gray-500">
                            รับของแล้ว {formatDateTime(req.handover_at)}{req.handover_by_name ? ` · ผู้จ่าย ${req.handover_by_name}` : ''}
                          </span>
                        )}
                        {req.signatures.map((kind) => (
                          <button key={kind} onClick={() => viewSignature(req.id, kind)}
                            className="text-sm text-primary-600 hover:underline">
                            ✍ {SIGNATURE_LABEL[kind]}
                          </button>
                        ))}
                      </div>
                    )}
                    {req.items.some((i) => i.returned) && (
                      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2">
                        <button onClick={() => viewReturnPdf(req.id)}
                          className="text-sm font-medium text-emerald-600 hover:underline">
                          ดูใบรับคืน
                        </button>
                        {lastReturnAt && (
                          <span className="text-xs text-gray-400">
                            อัปเดตล่าสุด {formatDateTime(lastReturnAt)} (ของชิ้นล่าสุดที่รับคืน)
                          </span>
                        )}
                      </div>
                    )}
                  </div>

                  {/* ── การจัดการ ── */}
                  {req.status === 'pending' && (
                    <div className="flex gap-2 pt-1">
                      <button onClick={() => setCancelTarget(req)}
                        className="text-sm text-red-600 hover:underline">
                        ยกเลิกคำขอ
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>
          )})}
        </div>
      )}

      <Pagination page={page} total={data.total} pageSize={10} onChange={setPage} />

      {renewTarget && (
        <RenewModal
          item={renewTarget.item}
          requestId={renewTarget.reqId}
          onClose={() => setRenewTarget(null)}
          onDone={() => { setRenewTarget(null); load(true) }}
        />
      )}

      {cancelTarget && (
        <ReasonModal
          title="ยกเลิกคำขอยืม"
          message={`ยกเลิกคำขอ ${cancelTarget.request_code}?\nอุปกรณ์ที่กันไว้ให้จะถูกปล่อยคืนให้คนอื่นยืมได้ทันที`}
          presets={CANCEL_REASONS}
          confirmLabel="ยกเลิกคำขอ"
          danger
          onCancel={() => setCancelTarget(null)}
          onConfirm={async (reason) => {
            await borrowApi.cancel(cancelTarget.id, reason)
            setCancelTarget(null)
            load(true)
          }}
        />
      )}

      {returnTarget && (
        <ReturnAppointModal
          requestId={returnTarget.reqId}
          itemIds={returnTarget.itemIds}
          defaultLocation={returnTarget.location}
          onClose={() => setReturnTarget(null)}
          onDone={returnDone}
        />
      )}
    </div>
  )
}
