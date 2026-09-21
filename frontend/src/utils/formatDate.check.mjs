// เช็คว่าวัน/เวลาเป็นเวลาไทยเสมอ ไม่ว่าเครื่องจะตั้ง timezone อะไร — รัน:
//   for tz in Asia/Bangkok UTC America/New_York; do TZ=$tz node src/utils/formatDate.check.mjs; done
import assert from 'node:assert/strict'
import { daysSinceTH, formatAge, formatDate, formatDateTime, todayTH } from './formatDate.js'
import { overdueDays } from './dueDate.js'
import { previewFine } from './fine.js'

// 21 ก.ย. 01:30 น. เวลาไทย = ยังเป็น 20 ก.ย. ตาม UTC — ช่วงที่เคยได้ "เมื่อวาน"
Date.now = () => Date.parse('2026-09-20T18:30:00Z')

assert.equal(todayTH(), '2026-09-21')
assert.equal(todayTH(1), '2026-09-22')
assert.equal(daysSinceTH('2026-09-20'), 1)
assert.equal(daysSinceTH('2026-09-21'), 0)
assert.equal(formatAge('2026-09-21'), '0 วัน')

assert.equal(formatDate('2026-09-05'), '05/09/2026')
assert.equal(formatDate('2026-09-20T18:30:00Z'), '21/09/2026')
assert.equal(formatDateTime('2026-09-20T18:30:00+00:00'), '21/09/2026 01:30')
assert.equal(formatDateTime('2026-07-09T09:09:32.433920Z'), '09/07/2026 16:09')  // microseconds จาก API
assert.equal(formatDateTime('2026-09-21T13:00'), '21/09/2026 13:00')  // datetime-local = เวลาไทยอยู่แล้ว
assert.equal(formatDateTime('2026-09-21'), '21/09/2026')

assert.equal(overdueDays({ due_date: '2026-09-19', returned: false }, {}), 2)
const fine = previewFine({ due_date: '2026-09-19', book_value: 0 }, {}, 'ok',
  [{ key: 'fine_per_day_per_item', value: '10' }, { key: 'fine_grace_days', value: '0' }])
assert.equal(fine.daysLate, 2)

console.log(`ok (TZ=${process.env.TZ ?? 'ค่าเครื่อง'})`)
