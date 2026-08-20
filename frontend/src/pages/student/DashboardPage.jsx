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

  return (
    <div className="max-w-3xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-light text-gray-800 mb-1">
        สวัสดี, {user?.full_name ?? '…'}
      </h1>
      <p className="text-sm text-gray-400 mb-8">ระบบยืม-คืนอุปกรณ์</p>

      {/* Bento grid — "กำลังยืมอยู่" เป็น tile หลัก ใหญ่กว่าอีก 2 อันเพราะเป็นสิ่งที่นักศึกษาอยากรู้ที่สุด */}
      <div className="grid grid-cols-3 [grid-auto-flow:dense] auto-rows-[100px] gap-4 mb-8">
        <Link to="/my-borrows"
          className="col-span-2 row-span-2 rounded-2xl p-6 flex flex-col justify-between bg-primary-50 text-primary-700 hover:opacity-80 transition-opacity">
          <p className="text-sm font-semibold">กำลังยืมอยู่</p>
          <p className="text-6xl font-bold">{counts.active}</p>
        </Link>
        <Link to="/my-borrows"
          className="rounded-2xl p-4 flex flex-col justify-between bg-yellow-50 text-yellow-700 hover:opacity-80 transition-opacity">
          <p className="text-sm font-medium">รออนุมัติ</p>
          <p className="text-3xl font-bold">{counts.pending}</p>
        </Link>
        <Link to="/my-borrows"
          className="rounded-2xl p-4 flex flex-col justify-between bg-red-50 text-red-700 hover:opacity-80 transition-opacity">
          <p className="text-sm font-medium">เกินกำหนด</p>
          <p className="text-3xl font-bold">{counts.overdue}</p>
        </Link>
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
