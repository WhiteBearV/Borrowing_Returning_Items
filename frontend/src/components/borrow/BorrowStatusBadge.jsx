// ที่เดียวที่นิยามป้าย/สีสถานะคำขอยืม — เดิมนิยามซ้ำ 2 ที่ (AllBorrowsPage/MyBorrowsPage) คำไทยไม่ตรงกัน
// ("ปฏิเสธ" vs "ถูกปฏิเสธ") คนละคำศัพท์กับสถานะอุปกรณ์ (StatusBadge) จึงแยกไฟล์กัน ไม่ปนกัน
export const STATUS_LABEL = {
  pending: 'รออนุมัติ', approved: 'อนุมัติแล้ว', rejected: 'ถูกปฏิเสธ',
  cancelled: 'ยกเลิกแล้ว', completed: 'คืนครบแล้ว',
}
const STATUS_STYLE = {
  pending: 'bg-yellow-100 text-yellow-700', approved: 'bg-primary-100 text-primary-700',
  rejected: 'bg-red-100 text-red-700', cancelled: 'bg-gray-100 text-gray-500',
  completed: 'bg-green-100 text-green-700',
}

export default function BorrowStatusBadge({ status }) {
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${STATUS_STYLE[status] ?? ''}`}>
      {STATUS_LABEL[status] ?? status}
    </span>
  )
}
