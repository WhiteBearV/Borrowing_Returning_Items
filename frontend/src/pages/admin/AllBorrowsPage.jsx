import { useEffect, useState } from 'react'
import { borrowApi } from '../../api/borrowApi.js'
import { equipmentApi } from '../../api/equipmentApi.js'
import ConfirmModal from '../../components/common/ConfirmModal.jsx'
import Pagination from '../../components/common/Pagination.jsx'
import { openPdf } from '../../utils/openPdf.js'

const STATUS_STYLE = {
  pending: 'bg-yellow-100 text-yellow-700', approved: 'bg-blue-100 text-blue-700',
  rejected: 'bg-red-100 text-red-700', cancelled: 'bg-gray-100 text-gray-500',
  completed: 'bg-green-100 text-green-700',
}
const STATUS_LABEL = { pending: 'รออนุมัติ', approved: 'อนุมัติแล้ว', rejected: 'ปฏิเสธ', cancelled: 'ยกเลิก', completed: 'คืนครบ' }

// สถานะสรุปผลแยกตามชนิด + สถานะที่ต้องแนบรูป
const DURABLE_OPTIONS = [{ value: 'ok', label: 'ปกติ' }, { value: 'damaged', label: 'เสียหาย' }, { value: 'lost', label: 'สูญหาย' }]
const CONSUMABLE_OPTIONS = [{ value: 'returned_full', label: 'คืนครบ (ไม่ได้ใช้)' }, { value: 'used_up', label: 'ใช้หมด' }, { value: 'discarded', label: 'เสียหาย/ทิ้ง' }]
const PHOTO_REQUIRED = new Set(['damaged', 'lost', 'discarded'])
const CONDITION_LABEL = {
  ok: 'ปกติ', damaged: 'เสียหาย', lost: 'สูญหาย',
  returned_full: 'คืนครบ', used_up: 'ใช้หมด', discarded: 'เสียหาย/ทิ้ง',
}
const imgSrc = (url) => (url?.startsWith('/') ? `${import.meta.env.VITE_API_URL || 'http://localhost:8000'}${url}` : url)

function ReturnModal({ item, requestId, onClose, onDone }) {
  const isConsumable = item.item_type_snapshot === 'consumable'
  const options = isConsumable ? CONSUMABLE_OPTIONS : DURABLE_OPTIONS
  const [condition, setCondition] = useState(options[0].value)
  const [note, setNote] = useState('')
  const [photos, setPhotos] = useState([])
  const [uploading, setUploading] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const needPhoto = PHOTO_REQUIRED.has(condition)

  const uploadPhotos = async (e) => {
    const files = Array.from(e.target.files ?? [])
    if (!files.length) return
    setUploading(true)
    setError('')
    try {
      const results = await Promise.all(files.map((f) => equipmentApi.uploadImage(f)))
      setPhotos((p) => [...p, ...results.map((r) => r.image_url)])
    } catch (err) {
      setError(err.response?.data?.detail ?? 'อัปโหลดรูปไม่สำเร็จ')
    } finally {
      setUploading(false)
    }
  }

  const submit = async () => {
    if (needPhoto && photos.length === 0) {
      setError('กรุณาถ่าย/แนบรูปหลักฐานอย่างน้อย 1 รูป')
      return
    }
    setLoading(true)
    setError('')
    try {
      await borrowApi.returnItem(requestId, item.id, {
        condition_on_return: condition,
        damage_note: note || undefined,
        damage_photo_urls: photos.length ? photos : undefined,
      })
      onDone()
    } catch (err) {
      setError(err.response?.data?.detail ?? 'บันทึกไม่สำเร็จ')
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 px-4">
      <div className="bg-white rounded-2xl p-6 w-full max-w-sm shadow-xl space-y-4">
        <h2 className="font-bold text-gray-800">{isConsumable ? 'สรุปผลวัสดุ' : 'ยืนยันรับคืนอุปกรณ์'}</h2>
        <p className="text-sm text-gray-500">{item.equipment_name} ×{item.quantity}</p>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">{isConsumable ? 'ผลการใช้งาน' : 'สภาพอุปกรณ์'}</label>
          <select value={condition} onChange={(e) => setCondition(e.target.value)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500">
            {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
        {needPhoto && (
          <>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                รูปหลักฐานความเสียหาย <span className="text-red-500">*</span>
              </label>
              <input type="file" accept="image/*" capture="environment" multiple onChange={uploadPhotos} disabled={uploading}
                className="block w-full text-xs text-gray-500 file:mr-3 file:rounded-lg file:border-0 file:bg-blue-50 file:px-3 file:py-1.5 file:text-blue-600" />
              {uploading && <p className="mt-1 text-xs text-gray-400">กำลังอัปโหลด…</p>}
              {photos.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-2">
                  {photos.map((url, i) => (
                    <div key={url} className="relative">
                      <img src={imgSrc(url)} alt="" className="w-14 h-14 rounded-lg object-cover border" />
                      <button onClick={() => setPhotos((p) => p.filter((_, j) => j !== i))}
                        className="absolute -top-1.5 -right-1.5 bg-red-500 text-white rounded-full w-4 h-4 text-xs leading-none">×</button>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">บันทึกความเสียหาย</label>
              <textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="อธิบายความเสียหาย…" />
            </div>
          </>
        )}
        {error && <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>}
        <div className="flex gap-3">
          <button onClick={onClose} className="flex-1 rounded-lg border py-2 text-sm text-gray-600 hover:bg-gray-50">ยกเลิก</button>
          <button onClick={submit} disabled={loading || uploading}
            className="flex-1 rounded-lg bg-blue-600 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50">
            {loading ? 'กำลังบันทึก…' : 'ยืนยัน'}
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
  const [confirmDelete, setConfirmDelete] = useState(null) // { id, code }
  const [loading, setLoading] = useState(true)

  const load = () => {
    setLoading(true)
    borrowApi.list({ status: filterStatus || undefined, page, page_size: 20 }).then(setData).finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [filterStatus, page])

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-6">
        <h1 className="text-2xl font-bold text-gray-800">ประวัติการยืมทั้งหมด</h1>
        <select value={filterStatus} onChange={(e) => { setFilterStatus(e.target.value); setPage(1) }}
          className="w-full sm:w-48 shrink-0 rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500">
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
                <div className="flex flex-col gap-1 min-w-0">
                  <div className="flex items-center gap-3">
                    <span className="font-mono text-sm font-semibold text-gray-700">{req.request_code}</span>
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${STATUS_STYLE[req.status]}`}>{STATUS_LABEL[req.status]}</span>
                    {req.is_overdue && <span className="text-xs px-2 py-0.5 rounded-full bg-red-100 text-red-600 font-medium">เกินกำหนด</span>}
                  </div>
                  <span className="text-xs text-gray-500 truncate">
                    ผู้ยืม: {req.student_name ?? '—'}{req.student_number ? ` (${req.student_number})` : ''}
                  </span>
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
                    {req.items.map((item) => {
                      const isConsumable = item.item_type_snapshot === 'consumable'
                      return (
                      <div key={item.id} className="flex items-start justify-between px-3 py-2 text-sm gap-2">
                        <div className="min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-gray-700">{item.equipment_name ?? item.equipment_id}</span>
                            <span className="text-gray-400">×{item.quantity}</span>
                            {isConsumable && <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-50 text-amber-600">วัสดุ</span>}
                            {item.returned ? (
                              <span className={`text-xs ${['ok', 'returned_full'].includes(item.condition_on_return) ? 'text-green-600' : 'text-red-500'}`}>
                                {CONDITION_LABEL[item.condition_on_return] ?? 'สรุปแล้ว'}
                              </span>
                            ) : (
                              req.status === 'approved' && <span className="text-xs text-blue-500">{isConsumable ? 'เบิกแล้ว (รอสรุป)' : 'ยังไม่คืน'}</span>
                            )}
                            {!item.returned && item.return_requested && (
                              <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700 font-medium">
                                นักศึกษาแจ้งขอคืนแล้ว
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
                        {req.status === 'approved' && !item.returned && (
                          <button
                            onClick={() => setReturnTarget({ requestId: req.id, item })}
                            className="shrink-0 text-xs rounded-lg bg-blue-50 text-blue-600 px-3 py-1 hover:bg-blue-100 font-medium"
                          >
                            {isConsumable ? 'สรุปผล' : 'รับคืน'}
                          </button>
                        )}
                      </div>
                    )})}
                  </div>

                  <div className="flex items-center gap-4 pt-1">
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
                      className="text-sm text-blue-600 hover:underline"
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

      {returnTarget && (
        <ReturnModal
          requestId={returnTarget.requestId}
          item={returnTarget.item}
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
