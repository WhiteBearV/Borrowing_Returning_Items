// วันครบกำหนดคืน "ที่ใช้จริง" ของอุปกรณ์ 1 ชิ้น — คู่แฝดของ backend/app/utils/duedate.py
// ลำดับความสำคัญต้องตรงกันเป๊ะ ไม่งั้นหน้าเว็บโชว์คนละวันกับที่ระบบทวงและที่พิมพ์ลงใบยืม
import { daysSinceTH } from './formatDate.js'

export const itemDueDate = (item, req) =>
  item.extended_due_date ?? item.due_date ?? req?.due_date ?? null

/** วันของชิ้นนี้ต่างจากวันของทั้งใบไหม — ใช้ตัดสินว่าต้องโชว์วันรายชิ้นให้เห็นหรือไม่
 *  (ทุกชิ้นวันเดียวกันก็ไม่ต้องรก หัวแถวบอกไปแล้ว) */
export const hasOwnDueDate = (item, req) => {
  const d = itemDueDate(item, req)
  return !!d && d !== req?.due_date
}

/** เกินกำหนดมากี่วัน (0 = ยังไม่เกิน) — ใช้ทั้งป้ายรายชิ้นและป้ายหัวคำขอ
 *  นับเฉพาะชิ้นที่ยังไม่ได้คืนจริง ของที่คืนแล้วดูจากค่าปรับ/ใบคืนแทน */
export const overdueDays = (item, req) => {
  if (item.returned || item.item_status === 'rejected') return 0
  const due = itemDueDate(item, req)
  if (!due) return 0
  const diff = daysSinceTH(due)
  return Math.max(0, diff)
}

/** เกินกำหนดมากที่สุดกี่วันในคำขอนี้ — ใช้ป้ายที่หัวการ์ด (ของชิ้นที่ช้าที่สุดคือความเสี่ยงจริง) */
export const maxOverdueDays = (req) =>
  Math.max(0, ...(req.items ?? []).map((i) => overdueDays(i, req)))
