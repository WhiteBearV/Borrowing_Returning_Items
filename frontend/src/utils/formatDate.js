// เวลาทั้งระบบเป็นเวลาประเทศไทยเสมอ ไม่ขึ้นกับ timezone ที่ตั้งไว้ในเครื่องผู้ใช้
// ไทย = UTC+7 ตายตัว (ไม่มี daylight saving) → บวก 7 ชม. แล้วอ่านแบบ UTC ได้วัน/เวลาไทยตรง ๆ
// ห้ามใช้ new Date().toISOString().slice(0, 10) เป็น "วันนี้" — นั่นคือวันของ UTC ช่วง 00:00–07:00 น.
// เวลาไทยจะได้วันของเมื่อวาน และห้ามใช้ getDate()/getHours() ตรง ๆ (ขึ้นกับ timezone เครื่อง)
const TH_OFFSET_MS = 7 * 60 * 60 * 1000
const DAY_MS = 24 * 60 * 60 * 1000
const HAS_TZ = /(Z|[+-]\d{2}:?\d{2})$/i

/** วันที่ไทยรูป "YYYY-MM-DD" (ค่าที่ <input type="date"> ใช้) — addDays=1 คือพรุ่งนี้ */
export const todayTH = (addDays = 0) =>
  new Date(Date.now() + TH_OFFSET_MS + addDays * DAY_MS).toISOString().slice(0, 10)

/** ผ่านวันนั้นมาแล้วกี่วันตามปฏิทินไทย (ติดลบ = ยังไม่ถึง) — ใช้นับวันเกินกำหนด/อายุของ */
export const daysSinceTH = (isoDate) =>
  Math.round((Date.parse(todayTH()) - Date.parse(String(isoDate).slice(0, 10))) / DAY_MS)

/** ISO string → [ปี, เดือน, วัน, ชม., นาที] ตามเวลาไทย
 *  มี timezone ติดมา (timestamp จาก API) = แปลงเป็นเวลาไทย · ไม่มี = วันที่ล้วน หรือค่าจาก datetime-local
 *  ซึ่งเป็นเวลาไทยอยู่แล้ว (backend _to_utc ก็ถือแบบเดียวกัน) ใช้ตามตัวอักษรเลย */
function thaiParts(isoString) {
  let s = isoString
  const t = HAS_TZ.test(s) ? Date.parse(s) : NaN
  if (!Number.isNaN(t)) s = new Date(t + TH_OFFSET_MS).toISOString()
  const [date, time = ''] = s.split('T')
  return [...date.split('-'), ...time.slice(0, 5).split(':')]
}

/** ISO date/datetime string -> "DD/MM/YYYY" (ไม่ใช้ toLocaleDateString('th-TH') เพราะเป็นปี พ.ศ. และไม่ zero-pad) */
export function formatDate(isoString) {
  if (!isoString) return ''
  const [y, m, d] = thaiParts(isoString)
  return `${d}/${m}/${y}`
}

/** วันที่ได้มา -> อายุอ่านง่าย เช่น "5 ปี 3 เดือน" / "2 เดือน" / "12 วัน" — ไม่มีวันที่ = "—" */
export function formatAge(isoDate) {
  if (!isoDate) return '—'
  const days = daysSinceTH(isoDate)
  if (Number.isNaN(days) || days < 0) return '—'  // ลงวันที่ไว้ในอนาคต (พิมพ์ผิด) อย่าโชว์เป็นอายุติดลบ
  if (days < 31) return `${days} วัน`
  const months = Math.floor(days / 30.44)
  if (months < 12) return `${months} เดือน`
  const years = Math.floor(months / 12)
  const rest = months % 12
  return rest ? `${years} ปี ${rest} เดือน` : `${years} ปี`
}

/** จำนวนเงินแบบมีคอมมา — ไม่มีค่า = "—" (ตรงกับ _fmt_money ฝั่ง PDF ที่ใช้ "-") */
export function formatMoney(v) {
  if (v === null || v === undefined) return '—'
  return Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/** ISO datetime -> "DD/MM/YYYY HH:MM" เวลาไทย (นัดรับ/นัดคืน ต้องเห็นเวลาด้วย ไม่ใช่แค่วัน) */
export function formatDateTime(isoString) {
  if (!isoString) return ''
  const [y, m, d, hh, mm] = thaiParts(isoString)
  return hh ? `${d}/${m}/${y} ${hh}:${mm}` : `${d}/${m}/${y}`
}
