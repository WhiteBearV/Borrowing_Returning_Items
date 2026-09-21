import { useCallback, useEffect, useState } from 'react'
import { eligibleStudentsApi } from '../../api/eligibleStudentsApi.js'
import ConfirmModal from '../../components/common/ConfirmModal.jsx'
import EmptyState from '../../components/common/EmptyState.jsx'
import Pagination from '../../components/common/Pagination.jsx'
import { formatDate } from '../../utils/formatDate.js'

const MAJOR_LABEL = { comp_eng: 'วิศวกรรมคอมพิวเตอร์', digital_design: 'ออกแบบดิจิทัล' }

/** รายชื่อนักศึกษาที่สาขารับรอง — ใช้ตรวจตอนสมัครใช้งาน (เฟส 9)
 *  นำเข้าจากไฟล์ "รายชื่อนักศึกษาในที่ปรึกษา" ของสำนักทะเบียน ทีละไฟล์ (1 ไฟล์ = 1 อาจารย์ที่ปรึกษา)
 *  นำเข้าซ้ำได้เรื่อย ๆ — อัปเดตทับด้วยรหัสนักศึกษา ไม่ล้างของเดิมทิ้ง */
export default function EligibleStudentsPage() {
  const [data, setData] = useState({ items: [], total: 0, cohorts: {} })
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [cohort, setCohort] = useState('')  // รุ่น = 2 หลักแรกของรหัส ('' = ทุกรุ่น)
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [confirm, setConfirm] = useState(null)

  const load = useCallback(() => {
    setLoading(true)
    eligibleStudentsApi.list({ page, page_size: 20, search: search.trim() || undefined, cohort: cohort || undefined })
      .then(setData)
      .catch((e) => setError(e.response?.data?.detail ?? 'โหลดรายชื่อไม่สำเร็จ'))
      .finally(() => setLoading(false))
  }, [page, search, cohort])

  // หน่วงการค้นหาเล็กน้อย — พิมพ์ทีละตัวอักษรแล้วยิง API ทุกครั้งไม่คุ้ม
  useEffect(() => {
    const t = setTimeout(load, 300)
    return () => clearTimeout(t)
  }, [load])

  const upload = async (e) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    setUploading(true)
    setError('')
    setResult(null)
    try {
      setResult(await eligibleStudentsApi.import(file))
      load()
    } catch (err) {
      setError(err.response?.data?.detail ?? 'นำเข้าไฟล์ไม่สำเร็จ')
    } finally {
      setUploading(false)
    }
  }

  const remove = (row) => setConfirm({
    title: 'ถอนรายชื่อออกจากระบบ',
    message: `ถอน "${row.full_name}" (${row.student_id}) ออกจากรายชื่อที่รับรอง?\n`
      + 'บัญชีที่สมัครไปแล้วจะไม่ถูกลบ แต่คนนี้จะสมัครใหม่ไม่ผ่านการตรวจอัตโนมัติอีก',
    confirmLabel: 'ถอนรายชื่อ',
    danger: true,
    onConfirm: async () => {
      setConfirm(null)
      await eligibleStudentsApi.remove(row.id)
      load()
    },
  })

  const allCount = Object.values(data.cohorts ?? {}).reduce((a, b) => a + b, 0)

  return (
    <div className="px-6 py-8">
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
        <div>
          <h1 className="text-2xl font-light text-gray-800">รายชื่อนักศึกษาที่รับรอง</h1>
          <p className="text-xs text-gray-500 mt-1 max-w-2xl leading-relaxed">
            ใช้ตรวจตอนสมัครใช้งาน — <b>ชื่อและสาขาของผู้สมัครจะถูกยึดตามรายชื่อนี้ ไม่ใช่ตามที่กรอกเอง</b>
            {' '}· คนที่ไม่อยู่ในรายชื่อยังสมัครได้ แต่ต้องรอเจ้าหน้าที่อนุมัติที่หน้า "จัดการผู้ใช้"
          </p>
        </div>
        <label className={`shrink-0 rounded-full px-4 py-2 text-sm font-semibold text-white text-center
          ${uploading ? 'bg-gray-400' : 'bg-primary-600 hover:bg-primary-700 cursor-pointer'}`}>
          {uploading ? 'กำลังนำเข้า…' : '+ นำเข้าไฟล์รายชื่อ'}
          <input type="file" accept=".xls,.xlsx,.csv,.pdf" className="hidden" disabled={uploading}
            onChange={upload} />
        </label>
      </div>

      <p className="mt-2 text-xs text-gray-400">
        รองรับไฟล์ .xls (ไฟล์ที่ export จากสำนักทะเบียนโดยตรง) · .xlsx · .csv · .pdf —
        ระบบอ่านสาขา/รุ่น/อาจารย์ที่ปรึกษาจากหัวกระดาษให้อัตโนมัติ นำเข้าไฟล์ของอาจารย์หลายคนต่อกันได้
      </p>

      {error && <p className="mt-3 text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>}

      {result && (
        <div className="mt-3 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
          <p className="font-medium">
            นำเข้าสำเร็จ {result.total} รายชื่อ (เพิ่มใหม่ {result.added} · อัปเดต {result.updated})
          </p>
          <p className="text-xs mt-1 text-emerald-700">
            {[
              result.faculty && `คณะ ${result.faculty}`,
              result.major_raw && `สาขา ${result.major_raw}${result.major ? '' : ' (ระบบไม่รู้จักสาขานี้)'}`,
              result.generation,
              result.advisor && `อาจารย์ที่ปรึกษา ${result.advisor}`,
            ].filter(Boolean).join(' · ') || 'อ่านข้อมูลหัวกระดาษไม่ได้'}
          </p>
          {result.warnings?.map((w) => (
            <p key={w} className="text-xs mt-1 text-amber-700">⚠ {w}</p>
          ))}
        </div>
      )}

      <div className="flex items-center gap-3 my-4">
        <input value={search} onChange={(e) => { setSearch(e.target.value); setPage(1) }}
          placeholder="ค้นหารหัสนักศึกษา / ชื่อ / อาจารย์ที่ปรึกษา"
          className="rounded-lg border border-gray-300 px-3 py-2 text-sm w-72" />
        {/* กรองตามรุ่น — ตัวเลือกมาจากรหัสที่มีอยู่จริงในตาราง (backend นับให้) ไม่ hardcode ปี */}
        <select value={cohort} onChange={(e) => { setCohort(e.target.value); setPage(1) }}
          className="rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white">
          {/* ยังโหลดไม่เสร็จ = ไม่โชว์ตัวเลข (ไม่งั้นแวบขึ้น "0 คน" ก่อนข้อมูลมา) */}
          <option value="">ทุกรุ่น{allCount ? ` (${allCount} คน)` : ''}</option>
          {Object.entries(data.cohorts ?? {}).map(([c, n]) => (
            <option key={c} value={c}>รุ่น {c} ({n} คน)</option>
          ))}
        </select>
        <span className="text-xs text-gray-500">{data.total.toLocaleString('th-TH')} รายชื่อ</span>
      </div>

      {loading ? <EmptyState>กำลังโหลด…</EmptyState> : (
        <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                {['รหัสนักศึกษา', 'ชื่อ-นามสกุล', 'สาขา', 'รุ่น / หมู่เรียน', 'อาจารย์ที่ปรึกษา',
                  'สมัครแล้ว', 'นำเข้าเมื่อ', ''].map((h) => (
                  <th key={h} className="px-4 py-2.5 text-left text-xs font-semibold text-gray-500 whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {data.items.map((row) => (
                <tr key={row.id} className="hover:bg-gray-50">
                  <td className="px-4 py-2.5 font-mono text-xs text-gray-600">{row.student_id}</td>
                  <td className="px-4 py-2.5 text-gray-800">{row.full_name}</td>
                  <td className="px-4 py-2.5 text-xs text-gray-500">{MAJOR_LABEL[row.major] ?? '—'}</td>
                  <td className="px-4 py-2.5 text-xs text-gray-500">{row.generation ?? '—'}</td>
                  <td className="px-4 py-2.5 text-xs text-gray-500">{row.advisor ?? '—'}</td>
                  <td className="px-4 py-2.5">
                    {row.has_account
                      ? <span className="text-xs text-emerald-600">สมัครแล้ว</span>
                      : <span className="text-xs text-gray-400">ยังไม่สมัคร</span>}
                  </td>
                  <td className="px-4 py-2.5 text-xs text-gray-400 whitespace-nowrap">
                    {row.imported_at ? formatDate(row.imported_at) : '—'}
                  </td>
                  <td className="px-4 py-2.5">
                    <button onClick={() => remove(row)} className="text-xs text-red-500 hover:underline">ถอนออก</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.items.length === 0 && (
            <EmptyState className="py-10">
              ยังไม่มีรายชื่อในระบบ — กด "นำเข้าไฟล์รายชื่อ" เพื่อเริ่มต้น
            </EmptyState>
          )}
        </div>
      )}

      <Pagination page={page} total={data.total} pageSize={20} onChange={setPage} />

      {confirm && (
        <ConfirmModal {...confirm} onCancel={() => setConfirm(null)} />
      )}
    </div>
  )
}
