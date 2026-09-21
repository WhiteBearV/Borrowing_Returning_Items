import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { dashboardApi } from '../../api/dashboardApi.js'
import { formatDate, todayTH } from '../../utils/formatDate.js'
import DateInput from '../../components/common/DateInput.jsx'
import EmptyState from '../../components/common/EmptyState.jsx'
import Pagination from '../../components/common/Pagination.jsx'

// low = เคยถูกยืมแต่ใช้น้อย แยกจาก idle = ไม่ถูกยืมเลย (เดิมปนกันเป็น "ไม่ถูกใช้" ทั้งคู่ อ่านแล้วงง)
const RATING = {
  good: { label: 'คุ้มค่า', cls: 'bg-emerald-100 text-emerald-700' },
  fair: { label: 'ปานกลาง', cls: 'bg-amber-100 text-amber-700' },
  low: { label: 'ใช้งานน้อย', cls: 'bg-orange-100 text-orange-700' },
  idle: { label: 'ไม่เคยถูกยืม', cls: 'bg-red-100 text-red-600' },
}

const TYPE_LABEL = { durable: 'ครุภัณฑ์', material: 'วัสดุใช้ซ้ำ', consumable: 'วัสดุสิ้นเปลือง' }
const TH_MONTHS = ['ม.ค.', 'ก.พ.', 'มี.ค.', 'เม.ย.', 'พ.ค.', 'มิ.ย.', 'ก.ค.', 'ส.ค.', 'ก.ย.', 'ต.ค.', 'พ.ย.', 'ธ.ค.']

// key = ฟิลด์ใน row · numeric = เรียงมาก→น้อยเป็นค่าเริ่มต้น (ตัวเลขที่คนอยากเห็น "เยอะสุด" ก่อน)
// period = เลือกช่วงเวลาอยู่ — ชื่อคอลัมน์ต้องบอกว่านับ "ในช่วงนี้" ไม่ใช่สะสม
const columns = (period) => [
  { key: 'code', label: 'รหัส' },
  { key: 'name', label: 'ชื่ออุปกรณ์' },
  { key: 'item_type', label: 'ประเภท' },
  { key: 'unit_value', label: 'ราคาที่ซื้อ', numeric: true },
  { key: 'acquired_at', label: 'ได้มาเมื่อ' },
  { key: 'borrow_count', label: period ? 'ยืมใหม่ในช่วงนี้ (ครั้ง)' : 'ถูกยืมสะสม (ครั้ง)', numeric: true },
  { key: 'days_borrowed', label: period ? 'ถูกยืมในช่วงนี้ (วัน)' : 'ถูกยืมสะสม (วัน)', numeric: true },
  { key: 'tracked_days', label: period ? 'อยู่ในระบบในช่วงนี้ (วัน)' : 'อยู่ในระบบ (วัน)', numeric: true },
  { key: 'utilization_rate', label: 'อัตราการใช้งาน', numeric: true },
  { key: 'daily_depreciation', label: 'ค่าเสื่อม/วัน', numeric: true },
  { key: 'cost_per_use_day', label: 'ต้นทุน/วันที่ใช้', numeric: true },
  { key: 'rating', label: 'ประเมิน' },
]

const PAGE_SIZE = 15   // เท่ากับหน้าจัดการอุปกรณ์

const money = (v) => (v == null ? '—' : v.toLocaleString('th-TH', { maximumFractionDigits: 2 }))

/** เดือน "YYYY-MM" → ช่วง {from, to} ของเดือนนั้น (ถึงวันนี้ถ้าเป็นเดือนปัจจุบัน) */
const monthRange = (month) => {
  const [y, m] = month.split('-').map(Number)
  const last = new Date(Date.UTC(y, m, 0)).toISOString().slice(0, 10)  // วันที่ 0 ของเดือนถัดไป = วันสุดท้าย
  return { from: `${month}-01`, to: last > todayTH() ? todayTH() : last }
}

/** หน้าสถิติความคุ้มค่าของอุปกรณ์ — ใช้ประกอบการตัดสินใจจัดซื้อ ไม่ใช่ฐานคิดค่าปรับ
 *  ทุกตัวเลขคำนวณสดจากประวัติการยืมจริง (borrow_items) · ช่วงเวลา/ประเภทอยู่ใน URL (?type=&from=&to=)
 *  การ์ด "มูลค่าที่ถูกยืมออก" ใน Dashboard ลิงก์มาพร้อมช่วงเดือนนี้/ปีนี้ได้ */
export default function UtilizationPage() {
  const [params, setParams] = useSearchParams()
  const type = params.get('type') ?? ''
  const from = params.get('from') ?? ''
  const to = params.get('to') ?? ''
  const period = !!(from && to)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const [rating, setRating] = useState('')
  const [sort, setSort] = useState({ key: 'days_borrowed', desc: true })
  const [customOpen, setCustomOpen] = useState(false)
  const [page, setPage] = useState(1)

  const setQuery = (patch) => {
    const next = Object.fromEntries([...params.entries()])
    Object.entries(patch).forEach(([k, v]) => { if (v) next[k] = v; else delete next[k] })
    setParams(next, { replace: true })
  }

  useEffect(() => {
    if ((from && !to) || (!from && to) || (period && from > to)) return  // กำลังกรอกช่วงเองยังไม่ครบ
    setLoading(true)
    dashboardApi.utilization(type, from, to)
      .then((d) => { setData(d); setError('') })
      .catch((e) => setError(e.response?.data?.detail ?? 'โหลดข้อมูลไม่สำเร็จ'))
      .finally(() => setLoading(false))
  }, [type, from, to])

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

  // แบ่งหน้าฝั่งเว็บ (ข้อมูลมาทั้งชุดอยู่แล้วเพื่อเรียง/กรองได้ทันที) — กรอง/เรียง/เปลี่ยนช่วงแล้วกลับหน้า 1
  useEffect(() => { setPage(1) }, [search, rating, sort, data])
  const pageRows = rows.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

  const toggleSort = (col) =>
    setSort((s) => (s.key === col.key ? { key: col.key, desc: !s.desc } : { key: col.key, desc: !!col.numeric }))

  if (!data && loading) return <EmptyState>กำลังคำนวณสถิติ…</EmptyState>
  if (!data) return <EmptyState>{error}</EmptyState>

  const today = todayTH()
  const presets = {
    month: { from: today.slice(0, 8) + '01', to: today },
    year: { from: today.slice(0, 5) + '01-01', to: today },
  }
  const preset = customOpen ? 'custom'
    : !period ? 'all'
      : Object.keys(presets).find((k) => presets[k].from === from && presets[k].to === to) ?? 'custom'
  const pickPreset = (v) => {
    setCustomOpen(v === 'custom')
    if (v === 'all') setQuery({ from: '', to: '' })
    else if (presets[v]) setQuery(presets[v])
    else if (!period) setQuery(presets.month)   // เลือกเองครั้งแรก เริ่มจากเดือนนี้ให้แก้ต่อ
  }
  const pickMonth = (month) => { setCustomOpen(false); setQuery(monthRange(month)) }
  const idleLabel = period ? 'ไม่ถูกยืมในช่วงนี้' : RATING.idle.label
  const ratingLabel = (r) => (r === 'idle' ? idleLabel : RATING[r].label)
  const scope = period ? 'ในช่วงนี้' : 'สะสม'
  const maxDays = Math.max(1, ...data.monthly.map((m) => m.days_borrowed))

  return (
    <div className="px-6 py-8">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-light text-gray-800">สถิติความคุ้มค่าของอุปกรณ์</h1>
          <p className="mt-1 text-sm font-medium text-primary-700">
            {period ? `ช่วง ${formatDate(from)} – ${formatDate(to)}` : 'สะสมตั้งแต่เข้าระบบ'}
            {loading && <span className="ml-2 text-xs font-normal text-gray-400">กำลังคำนวณ…</span>}
          </p>
        </div>
        {/* ช่วงเวลา — ค่าอยู่ใน URL จึงกดย้อนกลับ/แชร์ลิงก์/ลิงก์จาก Dashboard ได้ */}
        <div className="flex flex-wrap items-center gap-2">
          <select value={preset} onChange={(e) => pickPreset(e.target.value)}
            className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm">
            <option value="all">ทั้งหมด (สะสม)</option>
            <option value="month">เดือนนี้</option>
            <option value="year">ปีนี้</option>
            <option value="custom">เลือกช่วงเอง…</option>
          </select>
          {preset === 'custom' && <>
            <DateInput type="date" value={from} max={to || today} onChange={(e) => setQuery({ from: e.target.value })}
              className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm" />
            <span className="text-xs text-gray-400">ถึง</span>
            <DateInput type="date" value={to} min={from} max={today} onChange={(e) => setQuery({ to: e.target.value })}
              className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm" />
          </>}
        </div>
      </div>
      {error && <p className="mt-3 text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>}

      {/* วิธีคำนวณ — แยกทีละตัวชี้วัดว่าใช้บอกอะไร ตัวเลขฐาน (อายุ/ซาก/เกณฑ์) มาจาก backend ไม่ hardcode */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 mt-5">
        {[
          { title: 'อัตราการใช้งาน', formula: `วันที่ถูกยืม${scope} ÷ วันที่อยู่ในระบบ${period ? 'ในช่วงนี้' : ''}`,
            use: 'ออกไปใช้งานกี่ % ของเวลาที่อยู่ในระบบ (นับจากวันที่นำเข้าระบบ หรือวันที่ได้มาถ้าช้ากว่า) — ใช้ตัดสินป้ายประเมิน' },
          { title: 'ค่าเสื่อม/วัน', formula: `(ราคาที่ซื้อ − ซาก ${money(data.salvage_value)} บ.) ÷ อายุการใช้งาน`,
            use: `ต้นทุนจริงต่อวันถ้าถูกใช้ทุกวัน (ตัวเทียบ) · อายุไม่ได้กรอก = ${data.depreciation_years_default} ปีตาม Settings · เส้นตรงตามหลักกรมบัญชีกลาง` },
          { title: 'ต้นทุน/วันที่ใช้', formula: `ค่าเสื่อมช่วงที่อยู่ในระบบ${period ? 'ในช่วงนี้' : ''} ÷ วันที่ถูกยืม${scope}`,
            use: 'ต้นทุนที่แท้จริงของการยืม 1 วัน รวมวันที่จอดเฉย ๆ ด้วย — ยิ่งห่างจากค่าเสื่อม/วันมาก ยิ่งไม่คุ้ม' },
          { title: 'ป้ายประเมิน', formula: `คุ้มค่า ≥ ${Math.round(data.good_threshold * 100)}% · ปานกลาง ≥ ${Math.round(data.fair_threshold * 100)}%`,
            use: `ใช้งานน้อย = ถูกยืมแต่ต่ำกว่า ${Math.round(data.fair_threshold * 100)}% · ${idleLabel} = ไม่มีใครยืมเลย${period ? 'ในช่วงนี้' : ''}` },
        ].map((m) => (
          <div key={m.title} className="bg-white rounded-xl border border-gray-200 px-4 py-3">
            <p className="text-sm font-semibold text-gray-800">{m.title}</p>
            <p className="mt-1 rounded-md bg-primary-50 px-2 py-1 text-xs font-medium text-primary-800">{m.formula}</p>
            <p className="mt-1.5 text-xs leading-relaxed text-gray-500">{m.use}</p>
          </div>
        ))}
      </div>

      <div className="grid gap-3 sm:grid-cols-3 my-6">
        <div className="bg-white rounded-xl border border-gray-200 px-4 py-3">
          <p className="text-xs text-gray-500">{period ? 'ไม่ถูกยืมเลยในช่วงนี้' : 'ซื้อมาแล้วไม่เคยถูกยืมเลย'}</p>
          <p className="text-2xl font-light text-gray-800">{data.never_borrowed_count.toLocaleString('th-TH')} รายการ</p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 px-4 py-3">
          <p className="text-xs text-gray-500">{period ? 'มูลค่ารวมของที่ไม่ถูกยืมในช่วงนี้' : 'มูลค่ารวมของที่ไม่เคยถูกยืม'}</p>
          <p className="text-2xl font-light text-red-600">{money(data.never_borrowed_value)} บาท</p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 px-4 py-3">
          <p className="text-xs text-gray-500">วันที่อุปกรณ์ออกจากคลังรวม ({scope})</p>
          <p className="text-2xl font-light text-gray-800">{data.total_days_borrowed.toLocaleString('th-TH')} วัน</p>
        </div>
      </div>

      {/* ภาพรวมรายเดือน — ตอบ "เดือนไหนใช้ของเยอะ/น้อย" แสดงทุกเดือนเสมอ (ไม่ขึ้นกับช่วงที่เลือก) แล้วไฮไลต์
          เดือนที่เลือกอยู่ · แท่ง = วันที่ของออกจากคลัง (ชุดข้อมูลเดียว สีเดียว ตัวเลขอยู่ข้างแท่งเสมอ) */}
      {data.monthly.length > 0 && (
        <section className="mb-6">
          <h2 className="mb-2 text-sm font-semibold text-gray-600">
            ภาพรวมรายเดือน
            <span className="ml-2 font-normal text-xs text-gray-400">กดเดือนเพื่อดูเฉพาะเดือนนั้น</span>
          </h2>
          <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-gray-600">
                <tr>
                  <th className="px-3 py-2 text-left font-medium whitespace-nowrap">เดือน</th>
                  <th className="px-3 py-2 text-right font-medium whitespace-nowrap">ยืมใหม่ (ครั้ง)</th>
                  <th className="px-3 py-2 text-left font-medium whitespace-nowrap w-1/2">วันที่อุปกรณ์ออกจากคลังรวม</th>
                  <th className="px-3 py-2 text-right font-medium whitespace-nowrap">มูลค่าที่ถูกยืมออก (บาท)</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {data.monthly.map((m) => {
                  const [y, mo] = m.month.split('-')
                  const label = `${TH_MONTHS[Number(mo) - 1]} ${y}`
                  const r = monthRange(m.month)
                  const selected = period && from === r.from && to === r.to
                  return (
                    <tr key={m.month} onClick={() => pickMonth(m.month)}
                      title={`${label}: ยืมใหม่ ${m.new_borrows} ครั้ง · ออกจากคลังรวม ${m.days_borrowed} วัน · มูลค่า ${money(m.borrowed_value)} บาท`}
                      className={`cursor-pointer ${selected ? 'bg-primary-50' : 'hover:bg-gray-50'}`}>
                      <td className={`px-3 py-2 whitespace-nowrap ${selected ? 'font-semibold text-primary-700' : 'text-gray-800'}`}>{label}</td>
                      <td className="px-3 py-2 text-right text-gray-700">{m.new_borrows.toLocaleString('th-TH')}</td>
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-2">
                          <div className="flex-1">
                            {m.days_borrowed > 0 && (
                              <div className="h-2 rounded-r bg-primary-500"
                                style={{ width: `${Math.max((m.days_borrowed / maxDays) * 100, 1)}%` }} />
                            )}
                          </div>
                          <span className="w-16 shrink-0 text-right text-xs text-gray-600">{m.days_borrowed.toLocaleString('th-TH')} วัน</span>
                        </div>
                      </td>
                      <td className="px-3 py-2 text-right text-gray-700">{money(m.borrowed_value)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <div className="flex flex-wrap gap-2 mb-3">
        <input
          value={search} onChange={(e) => setSearch(e.target.value)}
          placeholder="ค้นหารหัส / ชื่ออุปกรณ์"
          className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm w-56"
        />
        <select value={type} onChange={(e) => setQuery({ type: e.target.value })}
          className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm">
          <option value="">ครุภัณฑ์ + วัสดุใช้ซ้ำ</option>
          <option value="all">ทุกประเภท</option>
          <option value="durable">ครุภัณฑ์</option>
          <option value="material">วัสดุใช้ซ้ำ</option>
          <option value="consumable">วัสดุสิ้นเปลือง</option>
        </select>
        <select value={rating} onChange={(e) => setRating(e.target.value)}
          className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm">
          <option value="">ทุกระดับ</option>
          <option value="good">คุ้มค่า</option>
          <option value="fair">ปานกลาง</option>
          <option value="low">ใช้งานน้อย</option>
          <option value="idle">{idleLabel}</option>
        </select>
        <span className="self-center text-xs text-gray-500">{rows.length.toLocaleString('th-TH')} รายการ</span>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-gray-600">
            <tr>
              {columns(period).map((c) => (
                <th key={c.key} onClick={() => toggleSort(c)}
                  className={`px-3 py-2 font-medium cursor-pointer select-none whitespace-nowrap
                    ${c.numeric ? 'text-right' : 'text-left'} hover:text-primary-700`}>
                  {c.label}{sort.key === c.key ? (sort.desc ? ' ▼' : ' ▲') : ''}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {pageRows.map((r) => (
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
                <td className="px-3 py-2 text-right text-gray-500">{r.tracked_days.toLocaleString('th-TH')}</td>
                <td className="px-3 py-2 text-right">
                  {r.utilization_rate == null ? '—' : `${(r.utilization_rate * 100).toFixed(1)}%`}
                </td>
                <td className="px-3 py-2 text-right text-gray-500">{r.daily_depreciation == null ? '—' : `${money(r.daily_depreciation)} บ.`}</td>
                <td className="px-3 py-2 text-right">{r.cost_per_use_day == null ? '—' : `${money(r.cost_per_use_day)} บ.`}</td>
                <td className="px-3 py-2">
                  <span className={`whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${RATING[r.rating].cls}`}>
                    {ratingLabel(r.rating)}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 && <p className="px-4 py-8 text-center text-sm text-gray-400">ไม่พบรายการที่ตรงเงื่อนไข</p>}
      </div>
      <Pagination page={page} total={rows.length} pageSize={PAGE_SIZE} onChange={setPage} />

    </div>
  )
}
