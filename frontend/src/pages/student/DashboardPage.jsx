import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { borrowApi } from '../../api/borrowApi.js'
import { useAuthContext } from '../../context/AuthContext.jsx'

export default function DashboardPage() {
  const { user } = useAuthContext()
  const [counts, setCounts] = useState({ active: 0, pending: 0, overdue: 0 })

  useEffect(() => {
    Promise.all([
      borrowApi.list({ status: 'approved', page_size: 1 }),
      borrowApi.list({ status: 'pending', page_size: 1 }),
      borrowApi.list({ overdue_only: true, page_size: 1 }),
    ]).then(([active, pending, overdue]) =>
      setCounts({ active: active.total, pending: pending.total, overdue: overdue.total })
    ).catch(() => {})
  }, [])

  const stats = [
    { label: 'กำลังยืมอยู่', value: counts.active, color: 'bg-blue-50 text-blue-700', href: '/my-borrows' },
    { label: 'รออนุมัติ', value: counts.pending, color: 'bg-yellow-50 text-yellow-700', href: '/my-borrows' },
    { label: 'เกินกำหนด', value: counts.overdue, color: 'bg-red-50 text-red-700', href: '/my-borrows' },
  ]

  return (
    <div className="max-w-3xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-bold text-gray-800 mb-1">
        สวัสดี, {user?.full_name ?? '…'}
      </h1>
      <p className="text-sm text-gray-400 mb-8">ระบบยืม-คืนอุปกรณ์</p>

      <div className="grid grid-cols-3 gap-4 mb-8">
        {stats.map((s) => (
          <Link key={s.label} to={s.href} className={`rounded-xl p-4 text-center ${s.color} hover:opacity-80 transition-opacity`}>
            <p className="text-3xl font-bold">{s.value}</p>
            <p className="text-sm mt-1">{s.label}</p>
          </Link>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-4">
        <Link
          to="/equipment"
          className="rounded-xl bg-white border border-gray-200 p-5 hover:shadow-md transition-shadow"
        >
          <p className="text-lg font-semibold text-gray-800 mb-1">ยืมอุปกรณ์</p>
          <p className="text-sm text-gray-400">ค้นหาและเลือกอุปกรณ์ที่ต้องการ</p>
        </Link>
        <Link
          to="/my-borrows"
          className="rounded-xl bg-white border border-gray-200 p-5 hover:shadow-md transition-shadow"
        >
          <p className="text-lg font-semibold text-gray-800 mb-1">คำขอของฉัน</p>
          <p className="text-sm text-gray-400">ติดตามสถานะและดาวน์โหลดใบยืม</p>
        </Link>
      </div>
    </div>
  )
}
