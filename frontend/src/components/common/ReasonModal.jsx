import { useState } from 'react'

/** โมดัลขอเหตุผล — ใช้ร่วมกันทั้ง "ผู้ยืมยกเลิกคำขอ" และ "แอดมินปฏิเสธคำขอ" (8 ก.ย. 69)
 *
 *  มีดรอปดาวน์เหตุผลสำเร็จรูปที่กดแล้วเติมข้อความให้ (ยังพิมพ์แก้ต่อได้) + ตัวเลือก "อื่น ๆ" สำหรับ
 *  เหตุผลที่เราไม่ได้เตรียมไว้ — เหตุผลที่พิมพ์เองล้วน ๆ มักได้ "ไม่สะดวก" ซึ่งอ่านย้อนหลังแล้วไม่ได้อะไร
 */
export default function ReasonModal({
  title, message, presets = [], placeholder, confirmLabel = 'ยืนยัน', danger = false, onCancel, onConfirm,
}) {
  const [preset, setPreset] = useState('')
  const [reason, setReason] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const pickPreset = (value) => {
    setPreset(value)
    // "อื่น ๆ" = ล้างช่องให้พิมพ์เอง · เลือกหัวข้อสำเร็จรูป = เติมข้อความให้แล้วแก้ต่อได้
    setReason(value === '__other__' ? '' : value)
  }

  const submit = async () => {
    const text = reason.trim()
    if (!text) { setError('กรุณาระบุเหตุผล'); return }
    setError('')
    setLoading(true)
    try {
      await onConfirm(text)
    } catch (e) {
      setError(e.response?.data?.detail ?? 'บันทึกไม่สำเร็จ')
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50 px-4">
      <div className="bg-white rounded-2xl p-6 w-full max-w-md shadow-xl space-y-4">
        <h2 className="font-bold text-gray-800">{title}</h2>
        {message && <p className="text-sm text-gray-500 whitespace-pre-line">{message}</p>}

        {presets.length > 0 && (
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">เลือกเหตุผล</label>
            <select value={preset} onChange={(e) => pickPreset(e.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500">
              <option value="">— เลือกเหตุผลสำเร็จรูป —</option>
              {presets.map((p) => <option key={p} value={p}>{p}</option>)}
              <option value="__other__">อื่น ๆ (ระบุเอง)</option>
            </select>
          </div>
        )}

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            เหตุผล <span className="text-red-500">*</span>
          </label>
          <textarea rows={3} value={reason} onChange={(e) => setReason(e.target.value)}
            placeholder={placeholder ?? 'อธิบายเหตุผลสั้น ๆ'}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-primary-500" />
        </div>

        {error && <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>}

        <div className="flex gap-3">
          <button onClick={onCancel} className="flex-1 rounded-full border py-2 text-sm text-gray-600 hover:bg-gray-50">
            ปิด
          </button>
          <button onClick={submit} disabled={loading || !reason.trim()}
            className={`flex-1 rounded-full py-2 text-sm font-semibold text-white disabled:opacity-50
              ${danger ? 'bg-red-600 hover:bg-red-700' : 'bg-primary-600 hover:bg-primary-700'}`}>
            {loading ? 'กำลังบันทึก…' : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}

// เหตุผลสำเร็จรูป — เก็บไว้ที่เดียวเพื่อให้ฝั่งผู้ยืมและฝั่งแอดมินใช้ชุดเดียวกันตลอด
export const CANCEL_REASONS = [
  'เปลี่ยนใจ ไม่ต้องใช้อุปกรณ์แล้ว',
  'เลือกอุปกรณ์ผิดรายการ/ผิดจำนวน',
  'กรอกวันคืนผิด จะยื่นคำขอใหม่',
  'กิจกรรม/งานที่จะใช้ถูกเลื่อนหรือยกเลิก',
  'หาอุปกรณ์จากที่อื่นได้แล้ว',
]

export const REJECT_REASONS = [
  'อุปกรณ์ไม่ว่างในช่วงเวลาที่ขอ',
  'อุปกรณ์ชำรุด/อยู่ระหว่างซ่อม',
  'ข้อมูลในคำขอไม่ครบหรือไม่ชัดเจน',
  'วัตถุประสงค์ไม่เข้าเกณฑ์การยืม',
  'ผู้ยืมมีอุปกรณ์ค้างคืนเกินกำหนด',
  'ให้ติดต่อเจ้าหน้าที่ที่ห้องพัสดุก่อน',
]
