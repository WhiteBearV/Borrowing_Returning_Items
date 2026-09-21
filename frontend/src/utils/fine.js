// ค่าปรับ — ตัวช่วยฝั่งหน้าเว็บ
// การคำนวณจริงอยู่ที่ backend (borrow_service._compute_fine) และถูก freeze ลงแถวตอนรับคืน
// ที่นี่มีไว้ "พรีวิว" ในโมดัลรับคืนเท่านั้น สูตรต้องตรงกับฝั่ง backend เป๊ะ ไม่งั้นแอดมินเห็นยอดหนึ่ง
// แล้วระบบบันทึกอีกยอดหนึ่ง (คู่แฝดแบบเดียวกับ utils/dueDate.js ↔ backend/app/utils/duedate.py)
import { itemDueDate } from './dueDate.js'
import { daysSinceTH } from './formatDate.js'

export const FINE_STATUS = {
  none: { label: 'ไม่มีค่าปรับ', cls: 'bg-gray-100 text-gray-500' },
  unpaid: { label: 'ค้างชำระ', cls: 'bg-red-100 text-red-600' },
  paid: { label: 'ชำระแล้ว', cls: 'bg-emerald-100 text-emerald-700' },
  waived: { label: 'ยกเว้น', cls: 'bg-amber-100 text-amber-700' },
}

const DAMAGE_CONDITIONS = new Set(['damaged', 'lost', 'discarded'])

export const fineMoney = (v) =>
  (v == null ? '—' : Number(v).toLocaleString('th-TH', { minimumFractionDigits: 2, maximumFractionDigits: 2 }))

/** ยอดที่ระบบจะคิดถ้ารับคืนวันนี้ — settings = แถวจาก GET /settings (key/value) */
export function previewFine(item, req, condition, settings) {
  const num = (key, fallback) => {
    const row = settings?.find?.((s) => s.key === key)
    const v = Number(row?.value)
    return Number.isFinite(v) ? v : fallback
  }
  const rate = num('fine_per_day_per_item', 10)
  const grace = num('fine_grace_days', 0)
  const cap = num('fine_max_per_item', 0)

  const due = itemDueDate(item, req)
  let daysLate = 0
  if (due) {
    // เทียบเป็นวันตามปฏิทินไทย แบบเดียวกับฝั่ง backend ที่เทียบ date กับ date (container ตั้ง TZ=Asia/Bangkok)
    daysLate = Math.max(0, daysSinceTH(due) - grace)
  }
  let lateAmount = Math.round(daysLate * rate * 100) / 100
  if (cap > 0) lateAmount = Math.min(lateAmount, cap)

  const damageAmount = DAMAGE_CONDITIONS.has(condition) ? (item.book_value ?? 0) : 0
  return { daysLate, rate, grace, cap, lateAmount, damageAmount, total: lateAmount + damageAmount }
}
