import { useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { useAuthContext } from '../../context/AuthContext.jsx'
import { useCart } from '../../context/CartContext.jsx'
import ConfirmModal from '../common/ConfirmModal.jsx'
import NotificationBell from './NotificationBell.jsx'

const STUDENT_NAV = [
  { to: '/dashboard',  label: 'หน้าหลัก' },
  { to: '/equipment',  label: 'อุปกรณ์' },
  { to: '/borrow',     label: 'ตะกร้า', cart: true },
  { to: '/my-borrows', label: 'คำขอของฉัน' },
  { to: '/profile',    label: 'โปรไฟล์' },
]

const ADMIN_NAV = [
  { to: '/admin/dashboard',       label: 'Dashboard' },
  { to: '/admin/borrow-requests', label: 'อนุมัติคำขอ' },
  { to: '/admin/borrows',         label: 'ประวัติการยืม' },
  { to: '/admin/equipment',       label: 'จัดการอุปกรณ์' },
  { to: '/admin/bundles',         label: 'ชุดอุปกรณ์' },
  { to: '/admin/users',           label: 'จัดการผู้ใช้' },
  { to: '/admin/audit',           label: 'Audit Log' },
  { to: '/admin/settings',        label: 'การตั้งค่า' },
  { to: '/equipment',             label: 'ยืมอุปกรณ์' },
  { to: '/borrow',                label: 'ตะกร้า', cart: true },
  // admin ดูคำขอตัวเองได้ในหน้า "ประวัติการยืม" อยู่แล้ว จึงไม่ต้องมี "คำขอของฉัน" แยก
  { to: '/profile',               label: 'โปรไฟล์' },
]

const linkClass = ({ isActive }) =>
  `flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
    isActive
      ? 'bg-blue-50 text-blue-700'
      : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
  }`

export default function Sidebar({ open, onClose }) {
  const { user, logout } = useAuthContext()
  const { cart } = useCart()
  const navigate = useNavigate()
  const nav = user?.role === 'admin' ? ADMIN_NAV : STUDENT_NAV
  const [showLogoutConfirm, setShowLogoutConfirm] = useState(false)

  const handleLogout = () => {
    logout()
    navigate('/login', { replace: true })
  }

  return (
    <>
      {/* Backdrop มือถือ — แตะเพื่อปิด drawer */}
      {open && (
        <div
          className="fixed inset-0 bg-black/40 z-40 md:hidden"
          onClick={onClose}
          aria-hidden="true"
        />
      )}

      <aside
        className={`flex flex-col w-64 md:w-56 shrink-0 border-r border-gray-200 bg-white h-screen overflow-y-auto
        fixed inset-y-0 left-0 z-50 transform transition-transform duration-200 ease-in-out
        ${open ? 'translate-x-0' : '-translate-x-full'}
        md:translate-x-0 md:sticky md:top-0 md:z-auto`}
      >
        {/* Logo */}
        <div className="px-4 py-5 border-b border-gray-100 flex items-start justify-between gap-2">
          <div>
            <p className="font-bold text-gray-800 text-sm leading-tight">ระบบยืม-คืนอุปกรณ์</p>
            {user?.role === 'admin' && (
              <span className="text-xs bg-purple-100 text-purple-700 px-1.5 py-0.5 rounded mt-1 inline-block">Admin</span>
            )}
          </div>
          <NotificationBell />
        </div>

        {/* Nav links */}
        <nav className="flex-1 px-3 py-4 space-y-1">
          {nav.map(({ to, label, cart: showCart }) => (
            <NavLink key={to} to={to} className={linkClass} onClick={onClose}>
              {label}
              {showCart && cart.length > 0 && (
                <span className="ml-auto bg-blue-600 text-white text-xs rounded-full w-5 h-5 flex items-center justify-center">
                  {cart.length}
                </span>
              )}
            </NavLink>
          ))}
        </nav>

        {/* User + logout */}
        <div className="px-4 py-4 border-t border-gray-100 space-y-2">
          <p className="text-xs font-medium text-gray-700 truncate">{user?.full_name}</p>
          <p className="text-xs text-gray-400 truncate">{user?.email}</p>
          <button
            onClick={() => setShowLogoutConfirm(true)}
            className="w-full text-left text-xs text-red-500 hover:text-red-700 mt-1"
          >
            ออกจากระบบ
          </button>
        </div>

        {showLogoutConfirm && (
          <ConfirmModal
            title="ออกจากระบบ"
            message="ต้องการออกจากระบบใช่หรือไม่?"
            confirmLabel="ออกจากระบบ"
            danger
            onConfirm={handleLogout}
            onCancel={() => setShowLogoutConfirm(false)}
          />
        )}
      </aside>
    </>
  )
}
