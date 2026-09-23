const UUID = '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'

/** แปลงสิ่งที่สแกนได้ → { equipmentId } หรือ { code }
 *  QR ที่ระบบพิมพ์คือ URL `<origin>/equipment/<uuid>` — ดึงเฉพาะ uuid ไม่สน origin (เครื่อง dev IP เปลี่ยน
 *  ได้ QR เก่ายังใช้ได้) · อย่างอื่น (บาร์โค้ดสติกเกอร์ทะเบียน/พิมพ์เอง) ถือเป็นรหัสอุปกรณ์ */
export function parseScan(text) {
  const t = (text ?? '').trim()
  const m = t.match(new RegExp(`/equipment/(${UUID})(?:[/?#]|$)`, 'i'))
  if (m) return { equipmentId: m[1].toLowerCase() }
  return t ? { code: t } : null
}
