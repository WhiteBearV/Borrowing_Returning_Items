/** ISO date/datetime string -> "DD/MM/YYYY" (ไม่ใช้ toLocaleDateString('th-TH') เพราะเป็นปี พ.ศ. และไม่ zero-pad) */
export function formatDate(isoString) {
  if (!isoString) return ''
  const [y, m, d] = isoString.slice(0, 10).split('-')
  return `${d}/${m}/${y}`
}

/** วันที่ได้มา -> อายุอ่านง่าย เช่น "5 ปี 3 เดือน" / "2 เดือน" / "12 วัน" — ไม่มีวันที่ = "—" */
export function formatAge(isoDate) {
  if (!isoDate) return '—'
  const from = new Date(isoDate.slice(0, 10))
  if (Number.isNaN(from.getTime())) return '—'
  const days = Math.floor((Date.now() - from.getTime()) / 86400000)
  if (days < 0) return '—'          // ลงวันที่ไว้ในอนาคต (พิมพ์ผิด) อย่าโชว์เป็นอายุติดลบ
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

/** ISO datetime -> "DD/MM/YYYY HH:MM" ตามเวลาเครื่องผู้ใช้ (นัดรับ/นัดคืน ต้องเห็นเวลาด้วย ไม่ใช่แค่วัน) */
export function formatDateTime(isoString) {
  if (!isoString) return ''
  const d = new Date(isoString)
  if (Number.isNaN(d.getTime())) return formatDate(isoString)
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
