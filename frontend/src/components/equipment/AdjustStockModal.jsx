import { useState } from 'react'
import { equipmentApi } from '../../api/equipmentApi.js'

const imgSrc = (url) => (url?.startsWith('/') ? `${import.meta.env.VITE_API_URL || 'http://localhost:8000'}${url}` : url)

// ปรับ quantity_available ให้ตรงกับที่นับได้จริง — ต่างจาก "+ เพิ่มจำนวน" (restock) ที่บวกเพิ่ม อันนี้ SET
// ตรง ๆ (เช่นของหายไปโดยไม่มีบันทึกยืม) เหตุผลจึงบังคับ (ต่างจาก AuditModal ที่โน้ตไม่บังคับ) รูปยังไม่บังคับ
export default function AdjustStockModal({ id, name, currentAvailable, currentTotal, onClose, onSave }) {
  const [newAvailable, setNewAvailable] = useState(String(currentAvailable))
  const [reason, setReason] = useState('')
  const [photos, setPhotos] = useState([])
  const [uploading, setUploading] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

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
    const n = Number(newAvailable)
    if (!Number.isInteger(n) || n < 0 || n > currentTotal) {
      setError(`กรอกจำนวนเป็นเลขจำนวนเต็ม 0–${currentTotal}`)
      return
    }
    if (!reason.trim()) {
      setError('กรุณาระบุเหตุผล')
      return
    }
    setLoading(true)
    setError('')
    try {
      await onSave(n, reason.trim(), photos)
    } catch (err) {
      setError(err.response?.data?.detail ?? 'บันทึกไม่สำเร็จ')
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50 px-4">
      <div className="bg-white rounded-2xl p-6 w-full max-w-sm shadow-xl space-y-4">
        <h2 className="font-bold text-gray-800">ปรับยอดคงเหลือ</h2>
        <p className="text-sm text-gray-500">{name}</p>
        <p className="text-xs text-gray-400">ปัจจุบัน: {currentAvailable}/{currentTotal}</p>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">จำนวนคงเหลือที่นับได้จริง</label>
          <input type="number" min={0} max={currentTotal} step={1} value={newAvailable}
            onChange={(e) => setNewAvailable(e.target.value)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">เหตุผล <span className="text-red-500">*</span></label>
          <textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-primary-500"
            placeholder="เช่น นับจริงแล้วขาด 2 ชิ้น ไม่มีบันทึกยืม…" />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">รูปประกอบ (ไม่บังคับ)</label>
          <input type="file" accept="image/*" capture="environment" multiple onChange={uploadPhotos} disabled={uploading}
            className="block w-full text-xs text-gray-500 file:mr-3 file:rounded-lg file:border-0 file:bg-primary-50 file:px-3 file:py-1.5 file:text-primary-600" />
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

        {error && <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>}
        <div className="flex gap-3">
          <button onClick={onClose} className="flex-1 rounded-full border py-2 text-sm text-gray-600 hover:bg-gray-50">ยกเลิก</button>
          <button onClick={submit} disabled={loading || uploading || !reason.trim()}
            className="flex-1 rounded-full bg-primary-600 py-2 text-sm font-semibold text-white hover:bg-primary-700 disabled:opacity-50">
            {loading ? 'กำลังบันทึก…' : 'บันทึกการปรับยอด'}
          </button>
        </div>
      </div>
    </div>
  )
}
