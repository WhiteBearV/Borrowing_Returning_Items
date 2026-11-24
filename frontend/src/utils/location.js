/** ห้อง + ตำแหน่งในห้อง → "15312 · ตู้A ชั้น3" — รูปแบบเดียวทุกหน้า (23 พ.ย. 69) */
export function formatPlace(room, detail) {
  return [room, detail].filter(Boolean).join(' · ')
}
