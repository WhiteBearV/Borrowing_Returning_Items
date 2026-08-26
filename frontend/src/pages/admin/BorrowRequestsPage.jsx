import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { borrowApi } from '../../api/borrowApi.js'
import Pagination from '../../components/common/Pagination.jsx'
import EmptyState from '../../components/common/EmptyState.jsx'
import { ReturnModal } from '../../components/borrow/ReturnModal.jsx'
import { openPdf } from '../../utils/openPdf.js'
import { formatDate } from '../../utils/formatDate.js'

// คำขอต้อง "ทำอะไรสักอย่าง" ถ้ายัง pending (รออนุมัติ) หรือ approved ที่มี item แจ้งขอคืนแล้ว/ขอต่อเวลาแล้ว
const needsAttentionCheck = (req) =>
  req.status === 'pending' ||
  req.items.some((i) => (i.return_requested && !i.returned) || i.renew_requested)

export default function BorrowRequestsPage() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const highlightId = searchParams.get('request')
  const [data, setData] = useState({ items: [], total: 0 })
  const [page, setPage] = useState(1)
  const [expanded, setExpanded] = useState(highlightId)
  const [rejectId, setRejectId] = useState(null)
  const [rejectReason, setRejectReason] = useState('')
  const [returnTarget, setReturnTarget] = useState(null) // { requestId, item }
  const [renewRejectTarget, setRenewRejectTarget] = useState(null) // { requestId, item }
  const [renewRejectReason, setRenewRejectReason] = useState('')
  const [loading, setLoading] = useState(true)
  const [actionError, setActionError] = useState('')
  const highlightRef = useRef(null)

  // showLoading=false ตอน poll พื้นหลัง — เดิม setLoading(true) ทุกรอบทำหน้าทั้งหมดสลับไปเป็น
  // "กำลังโหลด…" ทุก 4 วิแล้วกลับมา ผู้ใช้เห็นเป็นจอกระพริบ ทั้งที่ข้อมูลส่วนใหญ่ไม่เปลี่ยน
  const load = (showLoading = false) => {
    if (showLoading) setLoading(true)
    borrowApi.list({ needs_attention: true, page, page_size: 20 }).then(setData).finally(() => setLoading(false))
  }

  // poll ทุก 4 วิ mirror NotificationBell.jsx — หยุด poll ระหว่างมี modal เปิดอยู่ (reject/return)
  // กันโดน re-render ทับตอนแอดมินกำลังกรอกฟอร์ม (เช่น เลือกสภาพ/อัปโหลดรูปค้างอยู่)
  useEffect(() => {
    if (rejectId || returnTarget || renewRejectTarget) return
    load(true)
    const id = setInterval(() => load(false), 4000)
    return () => clearInterval(id)
  }, [page, rejectId, returnTarget, renewRejectTarget])

  // มาจากลิงก์แจ้งเตือน "คำขอใหม่"/"แจ้งขอคืน" — ถ้าคำขอถูกจัดการไปแล้ว (อนุมัติ/ปฏิเสธ/รับคืนครบ) จนไม่ต้อง
  // ทำอะไรอีกแล้ว หน้านี้จะไม่มีให้ดู ส่งไปหน้าประวัติทั้งหมดแทน
  useEffect(() => {
    if (!highlightId) return
    borrowApi.get(highlightId).then((req) => {
      if (!needsAttentionCheck(req)) {
        navigate(`/admin/borrows?request=${highlightId}`, { replace: true })
        return
      }
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

  const approveRenew = async (reqId, itemId) => {
    setActionError('')
    try {
      await borrowApi.renewApprove(reqId, itemId)
      load()
    } catch (err) {
      setActionError(err?.response?.data?.detail ?? 'อนุมัติต่อเวลาไม่สำเร็จ')
    }
  }

  const rejectRenew = async () => {
    if (!renewRejectReason.trim()) return
    setActionError('')
    try {
      await borrowApi.renewReject(renewRejectTarget.requestId, renewRejectTarget.item.id, renewRejectReason)
      setRenewRejectTarget(null)
      setRenewRejectReason('')
      load()
    } catch (err) {
      setActionError(err?.response?.data?.detail ?? 'ปฏิเสธต่อเวลาไม่สำเร็จ')
    }
  }

  const pendingItems = data.items.filter((r) => r.status === 'pending')
  // เฉพาะคำขอที่มี item แจ้งขอคืนแล้วจริง — ไม่ใช่แค่ "ไม่ pending" เฉย ๆ เพราะตอนนี้ needs_attention
  // รวมคำขอต่อเวลาด้วย ถ้ายังใช้ status !== 'pending' เฉย ๆ คำขอที่มีแค่ renew_requested (ไม่มี return_requested)
  // จะโผล่มาในหมวด "แจ้งขอคืน" แบบว่างเปล่า
  const returnItems = data.items.filter((r) => r.items.some((i) => i.return_requested && !i.returned))
  const renewItems = data.items.filter((r) => r.items.some((i) => i.renew_requested))

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-light text-gray-800 mb-6">อนุมัติคำขอ</h1>

      {actionError && (
        <div className="mb-4 rounded-lg bg-red-50 border border-red-200 px-4 py-2.5 text-sm text-red-600 flex justify-between gap-3">
          <span>{actionError}</span>
          <button onClick={() => setActionError('')} className="text-red-400 hover:text-red-600 leading-none">×</button>
        </div>
      )}

      {loading ? (
        <EmptyState>กำลังโหลด…</EmptyState>
      ) : data.items.length === 0 ? (
        <EmptyState>ไม่มีคำขอที่ต้องดำเนินการ</EmptyState>
      ) : (
        <div className="space-y-8">
          <section>
            <h2 className="mb-3 text-sm font-semibold text-gray-500">รออนุมัติ ({pendingItems.length})</h2>
            {pendingItems.length === 0 ? (
              <p className="text-sm text-gray-400">ไม่มีคำขอรออนุมัติ</p>
            ) : (
              <div className="space-y-3">
                {pendingItems.map((req) => (
                  <div key={req.id} ref={req.id === highlightId ? highlightRef : null}
                    className={`bg-white rounded-xl border shadow-sm overflow-hidden ${req.id === highlightId ? 'border-primary-400 ring-2 ring-primary-100' : 'border-gray-200'}`}>
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
                                {/* รหัสหน่วยเจาะจงยังไม่นิ่งจนกว่าจะอนุมัติ — โชว์เฉพาะคำขอที่ไม่ pending แล้ว */}
                                {item.equipment_code && req.status !== 'pending' && (
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
                            className="rounded-full border border-gray-300 px-4 py-1.5 text-sm font-semibold text-gray-700 hover:bg-gray-50"
                          >
                            ดูใบร่าง PDF
                          </button>
                          <button
                            onClick={() => approve(req.id)}
                            className="rounded-full bg-green-600 px-4 py-1.5 text-sm font-semibold text-white hover:bg-green-700"
                          >
                            อนุมัติ
                          </button>
                          <button
                            onClick={() => { setRejectId(req.id); setRejectReason('') }}
                            className="rounded-full border border-red-300 px-4 py-1.5 text-sm font-semibold text-red-600 hover:bg-red-50"
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
          </section>

          <section>
            <h2 className="mb-3 text-sm font-semibold text-gray-500">แจ้งขอคืน ({returnItems.length})</h2>
            {returnItems.length === 0 ? (
              <p className="text-sm text-gray-400">ไม่มีคำขอแจ้งขอคืน</p>
            ) : (
              <div className="space-y-3">
                {returnItems.map((req) => (
                  <div key={req.id} ref={req.id === highlightId ? highlightRef : null}
                    className={`bg-white rounded-xl border shadow-sm overflow-hidden ${req.id === highlightId ? 'border-primary-400 ring-2 ring-primary-100' : 'border-gray-200'}`}>
                    <button
                      onClick={() => setExpanded(expanded === req.id ? null : req.id)}
                      className="w-full flex items-center justify-between px-4 py-3 hover:bg-gray-50 text-left"
                    >
                      <div className="flex flex-col gap-1 min-w-0">
                        <div className="flex items-center gap-3">
                          <span className="font-mono text-sm font-semibold text-gray-700">{req.request_code}</span>
                          <span className="text-xs text-gray-500">ผู้ยืม: {req.student_name ?? '—'}</span>
                        </div>
                      </div>
                      <span className="text-xs text-gray-400">{expanded === req.id ? '▲' : '▼'}</span>
                    </button>

                    {expanded === req.id && (
                      <div className="border-t px-4 py-3 space-y-3">
                        <div className="rounded-lg border border-gray-100 overflow-hidden divide-y divide-gray-100">
                          {req.items.filter((i) => !i.returned).map((item) => {
                            const isConsumable = item.item_type_snapshot === 'consumable'
                            return (
                              <div key={item.id} className="flex items-center justify-between px-3 py-2 text-sm gap-2">
                                <div className="min-w-0">
                                  <span className="text-gray-700">{item.equipment_name ?? item.equipment_id}</span>
                                  <span className="ml-2 text-gray-400">×{item.quantity}</span>
                                  {item.return_requested && (
                                    <span className="ml-2 text-[10px] px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700 font-medium">
                                      นักศึกษาแจ้งขอคืนแล้ว
                                    </span>
                                  )}
                                </div>
                                <button
                                  onClick={() => setReturnTarget({ requestId: req.id, item })}
                                  className="shrink-0 text-xs rounded-lg bg-primary-50 text-primary-600 px-3 py-1 hover:bg-primary-100 font-medium"
                                >
                                  {isConsumable ? 'สรุปผล' : 'รับคืน'}
                                </button>
                              </div>
                            )
                          })}
                        </div>
                        <button
                          onClick={async () => openPdf(await borrowApi.downloadPdf(req.id))}
                          className="text-sm text-primary-600 hover:underline"
                        >
                          ดูใบยืม
                        </button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </section>

          <section>
            <h2 className="mb-3 text-sm font-semibold text-gray-500">รอต่อเวลา ({renewItems.length})</h2>
            {renewItems.length === 0 ? (
              <p className="text-sm text-gray-400">ไม่มีคำขอต่อเวลา</p>
            ) : (
              <div className="space-y-3">
                {renewItems.map((req) => (
                  <div key={req.id} ref={req.id === highlightId ? highlightRef : null}
                    className={`bg-white rounded-xl border shadow-sm overflow-hidden ${req.id === highlightId ? 'border-primary-400 ring-2 ring-primary-100' : 'border-gray-200'}`}>
                    <button
                      onClick={() => setExpanded(expanded === req.id ? null : req.id)}
                      className="w-full flex items-center justify-between px-4 py-3 hover:bg-gray-50 text-left"
                    >
                      <div className="flex flex-col gap-1 min-w-0">
                        <div className="flex items-center gap-3">
                          <span className="font-mono text-sm font-semibold text-gray-700">{req.request_code}</span>
                          <span className="text-xs text-gray-500">ผู้ยืม: {req.student_name ?? '—'}</span>
                        </div>
                      </div>
                      <span className="text-xs text-gray-400">{expanded === req.id ? '▲' : '▼'}</span>
                    </button>

                    {expanded === req.id && (
                      <div className="border-t px-4 py-3 space-y-3">
                        <div className="rounded-lg border border-gray-100 overflow-hidden divide-y divide-gray-100">
                          {req.items.filter((i) => i.renew_requested).map((item) => (
                            <div key={item.id} className="flex items-center justify-between px-3 py-2 text-sm gap-2">
                              <div className="min-w-0">
                                <span className="text-gray-700">{item.equipment_name ?? item.equipment_id}</span>
                                <p className="text-xs text-gray-400 mt-0.5">
                                  ขอเลื่อนถึง {formatDate(item.renew_requested_date)} — {item.renew_reason}
                                </p>
                              </div>
                              <div className="flex gap-2 shrink-0">
                                <button
                                  onClick={() => approveRenew(req.id, item.id)}
                                  className="text-xs rounded-lg bg-green-50 text-green-700 px-3 py-1 hover:bg-green-100 font-medium"
                                >
                                  อนุมัติ
                                </button>
                                <button
                                  onClick={() => { setRenewRejectTarget({ requestId: req.id, item }); setRenewRejectReason('') }}
                                  className="text-xs rounded-lg bg-red-50 text-red-600 px-3 py-1 hover:bg-red-100 font-medium"
                                >
                                  ปฏิเสธ
                                </button>
                              </div>
                            </div>
                          ))}
                        </div>
                        <button
                          onClick={async () => openPdf(await borrowApi.downloadPdf(req.id))}
                          className="text-sm text-primary-600 hover:underline"
                        >
                          ดูใบยืม
                        </button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>
      )}

      <Pagination page={page} total={data.total} pageSize={20} onChange={setPage} />

      {/* Reject modal */}
      {rejectId && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50 px-4">
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
              <button onClick={() => setRejectId(null)} className="flex-1 rounded-full border py-2 text-sm text-gray-600 hover:bg-gray-50">ยกเลิก</button>
              <button
                disabled={!rejectReason.trim()}
                onClick={reject}
                className="flex-1 rounded-full bg-red-600 py-2 text-sm font-semibold text-white hover:bg-red-700 disabled:opacity-50"
              >
                ยืนยันปฏิเสธ
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Reject renewal modal */}
      {renewRejectTarget && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50 px-4">
          <div className="bg-white rounded-2xl p-6 w-full max-w-sm shadow-xl">
            <h2 className="font-bold text-gray-800 mb-3">ระบุเหตุผลที่ปฏิเสธการต่อเวลา</h2>
            <textarea
              autoFocus
              rows={3}
              value={renewRejectReason}
              onChange={(e) => setRenewRejectReason(e.target.value)}
              placeholder="เหตุผล…"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-red-400 resize-none"
            />
            <div className="flex gap-3 mt-4">
              <button onClick={() => setRenewRejectTarget(null)} className="flex-1 rounded-full border py-2 text-sm text-gray-600 hover:bg-gray-50">ยกเลิก</button>
              <button
                disabled={!renewRejectReason.trim()}
                onClick={rejectRenew}
                className="flex-1 rounded-full bg-red-600 py-2 text-sm font-semibold text-white hover:bg-red-700 disabled:opacity-50"
              >
                ยืนยันปฏิเสธ
              </button>
            </div>
          </div>
        </div>
      )}

      {returnTarget && (
        <ReturnModal
          requestId={returnTarget.requestId}
          item={returnTarget.item}
          onClose={() => setReturnTarget(null)}
          onDone={() => { setReturnTarget(null); load() }}
        />
      )}
    </div>
  )
}
