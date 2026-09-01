// ที่เดียวที่นิยามป้าย/สีสถานะอุปกรณ์ — เดิมนิยามซ้ำ 3 ที่ (EquipmentManagePage/EquipmentListPage/
// EquipmentDetailPage) คำไทยไม่ตรงกัน ("พร้อม" vs "พร้อมให้ยืม") ไฟล์อื่น import STATUS_LABEL จากที่นี่แทน
export const STATUS_LABEL = {
  available: 'พร้อมให้ยืม', borrowed: 'ถูกยืมอยู่', under_repair: 'ซ่อมอยู่',
  damaged: 'เสียหาย', retired: 'ปลดระวาง', unavailable: 'ไม่อนุญาตให้ยืม',
}
const STATUS_STYLE = {
  available: 'bg-green-100 text-green-700', borrowed: 'bg-primary-100 text-primary-700',
  under_repair: 'bg-yellow-100 text-yellow-700', damaged: 'bg-red-100 text-red-700',
  retired: 'bg-gray-100 text-gray-400', unavailable: 'bg-gray-100 text-gray-500',
}

// isCurrentlyBorrowed: equipment.status ฝั่ง backend ไม่เปลี่ยนเป็น "borrowed" ตอนถูกยืม (ยังเป็น "available"
// เหมือนเดิม แค่ quantity_available ลดลง) — ต้องส่ง flag จริงจาก is_currently_borrowed มาเอง ถ้าอยากโชว์ "ถูกยืมอยู่"
// isBorrowable: ของประจำห้อง (is_borrowable=false) ยืมไม่ได้เสมอไม่ว่า status คอลัมน์จะเป็นอะไร (เช่น "available"
// เพราะ import ไฟล์ทะเบียนใหม่เขียนทับ status แต่ไม่แตะ is_borrowable) — ต้องบังคับ badge เป็น "ไม่อนุญาตให้ยืม"
// ก่อนเช็ค isCurrentlyBorrowed เสมอ (ของประจำห้องไม่มีทางถูกยืมอยู่แล้วเพราะยืมไม่ได้ตั้งแต่ต้น)
export default function StatusBadge({ status, isCurrentlyBorrowed = false, isBorrowable = true }) {
  const key = !isBorrowable ? 'unavailable' : status === 'available' && isCurrentlyBorrowed ? 'borrowed' : status
  return (
    <span className={`inline-flex text-xs px-2 py-0.5 rounded-full font-medium ${STATUS_STYLE[key] ?? STATUS_STYLE.unavailable}`}>
      {STATUS_LABEL[key] ?? status}
    </span>
  )
}
