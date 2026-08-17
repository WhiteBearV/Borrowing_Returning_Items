/** ISO date/datetime string -> "DD/MM/YYYY" (ไม่ใช้ toLocaleDateString('th-TH') เพราะเป็นปี พ.ศ. และไม่ zero-pad) */
export function formatDate(isoString) {
  if (!isoString) return ''
  const [y, m, d] = isoString.slice(0, 10).split('-')
  return `${d}/${m}/${y}`
}
