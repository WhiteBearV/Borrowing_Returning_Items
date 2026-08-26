import { useState } from 'react'
import { borrowApi } from '../../api/borrowApi.js'

const tomorrow = () => {
  const d = new Date()
  d.setDate(d.getDate() + 1)
  return d.toISOString().slice(0, 10)
}

// นักศึกษายื่นคำขอต่อเวลา (เลือกวันที่+เหตุผลเอง) — ยังไม่ใช่การต่อเวลาจริง แค่แจ้ง admin ให้มาอนุมัติ
export function RenewModal({ item, requestId, onClose, onDone }) {
  const [requestedDate, setRequestedDate] = useState('')
  const [reason, setReason] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const submit = async () => {
    if (!requestedDate || !reason.trim()) return
    setLoading(true)
    setError('')
    try {
      await borrowApi.renewRequest(requestId, item.id, requestedDate, reason.trim())
      onDone()
    } catch (err) {
      setError(err.response?.data?.detail ?? 'ส่งคำขอไม่สำเร็จ')
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50 px-4">
      <div className="bg-white rounded-2xl p-6 w-full max-w-sm shadow-xl space-y-4">
        <h2 className="font-bold text-gray-800">ขอต่อเวลา</h2>
        <p className="text-sm text-gray-500">{item.equipment_name}</p>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">วันที่ต้องการคืนใหม่</label>
          <input type="date" min={tomorrow()} value={requestedDate}
            onChange={(e) => setRequestedDate(e.target.value)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">เหตุผล</label>
          <textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-primary-500"
            placeholder="เช่น งานยังไม่เสร็จ ขอเวลาเพิ่ม…" />
        </div>

        {error && <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>}
        <div className="flex gap-3">
          <button onClick={onClose} className="flex-1 rounded-full border py-2 text-sm text-gray-600 hover:bg-gray-50">ยกเลิก</button>
          <button onClick={submit} disabled={loading || !requestedDate || !reason.trim()}
            className="flex-1 rounded-full bg-primary-600 py-2 text-sm font-semibold text-white hover:bg-primary-700 disabled:opacity-50">
            {loading ? 'กำลังส่ง…' : 'ส่งคำขอ'}
          </button>
        </div>
      </div>
    </div>
  )
}
