import { todayTH } from './formatDate.js'

// ponytail: ดึงทีละหน้าจาก API รายการเดิม (ตัวกรองเดียวกับที่เห็นบนจอ) แล้วประกอบ CSV ฝั่งเว็บ ไม่มี endpoint
// export แยก — เพดาน 50 หน้า × 100 = 5,000 แถว พอกับคลัง/ประวัติของคณะ ถ้าเกินค่อยทำ endpoint สตรีมฝั่ง backend
const MAX_PAGES = 50
const PAGE_SIZE = 100

export const csvCell = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`

export function toCsv(header, rows) {
  // BOM — ไม่มีตัวนี้ Excel บน Windows เปิดไฟล์แล้วภาษาไทยเป็นตัวขยะ
  return '﻿' + [header, ...rows].map((r) => r.map(csvCell).join(',')).join('\r\n')
}

/** ทุกแถวของ list API ที่แบ่งหน้า ({ items, total }) ตามตัวกรองที่ส่งมา */
export async function fetchAllPages(listFn, params = {}) {
  const rows = []
  for (let page = 1; page <= MAX_PAGES; page++) {
    const chunk = await listFn({ ...params, page, page_size: PAGE_SIZE })
    rows.push(...chunk.items)
    if (rows.length >= chunk.total || chunk.items.length === 0) break
  }
  return rows
}

/** ดาวน์โหลดไฟล์ชื่อ `<prefix>-<วันนี้>.csv` */
export function downloadCsv(prefix, header, rows) {
  const url = URL.createObjectURL(new Blob([toCsv(header, rows)], { type: 'text/csv;charset=utf-8' }))
  const a = document.createElement('a')
  a.href = url
  a.download = `${prefix}-${todayTH()}.csv`
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 10000)
}
