import { useState } from 'react'

// ปรับยอดคงเหลือหลายรายการพร้อมกันแบบ "บวก/ลบเท่ากันทุกแถว" (delta) — ต่างจาก AdjustStockModal เดี่ยวที่ตั้งค่า
// absolute เพราะแต่ละแถวที่เลือก quantity_total ไม่เท่ากัน ตั้งเลขเดียวทับทุกแถวไม่มีความหมาย backend clamp
// แต่ละแถวเองไม่ให้เกิน quantity_total ลบจำนวนที่ถูกยืมออกไปจริง หรือต่ำกว่า 0 ของแถวนั้น
// (เงียบ ๆ ไม่ error ทั้งชุดถ้าบางแถวชนขอบเขต)
export default function BulkAdjustStockModal({ count, onClose, onSave }) {
  const [delta, setDelta] = useState('')
  const [reason, setReason] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const submit = async () => {
    const n = Number(delta)
    if (!Number.isInteger(n) || n === 0) {
      setError('กรอกจำนวนที่จะบวก/ลบเป็นเลขจำนวนเต็ม ไม่เท่ากับ 0 (ใส่ค่าลบเพื่อลด)')
      return
    }
    if (!reason.trim()) {
      setError('กรุณาระบุเหตุผล')
      return
    }
    setError('')
    setLoading(true)
    try {
      await onSave(n, reason.trim())
    } catch (err) {
      setError(err.response?.data?.detail ?? 'บันทึกไม่สำเร็จ')
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50 px-4">
      <div className="bg-white rounded-2xl p-6 w-full max-w-sm shadow-xl space-y-4">
        <h2 className="font-bold text-gray-800">ปรับยอดคงเหลือหลายรายการ</h2>
        <p className="text-sm text-gray-500">ปรับพร้อมกัน {count} รายการ</p>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">จำนวนที่จะบวก/ลบ</label>
          <input type="number" step={1} autoFocus value={delta} onChange={(e) => setDelta(e.target.value)}
            placeholder="เช่น -2 (ลด 2) หรือ 5 (เพิ่ม 5)"
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
          <p className="mt-1 text-xs text-gray-400">
            ระบบบวก/ลบเท่ากันทุกแถวที่เลือก — แถวไหนไม่พอ (ต่ำกว่า 0) หรือเกินจำนวนที่ยังไม่ถูกยืมออกไปของแถวนั้น
            (จำนวนทั้งหมด ลบ จำนวนที่ถูกยืมอยู่) จะถูกปัดให้อยู่ในขอบเขตอัตโนมัติ
          </p>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">เหตุผล <span className="text-red-500">*</span></label>
          <textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-primary-500"
            placeholder="เช่น นับจริงแล้วขาดทุกแถว 2 ชิ้น ไม่มีบันทึกยืม…" />
        </div>

        {error && <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>}
        <div className="flex gap-3">
          <button onClick={onClose} className="flex-1 rounded-full border py-2 text-sm text-gray-600 hover:bg-gray-50">ยกเลิก</button>
          <button onClick={submit} disabled={loading || !reason.trim()}
            className="flex-1 rounded-full bg-primary-600 py-2 text-sm font-semibold text-white hover:bg-primary-700 disabled:opacity-50">
            {loading ? 'กำลังบันทึก…' : 'บันทึกการปรับยอด'}
          </button>
        </div>
      </div>
    </div>
  )
}
