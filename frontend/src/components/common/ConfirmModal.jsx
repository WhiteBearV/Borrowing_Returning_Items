import { createPortal } from 'react-dom'

export default function ConfirmModal({ title, message, confirmLabel = 'ยืนยัน', danger = false, onConfirm, onCancel }) {
  // portal ออกไปที่ document.body — กัน parent ที่มี transform (เช่น sidebar drawer มือถือ)
  // เปลี่ยน containing block ของ position:fixed แล้วดันโมดัลไปโผล่มุมจอผิดที่แทนกึ่งกลาง
  return createPortal(
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 px-4">
      <div className="bg-white rounded-2xl p-6 w-full max-w-sm shadow-xl space-y-4">
        <h2 className="font-bold text-gray-800 text-lg">{title}</h2>
        {message && <p className="text-sm text-gray-600 whitespace-pre-line">{message}</p>}
        <div className="flex gap-3 pt-1">
          <button onClick={onCancel}
            className="flex-1 rounded-lg border border-gray-200 py-2 text-sm text-gray-600 hover:bg-gray-50">
            ยกเลิก
          </button>
          <button onClick={onConfirm}
            className={`flex-1 rounded-lg py-2 text-sm font-semibold text-white ${danger ? 'bg-red-600 hover:bg-red-700' : 'bg-blue-600 hover:bg-blue-700'}`}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>,
    document.body
  )
}
