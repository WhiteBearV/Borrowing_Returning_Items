import { useEffect, useState } from 'react'
import { auditApi } from '../../api/auditApi.js'
import Pagination from '../../components/common/Pagination.jsx'
import EmptyState from '../../components/common/EmptyState.jsx'
import { ACTION_LABEL, actionLabel, detailLines, logDetailChips, logHeadline, logSentence } from '../../components/audit/auditLabels.js'
import { ALL_ROLES, roleBadgeClass, roleLabel } from '../../utils/role.js'

function DetailModal({ log, onClose }) {
  const rows = [
    ['ผู้ทำ', `${log.actor_name ?? '—'}${log.actor_identifier ? ` (${log.actor_identifier})` : ''}`],
    ['สิทธิ์ขณะทำ', log.actor_role ? roleLabel(log.actor_role) : '— (ก่อนระบบเริ่มเก็บ)'],
    ['การกระทำ', actionLabel(log.action)],
    ['เวลา', new Date(log.created_at).toLocaleString('th-TH')],
    ['ตาราง', log.target_table],
    ['Target ID', log.target_id],
  ]
  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50 px-4" onClick={onClose}>
      <div className="bg-white rounded-2xl p-6 w-full max-w-3xl max-h-[85vh] overflow-y-auto shadow-xl space-y-4"
        onClick={(e) => e.stopPropagation()}>
        <h2 className="font-bold text-gray-800">รายละเอียด Log</h2>
        <p className="text-sm font-medium text-gray-800 bg-gray-50 rounded-lg p-3">{logHeadline(log)}</p>
        <div className="grid sm:grid-cols-2 gap-x-6 gap-y-2 text-sm">
          {rows.map(([k, v]) => (
            <div key={k} className="flex gap-3">
              <span className="w-24 shrink-0 text-gray-400">{k}</span>
              <span className="font-mono text-xs break-all text-gray-700">{v}</span>
            </div>
          ))}
        </div>
        {log.detail && (
          <div>
            <p className="text-xs text-gray-400 mb-1">ข้อมูลเพิ่มเติม</p>
            <ul className="bg-gray-50 rounded-lg p-3 text-sm text-gray-700 divide-y divide-gray-200">
              {detailLines(log.detail).map((l) => (
                <li key={l.field} className="py-1.5 flex flex-wrap gap-x-2 gap-y-0.5">
                  <span className="text-gray-500 w-40 shrink-0">{l.label}</span>
                  <span className="flex-1 min-w-[12rem] break-words">
                    {l.from !== undefined
                      ? <>{l.from} → <span className="font-medium">{l.to}</span></>
                      : <span className="font-medium">{l.to}</span>}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
        <button onClick={onClose} className="w-full rounded-full border py-2 text-sm text-gray-600 hover:bg-gray-50">ปิด</button>
      </div>
    </div>
  )
}

const csvCell = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`
// ponytail: export ฝั่ง client จากข้อมูลที่ API ส่งอยู่แล้ว — ไม่ต้องมี endpoint ใหม่และไม่ต้อง
// ย้ายป้ายภาษาไทยทั้งชุดไปไว้ฝั่ง backend ให้ซ้ำสองที่ เพดานคือ 5,000 แถว (50 หน้า)
// ถ้าเกินให้ผู้ใช้แคบช่วงวันที่ลง — ถ้าวันหนึ่งต้องการมากกว่านี้จริงค่อยทำ endpoint CSV ที่ backend
const EXPORT_MAX_PAGES = 50
const EXPORT_PAGE_SIZE = 100

export default function AuditLogPage() {
  const [data, setData] = useState({ items: [], total: 0 })
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState(null)
  const [filterAction, setFilterAction] = useState('')
  const [filterRole, setFilterRole] = useState('')
  const [actor, setActor] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [exporting, setExporting] = useState(false)

  const params = {
    action: filterAction || undefined,
    actor_role: filterRole || undefined,
    actor: actor || undefined,
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
  }

  useEffect(() => {
    setLoading(true)
    auditApi.list({ page, page_size: 25, ...params }).then(setData).finally(() => setLoading(false))
  }, [page, filterAction, filterRole, actor, dateFrom, dateTo])

  const exportCsv = async () => {
    setExporting(true)
    try {
      const rows = []
      for (let p = 1; p <= EXPORT_MAX_PAGES; p++) {
        const chunk = await auditApi.list({ page: p, page_size: EXPORT_PAGE_SIZE, ...params })
        rows.push(...chunk.items)
        if (rows.length >= chunk.total) break
      }
      const header = ['เวลา', 'ผู้ทำ', 'รหัสประจำตัว', 'สิทธิ์ขณะทำ', 'การกระทำ', 'เหตุการณ์', 'ตาราง', 'Target ID']
      const body = rows.map((l) => [
        new Date(l.created_at).toLocaleString('th-TH'), l.actor_name, l.actor_identifier,
        l.actor_role ? roleLabel(l.actor_role) : '', actionLabel(l.action), logSentence(l),
        l.target_table, l.target_id,
      ])
      // ﻿ (BOM) — ไม่มีตัวนี้ Excel บน Windows เปิดไฟล์แล้วภาษาไทยเป็นตัวขยะ
      const csv = '﻿' + [header, ...body].map((r) => r.map(csvCell).join(',')).join('\n')
      const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
      const a = document.createElement('a')
      a.href = url
      a.download = `audit-log-${new Date().toISOString().slice(0, 10)}.csv`
      a.click()
      setTimeout(() => URL.revokeObjectURL(url), 10000)
    } finally {
      setExporting(false)
    }
  }

  const inputClass = 'rounded-lg border border-gray-300 px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500'

  return (
    <div className="px-6 py-8">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-4">
        <h1 className="text-2xl font-light text-gray-800">ประวัติการใช้งานระบบ</h1>
        <button onClick={exportCsv} disabled={exporting || data.total === 0}
          className="rounded-full border border-primary-300 px-4 py-1.5 text-sm font-medium text-primary-700 hover:bg-primary-50 disabled:opacity-50">
          {exporting ? 'กำลังสร้างไฟล์…' : 'ดาวน์โหลด CSV'}
        </button>
      </div>

      <div className="flex flex-wrap gap-2 mb-4">
        <input type="text" value={actor} placeholder="ค้นชื่อ/รหัสผู้ทำ…"
          onChange={(e) => { setActor(e.target.value); setPage(1) }}
          className={`${inputClass} w-full sm:w-52`} />
        <select value={filterRole} onChange={(e) => { setFilterRole(e.target.value); setPage(1) }} className={inputClass}>
          {/* ดึงรายการจาก utils/role.js — เดิมเขียนมือแล้วลืมใส่ "ผู้ดูแลระบบสูงสุด" กรองหาไม่เจอทั้งที่ log มี */}
          <option value="">ทุกสิทธิ์</option>
          {ALL_ROLES.map((r) => <option key={r} value={r}>{roleLabel(r)}</option>)}
        </select>
        <select value={filterAction} onChange={(e) => { setFilterAction(e.target.value); setPage(1) }} className={inputClass}>
          <option value="">ทุกการกระทำ</option>
          {Object.entries(ACTION_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <input type="date" value={dateFrom} onChange={(e) => { setDateFrom(e.target.value); setPage(1) }} className={inputClass} />
        <input type="date" value={dateTo} onChange={(e) => { setDateTo(e.target.value); setPage(1) }} className={inputClass} />
      </div>

      {loading ? (
        <EmptyState>กำลังโหลด…</EmptyState>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                {['เวลา', 'ผู้ทำ', 'เหตุการณ์', ''].map((h) => (
                  <th key={h} className="px-4 py-2.5 text-left text-xs font-semibold text-gray-500">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {data.items.map((log) => (
                <tr key={log.id} className="hover:bg-gray-50 cursor-pointer" onClick={() => setSelected(log)}>
                  <td className="px-4 py-2.5 text-xs text-gray-400 whitespace-nowrap align-top">
                    {new Date(log.created_at).toLocaleString('th-TH')}
                  </td>
                  <td className="px-4 py-2.5 text-xs text-gray-700 whitespace-nowrap align-top">
                    {log.actor_name ?? '—'}
                    {log.actor_role && (
                      <span className={`ml-1.5 px-1.5 py-0.5 rounded text-[10px] ${roleBadgeClass(log.actor_role)}`}>
                        {roleLabel(log.actor_role)}
                      </span>
                    )}
                  </td>
                  {/* ประโยคเดียวจบ — เดิมโชว์ชื่อตารางกับ UUID ดิบ ต้องกดเข้าไปดูถึงจะรู้ว่าเกิดอะไรขึ้น */}
                  <td className="px-4 py-2.5 text-xs text-gray-700">
                    <p className="font-medium text-gray-800">{logHeadline(log)}</p>
                    {logDetailChips(log).length > 0 && (
                      <ul className="mt-0.5 space-y-0.5 text-gray-500">
                        {logDetailChips(log).slice(0, 3).map((c, i) => <li key={i}>· {c}</li>)}
                        {logDetailChips(log).length > 3 && (
                          <li className="text-gray-400">· อีก {logDetailChips(log).length - 3} รายการ (กดดูรายละเอียด)</li>
                        )}
                      </ul>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-xs text-primary-600 whitespace-nowrap align-top">ดูรายละเอียด →</td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.items.length === 0 && <EmptyState className="py-10">ไม่พบรายการที่ตรงกับตัวกรอง</EmptyState>}
        </div>
      )}

      <Pagination page={page} total={data.total} pageSize={25} onChange={setPage} />

      {selected && <DetailModal log={selected} onClose={() => setSelected(null)} />}
    </div>
  )
}
