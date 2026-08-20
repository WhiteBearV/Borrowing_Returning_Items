import { useState } from 'react'

// ปุ่ม "?" เล็กๆ ไว้อธิบายจุดที่ผู้ใช้งานอาจงงหรือฟีเจอร์ที่ไม่ชัดเจนในตัวเอง — กดหรือ hover เพื่อดูคำอธิบาย
// ตั้งใจใช้เฉพาะจุดสำคัญจริงๆ ไม่ใช่ใส่ทุกที่ (ดู CLAUDE.md — ไม่เพิ่ม library ใหม่, ใช้ Tailwind ล้วน)
export default function Tooltip({ text, side = 'right' }) {
  const [show, setShow] = useState(false)

  const posClass = {
    right: 'left-full ml-2 top-1/2 -translate-y-1/2',
    left: 'right-full mr-2 top-1/2 -translate-y-1/2',
    top: 'bottom-full mb-2 left-1/2 -translate-x-1/2',
    bottom: 'top-full mt-2 left-1/2 -translate-x-1/2',
  }[side]

  return (
    <span className="relative inline-flex">
      <button
        type="button"
        onMouseEnter={() => setShow(true)}
        onMouseLeave={() => setShow(false)}
        onClick={() => setShow((s) => !s)}
        aria-label="คำอธิบายเพิ่มเติม"
        className="w-4 h-4 rounded-full bg-gray-200 text-gray-500 text-[10px] font-bold flex items-center justify-center hover:bg-primary-100 hover:text-primary-700"
      >
        ?
      </button>
      {show && (
        <span
          role="tooltip"
          className={`absolute z-50 w-56 rounded-lg bg-gray-800 text-white text-xs leading-relaxed px-3 py-2 shadow-lg whitespace-pre-line ${posClass}`}
        >
          {text}
        </span>
      )}
    </span>
  )
}
