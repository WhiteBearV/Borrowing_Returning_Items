import { useCallback, useEffect, useMemo, useState } from 'react'
import { borrowApi } from '../../api/borrowApi.js'
import { dashboardApi } from '../../api/dashboardApi.js'
import { useAuthContext } from '../../context/AuthContext.jsx'
import { formatDate } from '../../utils/formatDate.js'
import { FINE_STATUS, fineMoney } from '../../utils/fine.js'
import { isSuperadmin } from '../../utils/role.js'
import EmptyState from '../../components/common/EmptyState.jsx'
import { CONDITION_LABEL } from '../../components/borrow/ReturnModal.jsx'

const COLUMNS = [
  { key: 'request_code', label: 'เลขคำขอ' },
  { key: 'student_name', label: 'ผู้ยืม' },
  { key: 'equipment_name', label: 'อุปกรณ์' },
  { key: 'due_date', label: 'กำหนดคืน' },
  { key: 'returned_at', label: 'คืนเมื่อ' },
  { key: 'days_late', label: 'ล่าช้า (วัน)', numeric: true },
  { key: 'late_amount', label: 'ค่าปรับล่าช้า', numeric: true },
  { key: 'damage_amount', label: 'ค่าเสียหาย', numeric: true },
  { key: 'total', label: 'รวม', numeric: true },
  { key: 'status', label: 'สถานะ' },
  { key: '_action', label: '' },
]

/** หน้าสรุปค่าปรับ — ยอดทั้งหมดถูก freeze ไว้ตั้งแต่วันรับคืน ไม่คำนวณใหม่ตอนเปิดหน้านี้
 *  แก้อัตราใน "การตั้งค่า" จึงมีผลกับการรับคืนครั้งถัดไปเท่านั้น ยอดเก่าไม่ขยับ */
export default function FinesPage() {
  const { user } = useAuthContext()
  const canWaive = isSuperadmin(user)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [statusFilter, setStatusFilter] = useState('unpaid')
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState({ key: 'returned_at', desc: true })
  const [dialog, setDialog] = useState(null)   // { mode: 'edit' | 'waive', row }

  const load = useCallback(() => {
    setLoading(true)
    dashboardApi.fines()
      .then((d) => { setData(d); setError('') })
      .catch((e) => setError(e.response?.data?.detail ?? 'โหลดข้อมูลไม่สำเร็จ'))
      .finally(() => setLoading(false))
  }, [])
  useEffect(load, [load])

  const rows = useMemo(() => {
    if (!data) return []
    const q = search.trim().toLowerCase()
    const filtered = data.rows.filter((r) =>
      (!statusFilter || r.status === statusFilter) &&
      (!q || [r.request_code, r.student_name, r.student_identifier, r.equipment_name]
        .some((v) => v?.toLowerCase().includes(q))))
    return [...filtered].sort((a, b) => {
      const x = a[sort.key], y = b[sort.key]
      if (x == null && y == null) return 0
      if (x == null) return 1
      if (y == null) return -1
      const cmp = typeof x === 'number' ? x - y : String(x).localeCompare(String(y), 'th')
      return sort.desc ? -cmp : cmp
    })
  }, [data, statusFilter, search, sort])

  const toggleSort = (col) =>
    setSort((s) => (s.key === col.key ? { key: col.key, desc: !s.desc } : { key: col.key, desc: !!col.numeric }))

  const markPaid = async (row) => {
    try {
      await borrowApi.payFine(row.request_id, row.item_id)
      load()
    } catch (e) {
      setError(e.response?.data?.detail ?? 'บันทึกไม่สำเร็จ')
    }
  }

  const exportCsv = async () => {
    const blob = await dashboardApi.finesCsv()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `ค่าปรับ-${new Date().toISOString().slice(0, 10)}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  if (loading) return <EmptyState>กำลังโหลดข้อมูลค่าปรับ…</EmptyState>
  if (error && !data) return <EmptyState>{error}</EmptyState>

  return (
    <div className="px-6 py-8">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-light text-gray-800">ค่าปรับ</h1>
          <p className="text-xs text-gray-500 mt-1">
            ค่าปรับล่าช้าคิดจากอัตราต่อวันใน "การตั้งค่า" · ค่าเสียหายคิดจากมูลค่าตามบัญชี (ราคาทุนหักค่าเสื่อม)
            · <b>ยอดถูกบันทึกไว้ตั้งแต่วันรับคืน แก้อัตราทีหลังยอดเก่าจะไม่เปลี่ยน</b>
          </p>
        </div>
        <button onClick={exportCsv}
          className="rounded-full border border-gray-300 px-4 py-1.5 text-sm text-gray-600 hover:bg-gray-50">
          ดาวน์โหลด CSV
        </button>
      </div>

      <div className="grid gap-3 sm:grid-cols-3 my-6">
        <div className="bg-white rounded-xl border border-gray-200 px-4 py-3">
          <p className="text-xs text-gray-500">ค้างชำระ ({data.unpaid_count} รายการ)</p>
          <p className="text-2xl font-light text-red-600">{fineMoney(data.unpaid_total)} บาท</p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 px-4 py-3">
          <p className="text-xs text-gray-500">ชำระแล้ว ({data.paid_count} รายการ)</p>
          <p className="text-2xl font-light text-emerald-600">{fineMoney(data.paid_total)} บาท</p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 px-4 py-3">
          <p className="text-xs text-gray-500">ยกเว้น ({data.waived_count} รายการ)</p>
          <p className="text-2xl font-light text-amber-600">{fineMoney(data.waived_total)} บาท</p>
        </div>
      </div>

      <div className="flex flex-wrap gap-2 mb-3">
        <input value={search} onChange={(e) => setSearch(e.target.value)}
          placeholder="ค้นหาเลขคำขอ / ชื่อผู้ยืม / อุปกรณ์"
          className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm w-64" />
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}
          className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm">
          <option value="">ทุกสถานะ</option>
          <option value="unpaid">ค้างชำระ</option>
          <option value="paid">ชำระแล้ว</option>
          <option value="waived">ยกเว้น</option>
        </select>
        <span className="self-center text-xs text-gray-500">{rows.length.toLocaleString('th-TH')} รายการ</span>
      </div>

      {error && <p className="mb-3 text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>}

      <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-gray-600">
            <tr>
              {COLUMNS.map((c) => (
                <th key={c.key} onClick={() => c.key !== '_action' && toggleSort(c)}
                  className={`px-3 py-2 font-medium select-none whitespace-nowrap
                    ${c.key === '_action' ? '' : 'cursor-pointer hover:text-primary-700'}
                    ${c.numeric ? 'text-right' : 'text-left'}`}>
                  {c.label}{sort.key === c.key ? (sort.desc ? ' ▼' : ' ▲') : ''}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {rows.map((r) => (
              <tr key={r.item_id} className="hover:bg-gray-50 align-top">
                <td className="px-3 py-2 font-mono text-xs text-gray-500">{r.request_code}</td>
                <td className="px-3 py-2 text-gray-800">
                  {r.student_name}
                  <span className="block text-xs text-gray-400">{r.student_identifier}</span>
                </td>
                <td className="px-3 py-2 text-gray-800">
                  {r.equipment_name}
                  <span className="block text-xs text-gray-400">
                    {r.equipment_code}
                    {r.condition_on_return && ` · ${CONDITION_LABEL[r.condition_on_return] ?? r.condition_on_return}`}
                  </span>
                </td>
                <td className="px-3 py-2 text-xs text-gray-500 whitespace-nowrap">
                  {r.due_date ? formatDate(r.due_date) : '—'}
                </td>
                <td className="px-3 py-2 text-xs text-gray-500 whitespace-nowrap">
                  {r.returned_at ? formatDate(r.returned_at) : '—'}
                </td>
                <td className="px-3 py-2 text-right">{r.days_late}</td>
                <td className="px-3 py-2 text-right">{fineMoney(r.late_amount)}</td>
                <td className="px-3 py-2 text-right">{fineMoney(r.damage_amount)}</td>
                <td className="px-3 py-2 text-right font-medium text-gray-800">{fineMoney(r.total)}</td>
                <td className="px-3 py-2">
                  <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${FINE_STATUS[r.status]?.cls}`}>
                    {FINE_STATUS[r.status]?.label ?? r.status}
                  </span>
                  {r.status === 'waived' && (
                    <span className="block text-xs text-gray-400 mt-0.5">
                      โดย {r.waived_by_name} · {r.waived_reason}
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 whitespace-nowrap">
                  {r.status === 'unpaid' && (
                    <div className="flex gap-2 text-xs">
                      <button onClick={() => markPaid(r)} className="text-emerald-600 hover:underline">รับชำระ</button>
                      <button onClick={() => setDialog({ mode: 'edit', row: r })}
                        className="text-gray-500 hover:underline">แก้ยอด</button>
                      {canWaive && (
                        <button onClick={() => setDialog({ mode: 'waive', row: r })}
                          className="text-amber-600 hover:underline">ยกเว้น</button>
                      )}
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 && <p className="px-4 py-8 text-center text-sm text-gray-400">ไม่พบรายการที่ตรงเงื่อนไข</p>}
      </div>

      {dialog && (
        <FineDialog {...dialog} onClose={() => setDialog(null)} onDone={() => { setDialog(null); load() }} />
      )}
    </div>
  )
}

/** โมดัลแก้ยอด / ยกเว้น — ทั้งสองอย่างบังคับกรอกเหตุผลเพราะเป็นการแตะตัวเลขที่เรียกเงิน */
function FineDialog({ mode, row, onClose, onDone }) {
  const isWaive = mode === 'waive'
  const [late, setLate] = useState(String(row.late_amount))
  const [damage, setDamage] = useState(String(row.damage_amount))
  const [reason, setReason] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const submit = async () => {
    if (!reason.trim()) return setError('กรุณากรอกเหตุผล')
    setLoading(true)
    setError('')
    try {
      if (isWaive) await borrowApi.waiveFine(row.request_id, row.item_id, reason.trim())
      else await borrowApi.updateFine(row.request_id, row.item_id, {
        late_amount: Number(late) || 0, damage_amount: Number(damage) || 0, reason: reason.trim(),
      })
      onDone()
    } catch (e) {
      setError(e.response?.data?.detail ?? 'บันทึกไม่สำเร็จ')
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50 px-4">
      <div className="bg-white rounded-2xl p-6 w-full max-w-sm shadow-xl space-y-4">
        <h2 className="font-bold text-gray-800">{isWaive ? 'ยกเว้นค่าปรับ' : 'แก้ยอดค่าปรับ'}</h2>
        <p className="text-sm text-gray-500">
          {row.request_code} · {row.equipment_name}
          <span className="block text-xs text-gray-400">
            ยอดปัจจุบัน {fineMoney(row.total)} บาท
            {row.basis?.rate_per_day != null &&
              ` (ล่าช้า ${row.days_late} วัน × ${fineMoney(row.basis.rate_per_day)} บาท)`}
          </span>
        </p>
        {!isWaive && (
          <div className="grid grid-cols-2 gap-2">
            <label className="text-xs text-gray-600">
              ค่าปรับล่าช้า
              <input type="number" min="0" step="0.01" value={late} onChange={(e) => setLate(e.target.value)}
                className="mt-1 w-full rounded-lg border border-gray-300 px-2 py-1.5 text-sm" />
            </label>
            <label className="text-xs text-gray-600">
              ค่าเสียหาย
              <input type="number" min="0" step="0.01" value={damage} onChange={(e) => setDamage(e.target.value)}
                className="mt-1 w-full rounded-lg border border-gray-300 px-2 py-1.5 text-sm" />
            </label>
          </div>
        )}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            เหตุผล <span className="text-red-500">*</span>
          </label>
          <textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)}
            placeholder={isWaive ? 'เช่น อาจารย์อนุมัติให้ยกเว้น (เหตุสุดวิสัย)' : 'เช่น เจรจาลดหย่อน ของเสียหายบางส่วน'}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm resize-none" />
        </div>
        {error && <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>}
        <div className="flex gap-3">
          <button onClick={onClose} className="flex-1 rounded-full border py-2 text-sm text-gray-600 hover:bg-gray-50">
            ยกเลิก
          </button>
          <button onClick={submit} disabled={loading}
            className={`flex-1 rounded-full py-2 text-sm font-semibold text-white disabled:opacity-50
              ${isWaive ? 'bg-amber-600 hover:bg-amber-700' : 'bg-primary-600 hover:bg-primary-700'}`}>
            {loading ? 'กำลังบันทึก…' : 'ยืนยัน'}
          </button>
        </div>
      </div>
    </div>
  )
}
