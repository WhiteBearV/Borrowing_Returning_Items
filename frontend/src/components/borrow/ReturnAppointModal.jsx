import { useState } from 'react'
import { borrowApi } from '../../api/borrowApi.js'

// พรุ่งนี้เวลาที่กำหนด (ค่าเริ่มต้นของช่อง datetime-local) — ใช้เวลาเครื่องผู้ใช้ ไม่ผ่าน toISOString
// เพราะ toISOString แปลงเป็น UTC แล้วช่องจะขึ้นเวลาเพี้ยนไป 7 ชั่วโมง
const tomorrowAt = (hhmm = '13:00') => {
  const d = new Date()
  d.setDate(d.getDate() + 1)
  const [h, m] = hhmm.split(':')
  d.setHours(Number(h) || 13, Number(m) || 0, 0, 0)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const nowLocal = () => tomorrowAt().slice(0, 10) // ใช้แค่ให้ min ไม่ย้อนอดีตแบบหยาบ ๆ

/** นักศึกษาแจ้งขอคืน — ต้องนัดวัน-เวลา-สถานที่ ไม่ใช่แค่กดแจ้งเฉย ๆ
 *  แอดมินจะได้รู้ล่วงหน้าว่าวันนี้ใครจะมาคืนอะไรกี่โมง (feedback อาจารย์ ข้อ 12) */
export function ReturnAppointModal({ requestId, itemIds, defaultLocation, onClose, onDone }) {
  const [when, setWhen] = useState(tomorrowAt())
  // ค่าเริ่มต้น = ที่ที่ไปรับของมา (ปกติคืนที่เดิม) — ไม่ดึงจาก settings เพราะ GET /settings เป็นสิทธิ์
  // เจ้าหน้าที่ นักศึกษาเรียกแล้วได้ 403 ช่องนี้ก็จะว่างเปล่าอยู่ดี
  const [where, setWhere] = useState(defaultLocation ?? '')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const submit = async () => {
    if (!when || !where.trim()) return
    setLoading(true)
    setError('')
    try {
      await borrowApi.requestReturn(requestId, itemIds, when, where.trim())
      onDone()
    } catch (err) {
      setError(err.response?.data?.detail ?? 'แจ้งขอคืนไม่สำเร็จ')
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50 px-4">
      <div className="bg-white rounded-2xl p-6 w-full max-w-sm shadow-xl space-y-4">
        <h2 className="font-bold text-gray-800">นัดคืนอุปกรณ์</h2>
        <p className="text-sm text-gray-500">{itemIds.length} รายการ — เจ้าหน้าที่จะรอรับตามเวลาที่นัดไว้</p>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">วัน-เวลาที่จะมาคืน</label>
          <input type="datetime-local" min={`${nowLocal()}T00:00`} value={when}
            onChange={(e) => setWhen(e.target.value)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">สถานที่</label>
          <input type="text" value={where} onChange={(e) => setWhere(e.target.value)}
            placeholder="เช่น ห้องพัสดุ ชั้น 3"
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
        </div>

        {error && <p className="text-sm text-red-600">{error}</p>}

        <div className="flex gap-3">
          <button onClick={onClose} className="flex-1 rounded-full border py-2 text-sm text-gray-600 hover:bg-gray-50">
            ยกเลิก
          </button>
          <button onClick={submit} disabled={loading || !when || !where.trim()}
            className="flex-1 rounded-full bg-primary-600 py-2 text-sm font-semibold text-white hover:bg-primary-700 disabled:opacity-50">
            {loading ? 'กำลังส่ง…' : 'ยืนยันนัดคืน'}
          </button>
        </div>
      </div>
    </div>
  )
}
