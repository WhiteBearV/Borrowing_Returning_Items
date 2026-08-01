import { useEffect, useRef, useState } from 'react'
import { notificationApi } from '../../api/notificationApi.js'
import { useAuthContext } from '../../context/AuthContext.jsx'

function timeAgo(iso) {
  const min = Math.floor((Date.now() - new Date(iso).getTime()) / 60000)
  if (min < 1) return 'เมื่อสักครู่'
  if (min < 60) return `${min} นาทีที่แล้ว`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr} ชม.ที่แล้ว`
  return `${Math.floor(hr / 24)} วันที่แล้ว`
}

// ponytail: บี๊บสั้นๆ จาก Web Audio API แทนโหลดไฟล์เสียง — เบราว์เซอร์บล็อก autoplay
// จนกว่าจะมี user gesture บนหน้า (login ก็นับ) เงียบไว้ถ้ายัง unlock ไม่ได้ ไม่ทำให้ bell พัง
function beep() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)()
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()
    osc.connect(gain)
    gain.connect(ctx.destination)
    osc.frequency.value = 880
    gain.gain.setValueAtTime(0.2, ctx.currentTime)
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.3)
    osc.start()
    osc.stop(ctx.currentTime + 0.3)
  } catch {
    // เงียบไว้ — ไม่ให้ error เรื่องเสียงกระทบการแจ้งเตือนหลัก
  }
}

export default function NotificationBell() {
  const { user } = useAuthContext()
  const [items, setItems] = useState([])
  const [open, setOpen] = useState(false)
  const boxRef = useRef(null)
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
        if (hasNew && user?.role === 'admin') beep()
        seenIds.current = new Set(unreadIds)
      }
      setItems(list)
    })
    load()
    const id = setInterval(load, 60000) // ponytail: poll ทุก 60s แทน websocket
    return () => clearInterval(id)
  }, [user])

  useEffect(() => {
    const onClickOutside = (e) => {
      if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', onClickOutside)
    return () => document.removeEventListener('mousedown', onClickOutside)
  }, [])

  const unread = items.filter((n) => !n.is_read).length

  const handleClick = async (n) => {
    if (n.is_read) return
    await notificationApi.markRead(n.id)
    setItems((prev) => prev.map((x) => (x.id === n.id ? { ...x, is_read: true } : x)))
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

      {open && (
        <div className="absolute left-0 top-full mt-2 w-72 max-h-96 overflow-y-auto rounded-xl border border-gray-200 bg-white shadow-lg z-50">
          <p className="px-3 py-2 text-xs font-semibold text-gray-500 border-b border-gray-100">การแจ้งเตือน</p>
          {items.length === 0 ? (
            <p className="px-3 py-4 text-sm text-gray-400 text-center">ไม่มีการแจ้งเตือน</p>
          ) : (
            items.map((n) => (
              <button
                key={n.id}
                onClick={() => handleClick(n)}
                className={`block w-full text-left px-3 py-2 text-xs border-b border-gray-50 hover:bg-gray-50 ${
                  n.is_read ? 'text-gray-400' : 'text-gray-800 bg-blue-50/40'
                }`}
              >
                <p>{n.message}</p>
                <p className="mt-0.5 text-[10px] text-gray-400">{timeAgo(n.sent_at)}</p>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  )
}
