import { useEffect, useMemo, useState } from 'react'
import { dashboardApi } from '../../api/dashboardApi.js'
import { formatDate } from '../../utils/formatDate.js'
import EmptyState from '../../components/common/EmptyState.jsx'

const RATING = {
  good: { label: 'คุ้มค่า', cls: 'bg-emerald-100 text-emerald-700' },
  fair: { label: 'ปานกลาง', cls: 'bg-amber-100 text-amber-700' },
  idle: { label: 'ไม่ถูกใช้', cls: 'bg-red-100 text-red-600' },
}

const TYPE_LABEL = { durable: 'ครุภัณฑ์', material: 'วัสดุใช้ซ้ำ', consumable: 'วัสดุสิ้นเปลือง' }

// key = ฟิลด์ใน row · numeric = เรียงมาก→น้อยเป็นค่าเริ่มต้น (ตัวเลขที่คนอยากเห็น "เยอะสุด" ก่อน)
const COLUMNS = [
  { key: 'code', label: 'รหัส' },
  { key: 'name', label: 'ชื่ออุปกรณ์' },
  { key: 'item_type', label: 'ประเภท' },
  { key: 'unit_value', label: 'ราคาที่ซื้อ', numeric: true },
  { key: 'acquired_at', label: 'ได้มาเมื่อ' },
  { key: 'borrow_count', label: 'ถูกยืม (ครั้ง)', numeric: true },
  { key: 'days_borrowed', label: 'รวม (วัน)', numeric: true },
  { key: 'utilization_rate', label: 'อัตราการใช้งาน', numeric: true },
  { key: 'cost_per_day', label: 'ต้นทุน/วันใช้งาน', numeric: true },
  { key: 'rating', label: 'ประเมิน' },
]

const money = (v) => (v == null ? '—' : v.toLocaleString('th-TH', { maximumFractionDigits: 2 }))

/** หน้าสถิติความคุ้มค่าของอุปกรณ์ — ใช้ประกอบการตัดสินใจจัดซื้อ ไม่ใช่ฐานคิดค่าปรับ
 *  ทุกตัวเลขคำนวณสดจากประวัติการยืมจริง (borrow_items) ไม่มีการเก็บค่าไว้ล่วงหน้า */
export default function UtilizationPage() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [type, setType] = useState('')
  const [search, setSearch] = useState('')
  const [rating, setRating] = useState('')
  const [sort, setSort] = useState({ key: 'days_borrowed', desc: true })

  useEffect(() => {
    setLoading(true)
    dashboardApi.utilization(type)
      .then((d) => { setData(d); setError('') })
      .catch((e) => setError(e.response?.data?.detail ?? 'โหลดข้อมูลไม่สำเร็จ'))
      .finally(() => setLoading(false))
  }, [type])

  const rows = useMemo(() => {
    if (!data) return []
    const q = search.trim().toLowerCase()
    const filtered = data.rows.filter((r) =>
      (!rating || r.rating === rating) &&
      (!q || r.code.toLowerCase().includes(q) || r.name.toLowerCase().includes(q)))
    // null ไปท้ายแถวเสมอไม่ว่าเรียงขึ้นหรือลง — ของที่ยังไม่กรอกราคา/วันที่ไม่ควรแย่งหัวตาราง
    return [...filtered].sort((a, b) => {
      const x = a[sort.key], y = b[sort.key]
      if (x == null && y == null) return 0
      if (x == null) return 1
      if (y == null) return -1
      const cmp = typeof x === 'number' ? x - y : String(x).localeCompare(String(y), 'th')
      return sort.desc ? -cmp : cmp
    })
  }, [data, search, rating, sort])

  const toggleSort = (col) =>
    setSort((s) => (s.key === col.key ? { key: col.key, desc: !s.desc } : { key: col.key, desc: !!col.numeric }))

  if (loading) return <EmptyState>กำลังคำนวณสถิติ…</EmptyState>
  if (error) return <EmptyState>{error}</EmptyState>

  return (
    <div className="px-6 py-8">
      <h1 className="text-2xl font-light text-gray-800">สถิติความคุ้มค่าของอุปกรณ์</h1>
      <p className="text-xs text-gray-500 mt-1">
        คำนวณสดจากประวัติการยืมจริง · <b>ใช้ประกอบการตัดสินใจจัดซื้อเท่านั้น ไม่ใช่ฐานคิดค่าปรับ</b>
        (ค่าปรับ/ค่าเสียหายคิดจากมูลค่าตามบัญชี)
      </p>

      <div className="grid gap-3 sm:grid-cols-3 my-6">
        <div className="bg-white rounded-xl border border-gray-200 px-4 py-3">
          <p className="text-xs text-gray-500">ซื้อมาแล้วไม่เคยถูกยืมเลย</p>
          <p className="text-2xl font-light text-gray-800">{data.never_borrowed_count.toLocaleString('th-TH')} รายการ</p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 px-4 py-3">
          <p className="text-xs text-gray-500">มูลค่ารวมของที่ไม่เคยถูกยืม</p>
          <p className="text-2xl font-light text-red-600">{money(data.never_borrowed_value)} บาท</p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 px-4 py-3">
          <p className="text-xs text-gray-500">วันที่อุปกรณ์ออกจากคลังรวม</p>
          <p className="text-2xl font-light text-gray-800">{data.total_days_borrowed.toLocaleString('th-TH')} วัน</p>
        </div>
      </div>

      <div className="flex flex-wrap gap-2 mb-3">
        <input
          value={search} onChange={(e) => setSearch(e.target.value)}
          placeholder="ค้นหารหัส / ชื่ออุปกรณ์"
          className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm w-56"
        />
        <select value={type} onChange={(e) => setType(e.target.value)}
          className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm">
          <option value="">ครุภัณฑ์ + วัสดุใช้ซ้ำ</option>
          <option value="durable">ครุภัณฑ์</option>
          <option value="material">วัสดุใช้ซ้ำ</option>
          <option value="consumable">วัสดุสิ้นเปลือง</option>
        </select>
        <select value={rating} onChange={(e) => setRating(e.target.value)}
          className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm">
          <option value="">ทุกระดับ</option>
          <option value="good">คุ้มค่า</option>
          <option value="fair">ปานกลาง</option>
          <option value="idle">ไม่ถูกใช้</option>
        </select>
        <span className="self-center text-xs text-gray-500">{rows.length.toLocaleString('th-TH')} รายการ</span>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-gray-600">
            <tr>
              {COLUMNS.map((c) => (
                <th key={c.key} onClick={() => toggleSort(c)}
                  className={`px-3 py-2 font-medium cursor-pointer select-none whitespace-nowrap
                    ${c.numeric ? 'text-right' : 'text-left'} hover:text-primary-700`}>
                  {c.label}{sort.key === c.key ? (sort.desc ? ' ▼' : ' ▲') : ''}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {rows.map((r) => (
              <tr key={r.equipment_id} className="hover:bg-gray-50">
                <td className="px-3 py-2 font-mono text-xs text-gray-500">{r.code}</td>
                <td className="px-3 py-2 text-gray-800">{r.name}</td>
                <td className="px-3 py-2 text-gray-500 text-xs">{TYPE_LABEL[r.item_type] ?? r.item_type}</td>
                <td className="px-3 py-2 text-right">{money(r.unit_value)}</td>
                <td className="px-3 py-2 text-gray-500 text-xs whitespace-nowrap">
                  {r.acquired_at ? formatDate(r.acquired_at) : '—'}
                </td>
                <td className="px-3 py-2 text-right">{r.borrow_count.toLocaleString('th-TH')}</td>
                <td className="px-3 py-2 text-right">{r.days_borrowed.toLocaleString('th-TH')}</td>
                <td className="px-3 py-2 text-right">
                  {r.utilization_rate == null ? '—' : `${(r.utilization_rate * 100).toFixed(1)}%`}
                </td>
                <td className="px-3 py-2 text-right">{r.cost_per_day == null ? '—' : `${money(r.cost_per_day)} บ.`}</td>
                <td className="px-3 py-2">
                  <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${RATING[r.rating].cls}`}>
                    {RATING[r.rating].label}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 && <p className="px-4 py-8 text-center text-sm text-gray-400">ไม่พบรายการที่ตรงเงื่อนไข</p>}
      </div>

      <p className="text-xs text-gray-400 mt-3">
        อัตราการใช้งาน = วันที่ถูกยืม ÷ วันที่ครอบครองตั้งแต่วันที่ได้มา (ของที่ยังไม่กรอกวันที่ได้มาจะคิดไม่ได้ แสดง "—")
        · ต้นทุน/วันใช้งาน = ราคาที่ซื้อ ÷ วันที่ถูกยืมรวม
      </p>
    </div>
  )
}
