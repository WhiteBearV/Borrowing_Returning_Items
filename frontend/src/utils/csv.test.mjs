import assert from 'node:assert/strict'
import { fetchAllPages, toCsv } from './csv.js'

// เครื่องหมายคำพูด/คอมมา/ขึ้นบรรทัดในข้อมูลต้องไม่ทำให้คอลัมน์เลื่อน · null = ช่องว่าง · มี BOM นำหน้า
assert.equal(toCsv(['a', 'b'], [['x "y"', 'p,q\nr'], [null, 0]]),
  '﻿"a","b"\r\n"x ""y""","p,q\nr"\r\n"","0"')

// ดึงครบทุกหน้าแล้วหยุด ไม่ยิงหน้าเกิน
const calls = []
const list = async ({ page, page_size }) => {
  calls.push(page)
  const all = Array.from({ length: 230 }, (_, i) => i)
  return { items: all.slice((page - 1) * page_size, page * page_size), total: all.length }
}
assert.equal((await fetchAllPages(list, { q: 1 })).length, 230)
assert.deepEqual(calls, [1, 2, 3])
console.log('csv ok')
