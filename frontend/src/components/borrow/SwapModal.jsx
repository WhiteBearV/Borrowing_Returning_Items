import { useState } from 'react'
import { borrowApi } from '../../api/borrowApi.js'
import { equipmentApi } from '../../api/equipmentApi.js'
import UnitPickerModal from './UnitPickerModal.jsx'

const CONDITIONS = [
  { value: 'damaged', label: 'เสียหาย (ส่งซ่อม)' }, { value: 'ok', label: 'ปกติ (กลับเข้าคลัง)' },
  { value: 'lost', label: 'สูญหาย' },
]
const PHOTO_REQUIRED = new Set(['damaged', 'lost'])
const imgSrc = (url) => (url?.startsWith('/') ? `${import.meta.env.VITE_API_URL || 'http://localhost:8000'}${url}` : url)

/** เปลี่ยนตัวระหว่างยืม (SKGRent ข้อ 4) — รับหน่วยเดิมกลับตามสภาพจริง จ่ายหน่วยใหม่รุ่นเดียวกัน คงวันครบกำหนดเดิม
 *  หน่วยใหม่ว่าง = ระบบเลือกด้วยกฎจ่ายของเดิม · ค่าปรับล่าช้า (ถ้ามี) ไปคิดตอนคืนหน่วยใหม่ ไม่คิดซ้ำตอนเปลี่ยน */
export default function SwapModal({ item, req, onClose, onDone }) {
  const [condition, setCondition] = useState('damaged')
  const [reason, setReason] = useState('')
  const [note, setNote] = useState('')
  const [photos, setPhotos] = useState([])
  const [unit, setUnit] = useState(null) // { id, code } หรือ null = ให้ระบบเลือก
  const [picking, setPicking] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const needPhoto = PHOTO_REQUIRED.has(condition)

  const uploadPhotos = async (e) => {
    const files = Array.from(e.target.files ?? [])
    if (!files.length) return
    setUploading(true)
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
    if (!reason.trim()) { setError('กรุณาระบุเหตุผลที่เปลี่ยนตัว'); return }
    if (needPhoto && !photos.length) { setError('กรุณาแนบรูปหลักฐานอย่างน้อย 1 รูป'); return }
    setLoading(true)
    setError('')
    try {
      await borrowApi.swapItem(req.id, item.id, {
        condition_on_return: condition, reason: reason.trim(), damage_note: note || undefined,
        damage_photo_urls: photos.length ? photos : undefined, equipment_id: unit?.id ?? undefined,
      })
      onDone()
    } catch (err) {
      setError(err.response?.data?.detail ?? 'บันทึกไม่สำเร็จ')
      setLoading(false)
    }
  }

  if (picking) {
    return (
      <UnitPickerModal item={item} selectedId={unit?.id ?? null} studentId={req.student_id}
        studentYearLabel={req.student_year_label}
        onPick={(id, code) => { setUnit(id ? { id, code } : null); setPicking(false) }}
        onClose={() => setPicking(false)} />
    )
  }

  const input = 'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500'
  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50 px-4">
      <div className="bg-white rounded-2xl p-6 w-full max-w-sm shadow-xl space-y-4 max-h-[90vh] overflow-y-auto">
        <h2 className="font-bold text-gray-800">เปลี่ยนตัวระหว่างยืม</h2>
        <p className="text-sm text-gray-500">
          {item.equipment_name} · หน่วยเดิม <span className="font-mono">{item.equipment_code}</span>
          <br />หน่วยใหม่ได้วันครบกำหนดเดิม ผู้ยืมไม่ต้องยื่นคำขอใหม่
        </p>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">สภาพหน่วยเดิมที่รับกลับ</label>
          <select value={condition} onChange={(e) => setCondition(e.target.value)} className={`${input} bg-white`}>
            {CONDITIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
        {needPhoto && (
          <>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                รูปหลักฐาน <span className="text-red-500">*</span>
              </label>
              <input type="file" accept="image/*" capture="environment" multiple onChange={uploadPhotos} disabled={uploading}
                className="block w-full text-xs text-gray-500 file:mr-3 file:rounded-lg file:border-0 file:bg-primary-50 file:px-3 file:py-1.5 file:text-primary-600" />
              {photos.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-2">
                  {photos.map((url) => <img key={url} src={imgSrc(url)} alt="" className="w-14 h-14 rounded-lg object-cover border" />)}
                </div>
              )}
            </div>
            <textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)}
              className={`${input} resize-none`} placeholder="อธิบายความเสียหาย…" />
          </>
        )}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">เหตุผลที่เปลี่ยน <span className="text-red-500">*</span></label>
          <input value={reason} onChange={(e) => setReason(e.target.value)} className={input}
            placeholder="เช่น จอเสียระหว่างใช้งาน" />
        </div>
        <div className="flex items-center justify-between text-sm">
          <span className="text-gray-500">หน่วยใหม่: {unit ? <span className="font-mono">{unit.code}</span> : 'ระบบเลือกให้'}</span>
          <button onClick={() => setPicking(true)} className="text-primary-600 hover:underline">เลือกเอง</button>
        </div>
        {error && <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>}
        <div className="flex gap-3">
          <button onClick={onClose} className="flex-1 rounded-full border py-2 text-sm text-gray-600 hover:bg-gray-50">ยกเลิก</button>
          <button onClick={submit} disabled={loading || uploading}
            className="flex-1 rounded-full bg-primary-600 py-2 text-sm font-semibold text-white hover:bg-primary-700 disabled:opacity-50">
            {loading ? 'กำลังบันทึก…' : 'เปลี่ยนตัว'}
          </button>
        </div>
      </div>
    </div>
  )
}
