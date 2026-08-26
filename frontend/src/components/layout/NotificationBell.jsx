import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { notificationApi } from '../../api/notificationApi.js'
import { useAuthContext } from '../../context/AuthContext.jsx'

// พาไปหน้าที่เกี่ยวข้องกับคำขอที่แจ้งเตือนถึง
// new_request_admin / return_requested_admin ส่งให้แอดมินเท่านั้น (ดู borrow_service.py _notify)
// จึงพาไปหน้าที่ต้อง "ทำอะไรสักอย่าง" ตรงจุด ไม่ใช่หน้ารายการของตัวเอง
// overdue ส่งทั้งนักศึกษา (เรื่องคำขอตัวเอง) และแอดมิน (เรื่องคำขอของคนอื่น) ด้วย type เดียวกัน
// จึงต้องแยกตาม role ของคนที่กำลังดูอยู่ ไม่ใช่แยกตาม type อย่างเดียว
const notificationTarget = (n, role) => {
  if (!n.borrow_request_id) return null
  if (n.type === 'new_request_admin') return `/admin/borrow-requests?request=${n.borrow_request_id}`
  // BorrowRequestsPage (หน้า "อนุมัติคำขอ") ตอนนี้โชว์ทั้ง pending + แจ้งขอคืน + คำขอต่อเวลาในหน้าเดียว
  if (n.type === 'return_requested_admin') return `/admin/borrow-requests?request=${n.borrow_request_id}`
  if (n.type === 'renew_requested_admin') return `/admin/borrow-requests?request=${n.borrow_request_id}`
  if (n.type === 'overdue' && role === 'admin') return `/admin/borrows?request=${n.borrow_request_id}`
  return `/my-borrows?request=${n.borrow_request_id}`
}

function timeAgo(iso) {
  const min = Math.floor((Date.now() - new Date(iso).getTime()) / 60000)
  if (min < 1) return 'เมื่อสักครู่'
  if (min < 60) return `${min} นาทีที่แล้ว`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr} ชม.ที่แล้ว`
  return `${Math.floor(hr / 24)} วันที่แล้ว`
}

// ไฟล์เสียงอยู่ที่ frontend/public/notification.wav — เบราว์เซอร์อาจบล็อก autoplay
// จนกว่าจะมี user gesture บนหน้า (login ก็นับ) เงียบไว้ถ้ายัง unlock ไม่ได้ ไม่ทำให้ bell พัง
function beep() {
  new Audio('/notification.wav').play().catch(() => {})
}

export default function NotificationBell() {
  const { user } = useAuthContext()
  const navigate = useNavigate()
  const [items, setItems] = useState([])
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState({ top: 0, left: 0 })
  const boxRef = useRef(null)
  const dropdownRef = useRef(null)
  const seenIds = useRef(null) // null = ยังไม่โหลดรอบแรก

  useEffect(() => {
    const load = () => notificationApi.listMine({ page: 1, page_size: 20 }).then((data) => {
      const list = data.items ?? []
      const unreadIds = list.filter((n) => !n.is_read).map((n) => n.id)
      if (seenIds.current === null) {
        // รอบแรกที่โหลด: จำ backlog เดิมไว้เฉยๆ ไม่ดัง กันเสียงดังทันทีตอนเปิดหน้า
        seenIds.current = new Set(unreadIds)
      } else {
        const hasNew = unreadIds.some((id) => !seenIds.current.has(id))
        if (hasNew) beep()
        seenIds.current = new Set(unreadIds)
      }
      setItems(list)
    })
    load()
    // ponytail: poll แทน websocket — เดิม 10s รู้สึกหน่วงตอนรอแจ้งเตือนคืนของ/ขอคืน ลดเหลือ 4s
    // (backend เขียน notification ทันทีเมื่อ action เกิด ไม่มี lag ฝั่ง backend เลย เช็คแล้ว)
    const id = setInterval(load, 4000)
    return () => clearInterval(id)
  }, [user])

  useEffect(() => {
    const onClickOutside = (e) => {
      if (
        boxRef.current && !boxRef.current.contains(e.target) &&
        dropdownRef.current && !dropdownRef.current.contains(e.target)
      ) setOpen(false)
    }
    document.addEventListener('mousedown', onClickOutside)
    return () => document.removeEventListener('mousedown', onClickOutside)
  }, [])

  // dropdown ต้อง portal ออกไปที่ document.body เพราะ sidebar ที่ครอบอยู่มี
  // overflow-y-auto + transform (drawer มือถือ) ซึ่งตัดขอบ/เลื่อนตำแหน่ง absolute ผิดที่
  // ตำแหน่งจึงต้องคำนวณเองจาก bounding rect ของปุ่มกระดิ่งแทนการอิง relative wrapper
  const DROPDOWN_WIDTH = 288 // w-72
  const reposition = () => {
    if (!boxRef.current) return
    const r = boxRef.current.getBoundingClientRect()
    // ปุ่มอยู่มุมขวาบน header เสมอ — ชิดขวาปุ่มไว้ก่อน แล้ว clamp กันล้นขอบซ้าย/ขวาของจอ
    // (เดิมอิง left ของปุ่มตรงๆ ใช้ได้ตอนกระดิ่งอยู่ใน sidebar ฝั่งซ้าย พอย้ายมาไว้ขวา header
    // dropdown กว้าง 288px เลยทะลุขอบจอขวาไปเกือบหมด อ่านไม่ออก)
    const left = Math.max(8, Math.min(r.right - DROPDOWN_WIDTH, window.innerWidth - DROPDOWN_WIDTH - 8))
    setPos({ top: r.bottom + 8, left })
  }

  useEffect(() => {
    if (!open) return
    reposition()
    window.addEventListener('resize', reposition)
    return () => window.removeEventListener('resize', reposition)
  }, [open])

  const unread = items.filter((n) => !n.is_read).length

  const markAllRead = async () => {
    await notificationApi.markAllRead()
    setItems((prev) => prev.map((n) => ({ ...n, is_read: true })))
  }

  const handleClick = async (n) => {
    if (!n.is_read) {
      await notificationApi.markRead(n.id)
      setItems((prev) => prev.map((x) => (x.id === n.id ? { ...x, is_read: true } : x)))
    }
    const target = notificationTarget(n, user?.role)
    if (target) {
      setOpen(false)
      navigate(target)
    }
  }

  return (
    <div className="relative" ref={boxRef}>
      <button
        onClick={() => setOpen((o) => !o)}
        className="relative rounded-lg p-2 text-gray-500 hover:bg-gray-100 hover:text-gray-700"
        aria-label="การแจ้งเตือน"
      >
        🔔
        {unread > 0 && (
          <span className="absolute -top-0.5 -right-0.5 bg-red-500 text-white text-[10px] rounded-full w-4 h-4 flex items-center justify-center">
            {unread > 9 ? '9+' : unread}
          </span>
        )}
      </button>

      {open && createPortal(
        <div
          ref={dropdownRef}
          style={{ top: pos.top, left: pos.left }}
          className="fixed w-72 max-h-96 overflow-y-auto rounded-xl border border-gray-200 bg-white shadow-lg z-50"
        >
          <div className="flex items-center justify-between px-3 py-2 border-b border-gray-100">
            <p className="text-xs font-semibold text-gray-500">การแจ้งเตือน</p>
            {unread > 0 && (
              <button onClick={markAllRead} className="text-xs text-primary-600 hover:underline">
                ทำเครื่องหมายว่าอ่านแล้วทั้งหมด
              </button>
            )}
          </div>
          {items.length === 0 ? (
            <p className="px-3 py-4 text-sm text-gray-400 text-center">ไม่มีการแจ้งเตือน</p>
          ) : (
            items.map((n) => (
              <button
                key={n.id}
                onClick={() => handleClick(n)}
                className={`block w-full text-left px-3 py-2 text-xs border-b border-gray-50 hover:bg-gray-50 ${
                  n.is_read ? 'text-gray-400' : 'text-gray-800 bg-primary-50/40'
                }`}
              >
                <p>{n.message}</p>
                <p className="mt-0.5 text-[10px] text-gray-400">{timeAgo(n.sent_at)}</p>
              </button>
            ))
          )}
        </div>,
        document.body
      )}
    </div>
  )
}
