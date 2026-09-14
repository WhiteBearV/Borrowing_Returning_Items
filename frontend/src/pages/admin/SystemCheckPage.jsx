import { useEffect, useState } from 'react'
import { changeRequestApi } from '../../api/changeRequestApi.js'
import EmptyState from '../../components/common/EmptyState.jsx'

/** หน้าตรวจสุขภาพข้อมูลสำหรับผู้ดูแลระบบสูงสุด — อ่านอย่างเดียว
 *  ทุกตัวเลขมาจาก query ที่เขียนไว้ล่วงหน้าใน backend (system_check_service) ไม่มีช่องพิมพ์ SQL
 *  โดยตั้งใจ: ช่องรัน SQL ในเว็บทำให้ลบ audit log ของตัวเองได้ ซึ่งขัดกับข้อกำหนดเรื่องประวัติที่ลบไม่ได้ */
export default function SystemCheckPage() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = () => {
    setLoading(true)
    changeRequestApi.systemCheck()
      .then(setData)
      .catch((err) => setError(err.response?.data?.detail ?? 'โหลดข้อมูลไม่สำเร็จ'))
      .finally(() => setLoading(false))
  }
  useEffect(load, [])

  if (loading) return <EmptyState>กำลังตรวจ…</EmptyState>
  if (error) return <EmptyState>{error}</EmptyState>

  return (
    <div className="px-6 py-8">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-6">
        <div>
          <h1 className="text-2xl font-light text-gray-800">ตรวจสอบระบบ</h1>
          <p className="text-xs text-gray-500 mt-1">
            ตรวจล่าสุด {new Date(data.checked_at).toLocaleString('th-TH')} · อ่านอย่างเดียว ไม่มีการแก้ไขข้อมูลจากหน้านี้
          </p>
        </div>
        <button onClick={load}
          className="rounded-full border border-primary-300 px-4 py-1.5 text-sm font-medium text-primary-700 hover:bg-primary-50">
          ตรวจใหม่
        </button>
      </div>

      {/* สุขภาพของ "ระบบ" มาก่อนจำนวนข้อมูล — คำถามแรกของคนเปิดหน้านี้คือ "ตอนนี้ระบบปกติไหม" */}
      <h2 className="text-sm font-semibold text-gray-700 mb-2">สถานะระบบ</h2>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 mb-8">
        {(data.health ?? []).map((h) => (
          <div key={h.key} className={`rounded-xl border px-4 py-3 ${
            h.status === 'error' ? 'border-red-200 bg-red-50'
              : h.status === 'warn' ? 'border-amber-200 bg-amber-50' : 'border-gray-200 bg-white'}`}>
            <div className="flex items-start justify-between gap-2">
              <p className="text-xs text-gray-600">{h.label}</p>
              <span className={`text-xs font-semibold shrink-0 ${
                h.status === 'error' ? 'text-red-600' : h.status === 'warn' ? 'text-amber-600' : 'text-emerald-600'}`}>
                {h.status === 'error' ? '● ผิดปกติ' : h.status === 'warn' ? '● ต้องดู' : '● ปกติ'}
              </span>
            </div>
            <p className="text-lg font-light text-gray-800 mt-0.5 break-words">{h.value}</p>
            {h.hint && <p className="text-xs text-gray-500 mt-1">{h.hint}</p>}
          </div>
        ))}
      </div>

      <h2 className="text-sm font-semibold text-gray-700 mb-2">จำนวนข้อมูลในระบบ</h2>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 mb-8">
        {data.counts.map((c) => (
          <div key={c.table} className="bg-white rounded-xl border border-gray-200 px-4 py-3">
            <p className="text-xs text-gray-500">{c.label}</p>
            <p className="text-2xl font-light text-gray-800">{c.count.toLocaleString('th-TH')}</p>
          </div>
        ))}
        <div className="bg-white rounded-xl border border-gray-200 px-4 py-3">
          <p className="text-xs text-gray-500">ขนาดไฟล์แนบทั้งหมด</p>
          <p className="text-2xl font-light text-gray-800">{data.uploads_size_mb} MB</p>
          <p className="text-[10px] text-gray-400 font-mono">uploads/</p>
        </div>
      </div>

      <h2 className="text-sm font-semibold text-gray-700 mb-2">สิ่งที่ควรตรวจสอบ</h2>
      {data.issues.length === 0 ? (
        <div className="bg-white rounded-xl border border-green-200 px-4 py-6 text-center text-sm text-green-700">
          ไม่พบความผิดปกติของข้อมูล
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 divide-y">
          {data.issues.map((i) => (
            <div key={i.key} className="px-4 py-3 flex items-start gap-4">
              <span className="rounded-full bg-amber-100 text-amber-700 text-xs font-semibold px-2 py-0.5 shrink-0">
                {i.count}
              </span>
              <div className="min-w-0">
                <p className="text-sm text-gray-800">{i.label}</p>
                <p className="text-xs text-gray-500">{i.hint}</p>
              </div>
            </div>
          ))}
        </div>
      )}

      {data.audit_log_since && (
        <p className="text-xs text-gray-400 mt-6">
          ประวัติการใช้งานเก็บย้อนหลังตั้งแต่ {new Date(data.audit_log_since).toLocaleString('th-TH')}
        </p>
      )}
    </div>
  )
}
