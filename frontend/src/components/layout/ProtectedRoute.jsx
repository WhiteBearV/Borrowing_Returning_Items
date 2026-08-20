import { useState } from 'react'
import { Link, Navigate, Outlet } from 'react-router-dom'
import { useAuthContext } from '../../context/AuthContext.jsx'
import Sidebar from './Sidebar.jsx'
import NotificationBell from './NotificationBell.jsx'

export default function ProtectedRoute({ role }) {
  const { user, loading } = useAuthContext()
  const [sidebarOpen, setSidebarOpen] = useState(false)

  if (loading) return <div className="flex items-center justify-center h-screen text-gray-400 text-sm">Loading…</div>
  if (!user) return <Navigate to="/login" replace />
  if (role && user.role !== role) {
    return <Navigate to={user.role === 'admin' ? '/admin/dashboard' : '/dashboard'} replace />
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      <div className="flex flex-col min-w-0">
        {/* เมนูเป็น drawer ที่ซ่อนไว้เสมอ (ทุกขนาดจอ) ต้องมีปุ่มแฮมเบอร์เกอร์เปิด */}
        <header className="sticky top-0 z-30 flex items-center gap-3 bg-white border-b border-gray-200 px-4 py-3">
          <button
            onClick={() => setSidebarOpen(true)}
            aria-label="เปิดเมนู"
            className="p-1.5 -ml-1.5 rounded-lg text-gray-600 hover:bg-gray-100"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="w-6 h-6">
              <path d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
          <Link to={user.role === 'admin' ? '/admin/dashboard' : '/dashboard'} className="font-bold text-gray-800 text-sm flex-1 hover:text-primary-700">
            ระบบยืม-คืนอุปกรณ์
          </Link>
          <NotificationBell />
        </header>
        <main className="flex-1 overflow-y-auto min-w-0">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
