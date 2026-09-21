import { useEffect, useState } from 'react'
import { changeRequestApi } from '../../api/changeRequestApi.js'
import { useAuthContext } from '../../context/AuthContext.jsx'
import { isSuperadmin } from '../../utils/role.js'
import EmptyState from '../../components/common/EmptyState.jsx'
import Pagination from '../../components/common/Pagination.jsx'
import { formatDateTime } from '../../utils/formatDate.js'

const STATUS_LABEL = { pending: 'รอดำเนินการ', approved: 'ทำให้แล้ว', rejected: 'ไม่ดำเนินการ' }
const STATUS_CLASS = {
  pending: 'bg-amber-100 text-amber-700',
  approved: 'bg-green-100 text-green-700',
  rejected: 'bg-red-100 text-red-600',
}
// ตารางที่ขอแก้ได้ — ชื่อไทยเพื่อให้ผู้ดูแลคลังเลือกได้โดยไม่ต้องรู้ชื่อตารางจริง
const TARGETS = [
  { value: 'equipment', label: 'อุปกรณ์ในคลัง' },
  { value: 'users', label: 'บัญชีผู้ใช้' },
  { value: 'borrow_requests', label: 'คำขอยืม / ประวัติการยืม' },
  { value: 'settings', label: 'การตั้งค่าระบบ' },
  { value: 'other', label: 'อื่น ๆ' },
]

function NewRequestModal({ onClose, onCreated }) {
  const [form, setForm] = useState({ target_table: 'equipment', target_label: '', reason: '', detail: '' })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const submit = async (e) => {
    e.preventDefault()
    setSaving(true)
    setError('')
    try {
      await changeRequestApi.create({
        target_table: form.target_table,
        target_label: form.target_label || undefined,
        reason: form.reason,
        detail: form.detail || undefined,
      })
      onCreated()
    } catch (err) {
      setError(err.response?.data?.detail ?? 'ส่งคำขอไม่สำเร็จ')
    } finally {
      setSaving(false)
    }
  }

  const inputClass = 'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500'
  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50 px-4" onClick={onClose}>
      <form onSubmit={submit} className="bg-white rounded-2xl p-6 w-full max-w-lg shadow-xl space-y-3"
        onClick={(e) => e.stopPropagation()}>
        <h2 className="font-bold text-gray-800">ขอให้ผู้ดูแลระบบแก้ไขข้อมูล</h2>
        <p className="text-xs text-gray-500">
          คำขอนี้เก็บเป็นหลักฐานว่าใครขออะไรเพราะอะไร — ผู้ดูแลระบบสูงสุดจะเป็นผู้แก้ให้แล้วกลับมาปิดงาน
        </p>
        {error && <div className="rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">{error}</div>}

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">เรื่องที่ขอแก้</label>
          <select value={form.target_table} onChange={(e) => setForm({ ...form, target_table: e.target.value })}
            className={`${inputClass} bg-white`}>
            {TARGETS.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">ระบุรายการ (ชื่อ/รหัส)</label>
          <input type="text" value={form.target_label} placeholder="เช่น NB-001 โน้ตบุ๊ค Dell"
            onChange={(e) => setForm({ ...form, target_label: e.target.value })} className={inputClass} />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            เหตุผลที่ต้องแก้ <span className="text-red-500">*</span>
          </label>
          <textarea rows={2} required value={form.reason}
            onChange={(e) => setForm({ ...form, reason: e.target.value })}
            placeholder="เช่น รหัสครุภัณฑ์พิมพ์ผิดตั้งแต่ตอนนำเข้าไฟล์ทะเบียน"
            className={`${inputClass} resize-none`} />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">อยากให้แก้เป็นอะไร</label>
          <textarea rows={3} value={form.detail}
            onChange={(e) => setForm({ ...form, detail: e.target.value })}
            placeholder="เช่น เปลี่ยนรหัสจาก 671001 เป็น 671010"
            className={`${inputClass} resize-none`} />
        </div>

        <div className="flex gap-3 pt-1">
          <button type="button" onClick={onClose}
            className="flex-1 rounded-full border border-gray-300 py-2 text-sm text-gray-600 hover:bg-gray-50">ยกเลิก</button>
          <button type="submit" disabled={saving}
            className="flex-1 rounded-full bg-primary-600 py-2 text-sm font-semibold text-white hover:bg-primary-700 disabled:opacity-50">
            {saving ? 'กำลังส่ง…' : 'ส่งคำขอ'}
          </button>
        </div>
      </form>
    </div>
  )
}

function DecisionModal({ target, onClose, onDone }) {
  const [note, setNote] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const rejecting = target.action === 'reject'

  const submit = async () => {
    setSaving(true)
    setError('')
    try {
      if (rejecting) await changeRequestApi.reject(target.id, note)
      else await changeRequestApi.approve(target.id, note || undefined)
      onDone()
    } catch (err) {
      setError(err.response?.data?.detail ?? 'บันทึกไม่สำเร็จ')
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50 px-4" onClick={onClose}>
      <div className="bg-white rounded-2xl p-6 w-full max-w-md shadow-xl space-y-3" onClick={(e) => e.stopPropagation()}>
        <h2 className="font-bold text-gray-800">{rejecting ? 'ไม่ดำเนินการตามคำขอ' : 'ปิดงาน: ทำให้แล้ว'}</h2>
        <p className="text-xs text-gray-500">
          {rejecting
            ? 'ผู้ยื่นจะเห็นเหตุผลนี้ในรายการคำขอของตัวเอง'
            : 'กดยืนยันหลังจากแก้ข้อมูลจริงเรียบร้อยแล้ว — ระบบไม่ได้แก้ให้อัตโนมัติจากคำขอนี้'}
        </p>
        {error && <div className="rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">{error}</div>}
        <textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)}
          placeholder={rejecting ? 'เหตุผลที่ไม่ดำเนินการ (จำเป็น)' : 'บันทึกเพิ่มเติม (ไม่บังคับ)'}
          className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-primary-500" />
        <div className="flex gap-3">
          <button onClick={onClose} className="flex-1 rounded-full border border-gray-300 py-2 text-sm text-gray-600 hover:bg-gray-50">ยกเลิก</button>
          <button onClick={submit} disabled={saving}
            className={`flex-1 rounded-full py-2 text-sm font-semibold text-white disabled:opacity-50 ${
              rejecting ? 'bg-red-600 hover:bg-red-700' : 'bg-primary-600 hover:bg-primary-700'}`}>
            {saving ? '…' : 'ยืนยัน'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default function ChangeRequestsPage() {
  const { user } = useAuthContext()
  const canDecide = isSuperadmin(user)
  const [data, setData] = useState({ items: [], total: 0 })
  const [page, setPage] = useState(1)
  const [filterStatus, setFilterStatus] = useState('')
  const [loading, setLoading] = useState(true)
  const [showNew, setShowNew] = useState(false)
  const [decision, setDecision] = useState(null) // { id, action }

  const load = () => {
    setLoading(true)
    changeRequestApi.list({ page, page_size: 20, status: filterStatus || undefined })
      .then(setData).finally(() => setLoading(false))
  }
  useEffect(load, [page, filterStatus])

  return (
    <div className="px-6 py-8">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-4">
        <div>
          <h1 className="text-2xl font-light text-gray-800">คำขอแก้ไขข้อมูล</h1>
          <p className="text-xs text-gray-500 mt-1">
            {canDecide
              ? 'คำขอจากผู้ดูแลคลังที่ต้องให้คุณแก้ให้ — แก้เสร็จแล้วกดปิดงานเพื่อเก็บเป็นหลักฐาน'
              : 'เรื่องที่คุณแก้เองไม่ได้ ส่งให้ผู้ดูแลระบบสูงสุดทำให้ พร้อมบันทึกเป็นหลักฐาน'}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <select value={filterStatus} onChange={(e) => { setFilterStatus(e.target.value); setPage(1) }}
            className="rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500">
            <option value="">ทุกสถานะ</option>
            {Object.entries(STATUS_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
          <button onClick={() => setShowNew(true)}
            className="rounded-full bg-primary-600 px-4 py-2 text-sm font-semibold text-white hover:bg-primary-700">
            + ยื่นคำขอ
          </button>
        </div>
      </div>

      {loading ? (
        <EmptyState>กำลังโหลด…</EmptyState>
      ) : data.items.length === 0 ? (
        <EmptyState>ยังไม่มีคำขอแก้ไขข้อมูล</EmptyState>
      ) : (
        <div className="space-y-3">
          {data.items.map((cr) => (
            <div key={cr.id} className="bg-white rounded-xl border border-gray-200 px-4 py-3">
              <div className="flex flex-wrap items-center gap-2 mb-1">
                <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${STATUS_CLASS[cr.status]}`}>
                  {STATUS_LABEL[cr.status] ?? cr.status}
                </span>
                <span className="text-sm font-medium text-gray-800">
                  {TARGETS.find((t) => t.value === cr.target_table)?.label ?? cr.target_table}
                  {cr.target_label ? ` · ${cr.target_label}` : ''}
                </span>
                <span className="text-xs text-gray-400 ml-auto">
                  {cr.requester_name} · {formatDateTime(cr.created_at)}
                </span>
              </div>
              <p className="text-sm text-gray-700">เหตุผล: {cr.reason}</p>
              {cr.detail && <p className="text-sm text-gray-500 mt-0.5">สิ่งที่ขอให้แก้: {cr.detail}</p>}
              {cr.status !== 'pending' && (
                <p className="text-xs text-gray-500 mt-1">
                  {STATUS_LABEL[cr.status]} โดย {cr.decided_by_name ?? '—'}
                  {cr.decided_at ? ` · ${formatDateTime(cr.decided_at)}` : ''}
                  {cr.decision_note ? ` · ${cr.decision_note}` : ''}
                </p>
              )}
              {canDecide && cr.status === 'pending' && (
                <div className="flex gap-2 mt-2">
                  <button onClick={() => setDecision({ id: cr.id, action: 'approve' })}
                    className="rounded-full bg-primary-50 text-primary-700 px-3 py-1 text-xs font-medium hover:bg-primary-100">
                    ทำให้แล้ว
                  </button>
                  <button onClick={() => setDecision({ id: cr.id, action: 'reject' })}
                    className="rounded-full border border-red-200 text-red-600 px-3 py-1 text-xs hover:bg-red-50">
                    ไม่ดำเนินการ
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <Pagination page={page} total={data.total} pageSize={20} onChange={setPage} />

      {showNew && <NewRequestModal onClose={() => setShowNew(false)}
        onCreated={() => { setShowNew(false); load() }} />}
      {decision && <DecisionModal target={decision} onClose={() => setDecision(null)}
        onDone={() => { setDecision(null); load() }} />}
    </div>
  )
}
