import { useEffect, useState } from 'react'
import { auditApi } from '../../api/auditApi.js'
import EmptyState from '../common/EmptyState.jsx'
import { actionLabel, detailLines } from './auditLabels.js'

const fmtWhen = (iso) => new Date(iso).toLocaleString('th-TH', {
  day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
})

/**
 * ไทม์ไลน์ประวัติของ target เดียว (อุปกรณ์ 1 ชิ้น) — ตอบคำถาม "ถูกย้าย/แก้อะไร เมื่อไร โดยใคร"
 * ข้อมูลมาจาก audit_logs ที่มีอยู่แล้ว แค่กรองด้วย target_id (ดู audit_service.list_logs)
 */
export default function AuditTimeline({ targetId, limit = 50 }) {
  const [logs, setLogs] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true
    auditApi.list({ target_id: targetId, page_size: limit })
      .then((d) => { if (alive) setLogs(d.items) })
      .catch(() => { if (alive) setError('โหลดประวัติไม่สำเร็จ') })
    return () => { alive = false }
  }, [targetId])

  if (error) return <p className="text-sm text-rose-600">{error}</p>
  if (logs === null) return <EmptyState>กำลังโหลดประวัติ…</EmptyState>
  if (!logs.length) return <EmptyState>ยังไม่มีประวัติการแก้ไขของชิ้นนี้</EmptyState>

  return (
    <ol className="space-y-3">
      {logs.map((log) => {
        const lines = detailLines(log.detail)
        return (
          <li key={log.id} className="relative pl-5 border-l-2 border-gray-200">
            <span className="absolute -left-[5px] top-1.5 w-2 h-2 rounded-full bg-primary-500" />
            <p className="text-sm font-medium text-gray-700">{actionLabel(log.action)}</p>
            {lines.length > 0 && (
              <ul className="mt-0.5 space-y-0.5">
                {lines.map((l) => (
                  <li key={l.field} className="text-xs text-gray-600">
                    {l.label}: {l.from !== undefined
                      ? <>{l.from} <span className="text-gray-400">→</span> <span className="font-medium">{l.to}</span></>
                      : <span className="font-medium">{l.to}</span>}
                  </li>
                ))}
              </ul>
            )}
            <p className="mt-0.5 text-xs text-gray-400">
              {fmtWhen(log.created_at)} · โดย {log.actor_name ?? 'ไม่ทราบ'}
              {log.actor_identifier ? ` (${log.actor_identifier})` : ''}
            </p>
          </li>
        )
      })}
    </ol>
  )
}
