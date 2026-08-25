import { useState } from 'react'
import { equipmentApi } from '../../api/equipmentApi.js'

const imgSrc = (url) => (url?.startsWith('/') ? `${import.meta.env.VITE_API_URL || 'http://localhost:8000'}${url}` : url)

// บันทึกว่าตรวจนับอุปกรณ์ชิ้นนี้ทางกายภาพแล้ว — note/รูปไม่บังคับ (ยืนยันกับผู้ใช้แล้ว)
// UI อัปโหลดรูปยกมาจาก ReturnModal.jsx (equipmentApi.uploadImage เดิม ไม่คิด mechanism ใหม่)
export default function AuditModal({ id, name, onClose, onSave }) {
  const [note, setNote] = useState('')
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
    setLoading(true)
    setError('')
    try {
      await onSave(note || undefined, photos)
    } catch (err) {
      setError(err.response?.data?.detail ?? 'บันทึกไม่สำเร็จ')
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50 px-4">
      <div className="bg-white rounded-2xl p-6 w-full max-w-sm shadow-xl space-y-4">
        <h2 className="font-bold text-gray-800">ตรวจนับอุปกรณ์</h2>
        <p className="text-sm text-gray-500">{name}</p>

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

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">โน้ต (ไม่บังคับ)</label>
          <textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-primary-500"
            placeholder="เช่น เจอของจริง สภาพปกติ…" />
        </div>

        {error && <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>}
        <div className="flex gap-3">
          <button onClick={onClose} className="flex-1 rounded-full border py-2 text-sm text-gray-600 hover:bg-gray-50">ยกเลิก</button>
          <button onClick={submit} disabled={loading || uploading}
            className="flex-1 rounded-full bg-primary-600 py-2 text-sm font-semibold text-white hover:bg-primary-700 disabled:opacity-50">
            {loading ? 'กำลังบันทึก…' : 'ยืนยันตรวจนับแล้ว'}
          </button>
        </div>
      </div>
    </div>
  )
}
