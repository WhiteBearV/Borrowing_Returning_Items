import { useState } from 'react'

// 5 ช่องตามแบบรายงานทะเบียนคุมทรัพย์สินของคณะ — ลำดับ/ชื่อตรงกับ CONDITION_COLUMNS ฝั่ง backend
export const CONDITIONS = [
  { key: 'normal', label: 'ปกติ', cls: 'bg-green-100 text-green-800' },
  { key: 'damaged', label: 'ชำรุด', cls: 'bg-red-100 text-red-800' },
  { key: 'deteriorated', label: 'เสื่อมสภาพ', cls: 'bg-amber-100 text-amber-800' },
  { key: 'lost', label: 'สูญหาย (ไม่พบ)', cls: 'bg-gray-800 text-white' },
  { key: 'wrong_category', label: 'รายการผิดประเภท', cls: 'bg-purple-100 text-purple-800' },
]

/** เลือกสภาพ + หมายเหตุของครุภัณฑ์ 1 ชิ้นในรอบตรวจ — ขึ้นหลังสแกน หรือกดจากรายการ
 *  ไม่มีค่าเริ่มต้น (ยังไม่ตรวจ = ยังไม่ติ๊ก) · หมายเหตุใส่ได้เสมอ · ไม่ใช่ "ปกติ" บังคับหมายเหตุ */
export default function StocktakeConditionDialog({ item, roomName, onSave, onUndo, onClose }) {
  const [condition, setCondition] = useState(item.condition ?? '')
  const [note, setNote] = useState(item.note ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const needNote = condition && condition !== 'normal'
  const canSave = condition && (!needNote || note.trim())

  const scanned = ['found', 'moved_here'].includes(item.result) || !!item.condition
  const undo = async () => {
    setBusy(true)
    setError('')
    try {
      await onUndo()
    } catch (e) {
      setError(e.response?.data?.detail ?? 'ยกเลิกไม่สำเร็จ')
      setBusy(false)
    }
  }

  const save = async () => {
    setBusy(true)
    setError('')
    try {
      await onSave(condition, note.trim())
    } catch (e) {
      setError(e.response?.data?.detail ?? 'บันทึกไม่สำเร็จ')
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center overflow-y-auto bg-black/50 px-4 py-6">
      <div className="w-full max-w-md space-y-4 rounded-2xl bg-white p-6 shadow-xl">
        <div>
          <h2 className="font-bold text-gray-800">สภาพครุภัณฑ์</h2>
          <p className="text-sm text-gray-700">{item.equipment_name}</p>
          <p className="text-xs text-gray-500">
            {item.asset_number || item.equipment_code}{item.location_detail && ` · ${item.location_detail}`}
          </p>
        </div>

        {item.result === 'moved_here' && (
          <div className="rounded-xl border-2 border-orange-400 bg-orange-50 px-3 py-2.5 text-sm text-orange-900">
            <p className="font-bold">⚠ ของนี้ไม่ได้อยู่ในรายการของห้องนี้</p>
            <p>ทะเบียนเดิมอยู่ห้อง <b>{item.from_location || 'ไม่ระบุ'}</b> — ระบบย้ายมาห้อง <b>{roomName}</b> ให้แล้ว
              ถ้าสแกนผิด กด <b>"ยกเลิกการสแกน"</b> จะย้ายกลับห้องเดิม</p>
          </div>
        )}

        <div className="grid grid-cols-2 gap-2">
          {/* ของห้องอื่นที่เพิ่งสแกนเจอ ติ๊กสูญหายไม่ได้ (backend ตอบ 400) — สแกนผิดใช้ปุ่มยกเลิกการสแกน */}
          {CONDITIONS.filter((c) => !(c.key === 'lost' && item.result === 'moved_here')).map((c) => (
            <button key={c.key} type="button" onClick={() => setCondition(c.key)}
              className={`rounded-xl border-2 px-3 py-2.5 text-sm font-medium ${condition === c.key
                ? 'border-primary-600 bg-primary-50 text-primary-800' : 'border-gray-200 text-gray-700 hover:bg-gray-50'}`}>
              {condition === c.key ? '✓ ' : ''}{c.label}
            </button>
          ))}
        </div>

        <div>
          <label className="mb-1 block text-xs font-medium text-gray-600">
            หมายเหตุ{needNote ? <span className="text-red-600"> * (จำเป็นเมื่อไม่ใช่ปกติ)</span> : ' (ไม่บังคับ)'}
          </label>
          <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={3} maxLength={2000}
            placeholder={needNote ? 'เช่น ขาเก้าอี้หัก / จอมีรอยแตก / หาไม่เจอในห้อง' : 'ใส่เพิ่มได้ถ้ามี'}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
        </div>
        {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
        {scanned && onUndo && (
          <button type="button" onClick={undo} disabled={busy}
            className="w-full rounded-full border border-red-300 py-2 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-50">
            ยกเลิกการสแกน{item.result === 'moved_here' ? ` (ย้ายกลับห้อง ${item.from_location || 'เดิม'})` : ' (กลับเป็นยังไม่ตรวจ)'}
          </button>
        )}

        <div className="flex gap-2">
          <button type="button" onClick={onClose}
            className="flex-1 rounded-full border border-gray-300 py-2 text-sm font-medium text-gray-600 hover:bg-gray-50">
            ไว้ทีหลัง
          </button>
          <button type="button" onClick={save} disabled={!canSave || busy}
            className="flex-1 rounded-full bg-primary-600 py-2 text-sm font-semibold text-white hover:bg-primary-700 disabled:opacity-50">
            บันทึก
          </button>
        </div>
      </div>
    </div>
  )
}
