import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api/axiosInstance.js'
import Tooltip from '../../components/common/Tooltip.jsx'

export default function DashboardPage() {
  const [summary, setSummary] = useState({
    pending_requests: 0, overdue_requests: 0, low_stock_items: 0, active_borrows: 0, equipment_borrowed_out: 0,
    equipment_counts: { durable: 0, material: 0, consumable: 0, total: 0 },
    consumed_value_this_month: 0,
  })

  useEffect(() => {
    api.get('/dashboard/summary').then((r) => setSummary(r.data)).catch(() => {})
  }, [])

  const equipmentCounts = [
    { label: 'ครุภัณฑ์', value: summary.equipment_counts.durable, itemType: 'durable' },
    { label: 'วัสดุ', value: summary.equipment_counts.material, itemType: 'material' },
    { label: 'วัสดุสิ้นเปลือง', value: summary.equipment_counts.consumable, itemType: 'consumable' },
  ]

  const shortcuts = [
    { label: 'อนุมัติคำขอ', sub: 'รายการรออนุมัติ', href: '/admin/borrow-requests' },
    { label: 'จัดการอุปกรณ์', sub: 'เพิ่ม / แก้ไข / ปลดระวาง', href: '/admin/equipment' },
    { label: 'ประวัติการยืม', sub: 'ดูและยืนยันรับคืน', href: '/admin/borrows' },
    { label: 'จัดการผู้ใช้', sub: 'เปิด/ปิดบัญชี', href: '/admin/users' },
  ]

  return (
    <div className="max-w-5xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-light text-gray-800 mb-8">Admin Dashboard</h1>

      {/* Bento grid — ขนาด tile แปรตามความสำคัญ ไม่ใช่ตารางเท่ากันหมด */}
      <div className="grid grid-cols-4 [grid-auto-flow:dense] auto-rows-[110px] gap-4 mb-3">
        <Link to="/admin/borrow-requests"
          className="col-span-2 row-span-2 rounded-2xl p-6 flex flex-col justify-between bg-yellow-50 text-yellow-700 hover:opacity-80 transition-opacity">
          <p className="text-sm font-semibold">รออนุมัติ</p>
          <p className="text-6xl font-bold">{summary.pending_requests}</p>
        </Link>
        <Link to="/admin/borrows"
          className="col-span-2 rounded-2xl p-5 flex items-center justify-between bg-red-50 text-red-700 hover:opacity-80 transition-opacity">
          <p className="text-sm font-medium">เกินกำหนดคืน</p>
          <p className="text-4xl font-bold">{summary.overdue_requests}</p>
        </Link>
        <Link to="/admin/equipment?status=low_stock"
          className="rounded-2xl p-5 flex flex-col justify-between bg-orange-50 text-orange-700 hover:opacity-80 transition-opacity">
          <p className="text-sm font-medium">สต็อกต่ำ</p>
          <p className="text-3xl font-bold">{summary.low_stock_items}</p>
        </Link>
        <Link to="/admin/borrows?status=approved"
          className="rounded-2xl p-5 flex flex-col justify-between bg-primary-50 text-primary-700 hover:opacity-80 transition-opacity">
          <p className="text-sm font-medium">คำขอที่ยืมอยู่</p>
          <p className="text-3xl font-bold">{summary.active_borrows}</p>
        </Link>
        <Link to="/admin/equipment?status=borrowed"
          className="col-span-2 rounded-2xl p-5 flex items-center justify-between bg-indigo-50 text-indigo-700 hover:opacity-80 transition-opacity">
          <span className="flex items-center gap-1.5 text-sm font-medium">
            อุปกรณ์ที่ถูกยืมอยู่
            <span onClick={(e) => e.preventDefault()}><Tooltip text={'จำนวนอุปกรณ์ที่มีคำขอ "อนุมัติแล้ว" และยังไม่รับคืน — ต่างจาก "คำขอที่ยืมอยู่" ซึ่งนับเป็นคำขอ 1 ใบ อาจมีของหลายชิ้น'} side="top" /></span>
          </span>
          <p className="text-4xl font-bold">{summary.equipment_borrowed_out}</p>
        </Link>
        <div className="col-span-2 rounded-2xl p-5 flex items-center justify-between bg-emerald-50 text-emerald-700">
          <p className="text-sm font-medium">มูลค่าวัสดุที่ใช้ไปเดือนนี้ (บาท)</p>
          <p className="text-3xl font-bold">
            {summary.consumed_value_this_month.toLocaleString('th-TH', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </p>
        </div>
      </div>

      {/* ภาพรวมคลังอุปกรณ์ — สีกลาง แยกจาก tile แจ้งเตือนด้านบน */}
      <p className="text-sm font-semibold text-gray-500 mb-3 mt-8">ภาพรวมคลังอุปกรณ์</p>
      <div className="grid grid-cols-4 gap-4 mb-8">
        {equipmentCounts.map((c) => (
          <Link key={c.label} to={`/admin/equipment?item_type=${c.itemType}`} className="rounded-xl p-5 text-center bg-slate-50 text-slate-700 hover:opacity-80 transition-opacity">
            <p className="text-3xl font-bold">{c.value}</p>
            <p className="text-sm mt-1">{c.label}</p>
          </Link>
        ))}
        <Link to="/admin/equipment" className="rounded-xl p-5 text-center bg-slate-700 text-white hover:opacity-80 transition-opacity">
          <p className="text-3xl font-bold">{summary.equipment_counts.total}</p>
          <p className="text-sm mt-1 text-slate-300">รวมทั้งหมด</p>
        </Link>
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
