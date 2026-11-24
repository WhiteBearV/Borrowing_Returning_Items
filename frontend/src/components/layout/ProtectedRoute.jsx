import { useState } from 'react'
import { Link, Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuthContext } from '../../context/AuthContext.jsx'
import Sidebar from './Sidebar.jsx'
import NotificationBell from './NotificationBell.jsx'
import FeedbackButton from './FeedbackButton.jsx'
import PatchNoteModal from './PatchNoteModal.jsx'
import { isStaff, isSuperadmin, roleBadgeClass, roleLabel } from '../../utils/role.js'

// คู่มือในระบบ (public/manual — สร้างจาก Plans/manual-src/build.py) เปิดในแท็บใหม่ อ่านได้ไม่ต้องดาวน์โหลด
const manualFor = (user) => (isSuperadmin(user) ? '/manual/superadmin.html' : isStaff(user) ? '/manual/staff.html' : '/manual/borrower.html')

const avatarSrc = (url) =>
  (url?.startsWith('/') ? `${import.meta.env.VITE_API_URL || 'http://localhost:8000'}${url}` : url)

export default function ProtectedRoute({ role }) {
  const { user, loading } = useAuthContext()
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const location = useLocation()

  if (loading) return <div className="flex items-center justify-center h-screen text-gray-400 text-sm">Loading…</div>
  // จำหน้าที่ตั้งใจจะเข้า (เช่น สแกน QR อุปกรณ์ตอนยังไม่ล็อกอิน) ไว้ใน state — LoginPage อ่านค่านี้
  // เพื่อพากลับไปหน้าเดิมหลังล็อกอินสำเร็จ แทนที่จะเด้งไปหน้าแรกเสมอ
  if (!user) return <Navigate to="/login" state={{ from: location }} replace />
  // role="admin" = เจ้าหน้าที่ขึ้นไป (superadmin ผ่านด้วย) / role="superadmin" = เฉพาะระดับสูงสุด
  // ตรงกับฝั่ง backend: require_admin ปล่อย superadmin ผ่าน ดู app/utils/roles.py
  const allowed = !role
    || (role === 'admin' && isStaff(user))
    || (role === 'superadmin' && isSuperadmin(user))
    || (role === 'student' && user.role === 'student')
  if (!allowed) {
    return <Navigate to={isStaff(user) ? '/admin/dashboard' : '/dashboard'} replace />
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      <div className="flex flex-col min-w-0">
        {/* เมนูเป็น drawer ที่ซ่อนไว้เสมอ (ทุกขนาดจอ) ต้องมีปุ่มแฮมเบอร์เกอร์เปิด */}
        <header className="sticky top-0 z-30 flex items-center gap-1 sm:gap-3 bg-white border-b border-gray-200 px-4 py-3">
          <button
            onClick={() => setSidebarOpen(true)}
            aria-label="เปิดเมนู"
            className="p-1.5 -ml-1.5 rounded-lg text-gray-600 hover:bg-gray-100"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="w-6 h-6">
              <path d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
          <Link to={isStaff(user) ? '/admin/dashboard' : '/dashboard'} className="ml-1 font-bold text-gray-800 text-sm flex-1 min-w-0 truncate hover:text-primary-700">
            ระบบยืม-คืนอุปกรณ์
          </Link>
          {/* มินิโปรไฟล์ — เรียงตามที่ผู้ใช้ขอ 8 ก.ย. 69: กระดิ่ง → รูป → ชื่อ → สิทธิ์
              กดที่ชื่อ/รูปไปหน้าโปรไฟล์ได้เลย (เดิมต้องเปิด drawer ก่อน) */}
          <a href={manualFor(user)} target="_blank" rel="noopener" title="คู่มือการใช้งาน" aria-label="คู่มือการใช้งาน"
            className="p-1.5 rounded-lg text-gray-600 hover:bg-gray-100">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
              strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5">
              <path d="M2 4h6a4 4 0 0 1 4 4v13a3 3 0 0 0-3-3H2zM22 4h-6a4 4 0 0 0-4 4v13a3 3 0 0 1 3-3h7z" />
            </svg>
          </a>
          <PatchNoteModal />
          <FeedbackButton />
          <NotificationBell />
          <Link to="/profile" title={`${user.full_name} (${roleLabel(user.role)})`} className="flex shrink-0 items-center gap-2 rounded-full p-1 sm:pr-2 hover:bg-gray-100">
            {user.avatar_url ? (
              <img src={avatarSrc(user.avatar_url)} alt=""
                className="w-7 h-7 rounded-full object-cover border border-gray-200" />
            ) : (
              <span className="w-7 h-7 rounded-full bg-primary-100 text-primary-700 text-xs font-semibold
                flex items-center justify-center">
                {(user.full_name || '?').trim().charAt(0)}
              </span>
            )}
            {/* มือถือแสดงแค่รูปโปรไฟล์ — ชื่อ+ป้ายสิทธิ์ดันแถบหัวล้นจอจนทั้งหน้าเลื่อนซ้ายขวา (iPhone 13, 24 พ.ย. 69) */}
            <span className="hidden sm:inline text-xs text-gray-700 truncate max-w-[12rem]">{user.full_name}</span>
            <span className={`hidden sm:inline text-xs px-1.5 py-0.5 rounded whitespace-nowrap ${roleBadgeClass(user.role)}`}>
              {roleLabel(user.role)}
            </span>
          </Link>
        </header>
        <main className="flex-1 overflow-y-auto min-w-0">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
