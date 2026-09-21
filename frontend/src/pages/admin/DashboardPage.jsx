import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { dashboardApi } from '../../api/dashboardApi.js'
import Tooltip from '../../components/common/Tooltip.jsx'
import { todayTH } from '../../utils/formatDate.js'

const MAJOR_LABEL = { comp_eng: 'วิศวกรรมคอมพิวเตอร์', digital_design: 'ออกแบบดิจิทัล' }

export default function DashboardPage() {
  const [summary, setSummary] = useState({
    pending_requests: 0, overdue_requests: 0, low_stock_items: 0, active_borrows: 0, equipment_borrowed_out: 0,
    missing_price_items: 0, missing_acquired_at_items: 0,
    equipment_counts: { durable: 0, material: 0, consumable: 0, total: 0 },
    users_total: 0, users_students: 0, users_staff: 0, users_pending_approval: 0, users_by_major: [],
    users_by_year: [],
    quality_low_count: 0, quality_unassessed_count: 0,
    borrowed_value_this_month: 0,
    borrowed_value_this_year: 0,
  })

  useEffect(() => {
    dashboardApi.summary().then(setSummary).catch(() => {})
  }, [])

  const equipmentCounts = [
    { label: 'ครุภัณฑ์', value: summary.equipment_counts.durable, itemType: 'durable' },
    { label: 'วัสดุใช้ซ้ำ', value: summary.equipment_counts.material, itemType: 'material' },
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
        {/* ทางเข้าไล่เติมข้อมูลทะเบียนที่ยังขาด — ซ่อนการ์ดทิ้งเมื่อครบแล้ว จะได้ไม่รกแดชบอร์ดถาวร */}
        {summary.missing_price_items > 0 && (
          <Link to="/admin/equipment?status=no_price"
            className="rounded-2xl p-5 flex flex-col justify-between bg-rose-50 text-rose-700 hover:opacity-80 transition-opacity">
            <p className="text-sm font-medium">ยังไม่มีราคา</p>
            <p className="text-3xl font-bold">{summary.missing_price_items}</p>
          </Link>
        )}
        {summary.missing_acquired_at_items > 0 && (
          <Link to="/admin/equipment?status=no_acquired_at"
            className="rounded-2xl p-5 flex flex-col justify-between bg-amber-50 text-amber-700 hover:opacity-80 transition-opacity">
            <p className="text-sm font-medium">ยังไม่มีวันที่ได้มา</p>
            <p className="text-3xl font-bold">{summary.missing_acquired_at_items}</p>
          </Link>
        )}
        {/* การ์ดคุณภาพ (เฟส 10) — เฉพาะรุ่นที่เปิดติดตามคุณภาพ ยืมได้ตามปกติ แค่ขึ้นป้ายเตือนให้ไปตรวจสภาพ */}
        {summary.quality_low_count > 0 && (
          <Link to="/admin/equipment"
            className="rounded-2xl p-5 flex flex-col justify-between bg-rose-50 text-rose-700 hover:opacity-80 transition-opacity">
            <p className="text-sm font-medium">คุณภาพต่ำ ควรตรวจสภาพ</p>
            <p className="text-3xl font-bold">{summary.quality_low_count}</p>
          </Link>
        )}
        {summary.quality_unassessed_count > 0 && (
          <Link to="/admin/equipment"
            className="rounded-2xl p-5 flex flex-col justify-between bg-amber-50 text-amber-700 hover:opacity-80 transition-opacity">
            <p className="text-sm font-medium">เปิดติดตามแล้วแต่ยังไม่ประเมิน</p>
            <p className="text-3xl font-bold">{summary.quality_unassessed_count}</p>
          </Link>
        )}
        {/* กดแล้วไปหน้าความคุ้มค่าช่วงเดียวกัน ทุกประเภท — ยอดรายเดือนในหน้านั้นตรงกับการ์ดนี้ */}
        <Link to={`/admin/utilization?type=all&from=${todayTH().slice(0, 8) + '01'}&to=${todayTH()}`}
          className="col-span-2 rounded-2xl p-5 flex items-center justify-between bg-emerald-50 text-emerald-700 hover:opacity-80 transition-opacity">
          <p className="text-sm font-medium">มูลค่าอุปกรณ์ที่ถูกยืมออกเดือนนี้ (บาท)</p>
          <p className="text-3xl font-bold">
            {summary.borrowed_value_this_month.toLocaleString('th-TH', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </p>
        </Link>
        {/* กดแล้วไปหน้าความคุ้มค่าช่วงเดียวกัน ทุกประเภท — ยอดรายเดือนในหน้านั้นตรงกับการ์ดนี้ */}
        <Link to={`/admin/utilization?type=all&from=${todayTH().slice(0, 5) + '01-01'}&to=${todayTH()}`}
          className="col-span-2 rounded-2xl p-5 flex items-center justify-between bg-teal-50 text-teal-700 hover:opacity-80 transition-opacity">
          <p className="text-sm font-medium">มูลค่าอุปกรณ์ที่ถูกยืมออกปีนี้ (บาท)</p>
          <p className="text-3xl font-bold">
            {summary.borrowed_value_this_year.toLocaleString('th-TH', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </p>
        </Link>
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

      {/* ภาพรวมผู้ใช้ (8 ก.ย. 69) — ตอบว่าระบบมีคนใช้จริงกี่คน สาขาไหนบ้าง ไม่ใช่รู้แค่จำนวนของในคลัง */}
      <p className="text-sm font-semibold text-gray-500 mb-3">ภาพรวมผู้ใช้งาน</p>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-8">
        <Link to="/admin/users" className="rounded-xl p-5 text-center bg-indigo-600 text-white hover:opacity-80 transition-opacity">
          <p className="text-3xl font-bold">{summary.users_total}</p>
          <p className="text-sm mt-1 text-indigo-100">ผู้ใช้ทั้งหมด</p>
        </Link>
        {(summary.users_by_major ?? []).map((m) => (
          <Link key={m.major ?? 'none'} to={`/admin/users?major=${m.major ?? ''}`}
            className="rounded-xl p-5 text-center bg-indigo-50 text-indigo-800 hover:opacity-80 transition-opacity">
            <p className="text-3xl font-bold">{m.count}</p>
            <p className="text-sm mt-1">{MAJOR_LABEL[m.major] ?? 'ไม่ระบุสาขา'}</p>
          </Link>
        ))}
        <div className="rounded-xl p-5 text-center bg-slate-50 text-slate-700">
          <p className="text-3xl font-bold">{summary.users_staff}</p>
          <p className="text-sm mt-1">เจ้าหน้าที่ (ผู้ดูแล)</p>
        </div>
        {summary.users_pending_approval > 0 && (
          <Link to="/admin/users" className="rounded-xl p-5 text-center bg-amber-100 text-amber-800 hover:opacity-80 transition-opacity">
            <p className="text-3xl font-bold">{summary.users_pending_approval}</p>
            <p className="text-sm mt-1">ผู้สมัครรออนุมัติ</p>
          </Link>
        )}
      </div>

      {/* ภาพรวมชั้นปี (เฟส 10) — รวมกลุ่มตกค้างแยกจากปี 1-4 คำนวณสดจากรหัสนักศึกษา */}
      {summary.users_by_year?.length > 0 && (
        <>
          <p className="text-sm font-semibold text-gray-500 mb-3">ภาพรวมชั้นปี</p>
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-4 mb-8">
            {summary.users_by_year.map((y) => (
              // ลิงก์ด้วยคีย์แบบเครื่องอ่านจาก backend (y.group) ตรง ๆ ไม่ใช่แกะป้ายภาษาไทยด้วย regex เอง
              // (เดิม parse "ตกค้าง"/"บุคลากร" จาก label ซึ่งพังง่ายและไม่ตรงกับ backend เสมอไป — รีวิวรอบ 2)
              <Link key={y.group}
                to={`/admin/users?year_group=${y.group}`}
                className={`rounded-xl p-5 text-center hover:opacity-80 transition-opacity ${
                  y.group === 'retained' ? 'bg-amber-50 text-amber-800' : 'bg-slate-50 text-slate-700'
                }`}>
                <p className="text-3xl font-bold">{y.count}</p>
                <p className="text-sm mt-1">{y.label}</p>
              </Link>
            ))}
          </div>
        </>
      )}

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
