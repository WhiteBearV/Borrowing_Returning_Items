import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api/axiosInstance.js'

export default function DashboardPage() {
  const [summary, setSummary] = useState({ pending_requests: 0, overdue_requests: 0, low_stock_items: 0 })

  useEffect(() => {
    api.get('/dashboard/summary').then((r) => setSummary(r.data)).catch(() => {})
  }, [])

  const stats = [
    { label: 'รออนุมัติ', value: summary.pending_requests, color: 'bg-yellow-50 text-yellow-700', href: '/admin/borrow-requests' },
    { label: 'เกินกำหนดคืน', value: summary.overdue_requests, color: 'bg-red-50 text-red-700', href: '/admin/borrows' },
    { label: 'สต็อกต่ำ', value: summary.low_stock_items, color: 'bg-orange-50 text-orange-700', href: '/admin/equipment' },
  ]

  const shortcuts = [
    { label: 'อนุมัติคำขอ', sub: 'รายการรออนุมัติ', href: '/admin/borrow-requests' },
    { label: 'จัดการอุปกรณ์', sub: 'เพิ่ม / แก้ไข / ปลดระวาง', href: '/admin/equipment' },
    { label: 'ประวัติการยืม', sub: 'ดูและยืนยันรับคืน', href: '/admin/borrows' },
    { label: 'จัดการผู้ใช้', sub: 'เปิด/ปิดบัญชี', href: '/admin/users' },
  ]

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-bold text-gray-800 mb-8">Admin Dashboard</h1>

      <div className="grid grid-cols-3 gap-4 mb-8">
        {stats.map((s) => (
          <Link key={s.label} to={s.href} className={`rounded-xl p-5 text-center ${s.color} hover:opacity-80 transition-opacity`}>
            <p className="text-4xl font-bold">{s.value}</p>
            <p className="text-sm mt-1">{s.label}</p>
          </Link>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-4">
        {shortcuts.map((s) => (
          <Link key={s.href} to={s.href} className="rounded-xl bg-white border border-gray-200 p-5 hover:shadow-md transition-shadow">
            <p className="font-semibold text-gray-800 mb-1">{s.label}</p>
            <p className="text-sm text-gray-400">{s.sub}</p>
          </Link>
        ))}
      </div>
    </div>
  )
}
