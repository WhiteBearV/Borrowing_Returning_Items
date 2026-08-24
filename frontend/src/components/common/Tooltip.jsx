import { useRef, useState } from 'react'
import { createPortal } from 'react-dom'

// ปุ่ม "?" เล็กๆ ไว้อธิบายจุดที่ผู้ใช้งานอาจงงหรือฟีเจอร์ที่ไม่ชัดเจนในตัวเอง — กดหรือ hover เพื่อดูคำอธิบาย
// ตั้งใจใช้เฉพาะจุดสำคัญจริงๆ ไม่ใช่ใส่ทุกที่ (ดู CLAUDE.md — ไม่เพิ่ม library ใหม่, ใช้ Tailwind ล้วน)
//
// bubble ต้อง portal ออกไปที่ document.body + position: fixed แทน absolute ธรรมดา — เคยลองแบบ absolute
// อยู่ในตารางที่มี overflow-x-auto (เช่นหน้าจัดการอุปกรณ์) แล้วเจอบั๊กจริง: bubble ดันความกว้างของ
// ตารางจนเกิด scrollbar แนวนอน ทำให้แถวขยับ ปุ่ม "?" เลื่อนหลุดจากใต้ cursor ที่ค้างอยู่ที่เดิม
// mouseleave ยิง → bubble หาย → scrollbar หาย → ปุ่มเลื่อนกลับมาอยู่ใต้ cursor → mouseenter ยิงอีก
// วนซ้ำเป็นจอกระพริบไม่หยุด (เดียวกับที่ NotificationBell.jsx ต้อง portal หนี sidebar overflow มาก่อนแล้ว)
export default function Tooltip({ text, side = 'right' }) {
  const [show, setShow] = useState(false)
  const [pos, setPos] = useState(null)
  const btnRef = useRef(null)

  const reposition = () => {
    if (!btnRef.current) return
    const r = btnRef.current.getBoundingClientRect()
    const byside = {
      right: { top: r.top + r.height / 2, left: r.right + 8, transform: 'translateY(-50%)' },
      left: { top: r.top + r.height / 2, left: r.left - 8, transform: 'translate(-100%, -50%)' },
      top: { top: r.top - 8, left: r.left + r.width / 2, transform: 'translate(-50%, -100%)' },
      bottom: { top: r.bottom + 8, left: r.left + r.width / 2, transform: 'translateX(-50%)' },
    }
    setPos(byside[side])
  }

  const open = () => { reposition(); setShow(true) }
  const close = () => setShow(false)

  return (
    <span className="relative inline-flex">
      <button
        ref={btnRef}
        type="button"
        onMouseEnter={open}
        onMouseLeave={close}
        onClick={() => (show ? close() : open())}
        aria-label="คำอธิบายเพิ่มเติม"
        className="w-4 h-4 rounded-full bg-gray-200 text-gray-500 text-[10px] font-bold flex items-center justify-center hover:bg-primary-100 hover:text-primary-700"
      >
        ?
      </button>
      {show && pos && createPortal(
        <span
          role="tooltip"
          style={pos}
          className="fixed z-50 w-56 rounded-lg bg-gray-800 text-white text-xs leading-relaxed px-3 py-2 shadow-lg whitespace-pre-line"
        >
          {text}
        </span>,
        document.body
      )}
    </span>
  )
}
