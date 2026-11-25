import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { equipmentApi } from '../../api/equipmentApi.js'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const MAX_SIDE = 512 // โมเดลใช้ 256px — ย่อก่อนส่งให้อัปโหลดเร็วบนเน็ตมือถือ

// ย่อรูปเป็น JPEG ด้วย canvas · ถอดรูปไม่ได้ (เช่น HEIC บนบางเบราว์เซอร์) = ส่งไฟล์เดิม ให้ backend ตัดสิน
async function shrink(file) {
  try {
    const bmp = await createImageBitmap(file)
    const k = Math.min(1, MAX_SIDE / Math.max(bmp.width, bmp.height))
    const canvas = document.createElement('canvas')
    canvas.width = Math.round(bmp.width * k)
    canvas.height = Math.round(bmp.height * k)
    canvas.getContext('2d').drawImage(bmp, 0, 0, canvas.width, canvas.height)
    const blob = await new Promise((ok) => canvas.toBlob(ok, 'image/jpeg', 0.85))
    return blob ? new File([blob], 'photo.jpg', { type: 'image/jpeg' }) : file
  } catch {
    return file
  }
}

function errorText(e) {
  const code = e?.response?.status
  if (code === 503) return 'ระบบค้นหาด้วยรูปยังไม่พร้อมใช้งานตอนนี้ ลองใหม่ภายหลัง หรือพิมพ์ชื่อค้นหาแทน'
  if (code === 429) return 'ค้นหาถี่เกินไป รอสักครู่แล้วลองใหม่'
  return e?.response?.data?.detail || 'ค้นหาไม่สำเร็จ ลองถ่ายรูปใหม่อีกครั้ง'
}

// ค้นหาอุปกรณ์ด้วยรูป (25 พ.ย. 69) — รูปไม่ถูกเก็บที่เซิร์ฟเวอร์ ใช้เทียบแล้วทิ้ง
export default function ImageSearchModal({ onClose }) {
  const [preview, setPreview] = useState(null)
  const [results, setResults] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => () => preview && URL.revokeObjectURL(preview), [preview])

  const onPhoto = async (e) => {
    const file = e.target.files?.[0]
    e.target.value = '' // เลือกรูปเดิมซ้ำได้
    if (!file) return
    setError('')
    setResults(null)
    setBusy(true)
    try {
      const small = await shrink(file)
      setPreview(URL.createObjectURL(small))
      setResults(await equipmentApi.searchByImage(small))
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  const pick = 'flex flex-1 cursor-pointer items-center justify-center rounded-full py-2 text-sm font-medium'

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50 px-4 py-6 overflow-y-auto">
      <div className="bg-white rounded-2xl p-6 w-full max-w-md shadow-xl space-y-4">
        <h2 className="font-bold text-gray-800">ค้นหาด้วยรูป</h2>
        <p className="text-sm text-gray-500">ถ่ายรูปของที่อยากยืมให้เห็นชัด ๆ ระบบจะหารุ่นในคลังที่หน้าตาหรือชื่อใกล้เคียงที่สุด 5 รุ่น</p>

        <div className="flex gap-2">
          <label className={`${pick} bg-primary-600 text-white hover:bg-primary-700`}>
            ถ่ายรูป
            <input type="file" accept="image/*" capture="environment" onChange={onPhoto} className="hidden" disabled={busy} />
          </label>
          <label className={`${pick} border border-primary-600 text-primary-700 hover:bg-primary-50`}>
            เลือกรูปจากเครื่อง
            <input type="file" accept="image/*" onChange={onPhoto} className="hidden" disabled={busy} />
          </label>
        </div>

        {preview && <img src={preview} alt="รูปที่ถ่าย" className="mx-auto h-32 rounded-lg object-contain bg-gray-50" />}
        {busy && <p className="text-sm text-gray-600">กำลังค้นหา…</p>}
        {error && <p className="text-sm text-amber-700 bg-amber-50 rounded-lg px-3 py-2">{error}</p>}

        {results && (results.length === 0 ? (
          <p className="text-sm text-gray-600">ไม่พบรุ่นที่ใกล้เคียง</p>
        ) : (
          <div className="space-y-2">
            <p className="text-xs text-gray-500">รุ่นที่ใกล้เคียงที่สุด เรียงจากใกล้สุด ระบบเดาจากรูปจึงอาจไม่ตรงทุกครั้ง</p>
            {results.map((r) => (
              <Link key={r.equipment_id} to={`/equipment/${r.equipment_id}`} onClick={onClose}
                className="flex items-center gap-3 rounded-lg border border-gray-200 p-2 hover:bg-gray-50">
                {r.image_url ? (
                  <img src={r.image_url.startsWith('/') ? `${API}${r.image_url}` : r.image_url} alt=""
                    className="h-12 w-12 shrink-0 rounded object-contain bg-gray-50" />
                ) : <div className="h-12 w-12 shrink-0 rounded bg-gray-100" />}
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-gray-800">{r.name}</p>
                  <p className={`text-xs ${r.quantity_available > 0 ? 'text-green-700' : 'text-gray-500'}`}>
                    {r.quantity_available > 0
                      ? `พร้อมยืม ${r.quantity_available}/${r.quantity_total} ${r.unit || ''}`
                      : 'ไม่ว่างตอนนี้'}
                  </p>
                </div>
              </Link>
            ))}
          </div>
        ))}

        <p className="text-xs text-gray-500">
          ไม่เจอ? ของอาจไม่มีในคลัง ลอง{' '}
          <a href="https://lens.google.com/" target="_blank" rel="noopener noreferrer" className="text-primary-600 hover:underline">Google Lens</a>
          {' '}เพื่อดูว่าของนั้นชื่ออะไร แล้วพิมพ์ค้นหาอีกครั้ง
        </p>

        <button type="button" onClick={onClose}
          className="w-full rounded-full border border-gray-300 py-2 text-sm font-medium text-gray-600 hover:bg-gray-50">
          ปิด
        </button>
      </div>
    </div>
  )
}
