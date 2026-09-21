import { useEffect, useState } from 'react'
import { equipmentApi } from '../../api/equipmentApi.js'
import { settingsApi } from '../../api/settingsApi.js'
import { formatAge, formatDate, formatMoney, todayTH } from '../../utils/formatDate.js'
import QualityAssessField from './QualityAssessField.jsx'
import DateInput from '../common/DateInput.jsx'

const today = () => todayTH()
const EMPTY = { name: '', serial_number: '', unit_value: '', acquired_at: today(), useful_life_years: '', note: '', replaces_part_id: '' }

/**
 * ชิ้นส่วน/การอัพเกรดของอุปกรณ์ชิ้นหนึ่ง (เช่น RAM 8→16GB บนครุภัณฑ์เลขเดิม)
 * อายุของแต่ละชิ้นส่วนนับจากวันที่ติดตั้งของตัวเอง แยกจากอายุเครื่องหลักโดยสิ้นเชิง
 */
export default function PartsPanel({ equipmentId, equipmentValue, equipmentBookValue, qualityTracked, currentQuality, onQualityChanged }) {
  const [parts, setParts] = useState([])
  const [adding, setAdding] = useState(false)
  const [form, setForm] = useState(EMPTY)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [removeTarget, setRemoveTarget] = useState(null)
  const [removeReason, setRemoveReason] = useState('')
  const [showRemoved, setShowRemoved] = useState(false)
  // ค่าคุณภาพที่จะส่งไปพร้อมการติดตั้งชิ้นส่วน (เฟส 10) — null = ไม่ประเมิน
  const [qualityAfter, setQualityAfter] = useState(null)
  const [defaultDrop, setDefaultDrop] = useState(2)

  useEffect(() => {
    if (!qualityTracked) return
    settingsApi.list().then((rows) => {
      const v = Number(rows.find((s) => s.key === 'quality_repair_default_drop')?.value)
      if (Number.isFinite(v)) setDefaultDrop(v)
    }).catch(() => {})
  }, [qualityTracked])

  const load = () => equipmentApi.listParts(equipmentId).then(setParts).catch(() => {})
  useEffect(() => { load() }, [equipmentId])

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })

  const submit = async () => {
    setBusy(true); setError('')
    try {
      await equipmentApi.addPart(equipmentId, {
        name: form.name,
        serial_number: form.serial_number || null,
        unit_value: form.unit_value === '' ? null : Number(form.unit_value),
        acquired_at: form.acquired_at,
        useful_life_years: form.useful_life_years === '' ? null : Number(form.useful_life_years),
        note: form.note || null,
        // ระบุว่ามาแทนชิ้นไหน → ได้ไทม์ไลน์ "SSD 256GB → 512GB" ต่อเนื่อง แทนกองชิ้นส่วนที่ไม่รู้ลำดับ
        replaces_part_id: form.replaces_part_id || null,
        // ประเมินคุณภาพเครื่องหลักใหม่พร้อมกัน (เฟส 10, ไม่บังคับ) — มีผลเฉพาะเครื่องที่เปิดติดตามคุณภาพ
        ...(qualityTracked ? { quality_after: qualityAfter } : {}),
      })
      if (qualityTracked && qualityAfter != null) onQualityChanged?.()
      setForm(EMPTY); setQualityAfter(null); setAdding(false); await load()
    } catch (err) {
      setError(err?.response?.data?.detail ?? 'เพิ่มชิ้นส่วนไม่สำเร็จ')
    } finally { setBusy(false) }
  }

  const confirmRemove = async () => {
    try {
      await equipmentApi.removePart(equipmentId, removeTarget.id, { reason: removeReason.trim() })
      await load()
    } catch (err) {
      setError(err?.response?.data?.detail ?? 'ถอดชิ้นส่วนไม่สำเร็จ')
    } finally { setRemoveTarget(null); setRemoveReason('') }
  }

  const installed = parts.filter((p) => p.is_installed)
  const removed = parts.filter((p) => !p.is_installed)
  const partsValue = installed.reduce((sum, p) => sum + (p.unit_value ?? 0), 0)
  const partsBook = installed.reduce((sum, p) => sum + (p.book_value ?? 0), 0)

  const input = 'w-full rounded-lg border border-gray-300 px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500'

  return (
    <div className="md:col-span-2 border-t border-gray-200 pt-4">
      <div className="flex items-center justify-between mb-2">
        <label className="text-xs font-medium text-gray-600">ชิ้นส่วน / การอัพเกรด</label>
        {!adding && (
          <button type="button" onClick={() => setAdding(true)}
            className="text-xs text-primary-600 hover:underline">+ เพิ่มชิ้นส่วน</button>
        )}
      </div>
      {error && <p className="mb-2 text-xs text-rose-600 bg-rose-50 rounded-lg px-3 py-2">{error}</p>}

      {installed.length === 0 && !adding && (
        <p className="text-xs text-gray-400">ยังไม่มีชิ้นส่วนที่ติดตั้งเพิ่ม</p>
      )}

      {installed.length > 0 && (
        <ul className="space-y-1.5">
          {installed.map((p) => (
            <li key={p.id} className="flex items-start justify-between gap-3 rounded-lg bg-gray-50 px-3 py-2">
              <div className="min-w-0">
                <p className="text-sm text-gray-700">
                  {p.name}{p.serial_number && <span className="text-gray-400 text-xs"> · SN {p.serial_number}</span>}
                </p>
                <p className="text-xs text-gray-500">
                  ติดตั้ง {formatDate(p.acquired_at)} · อายุ {formatAge(p.acquired_at)}
                  {p.unit_value != null && ` · ${formatMoney(p.unit_value)} → ${formatMoney(p.book_value)} บ.`}
                </p>
                {p.replaces_part_name && (
                  <p className="text-xs text-primary-600">↑ มาแทน {p.replaces_part_name}</p>
                )}
                {p.note && <p className="text-xs text-gray-400">{p.note}</p>}
              </div>
              <button type="button" onClick={() => { setRemoveTarget(p); setRemoveReason('') }}
                className="shrink-0 text-xs text-orange-500 hover:underline">ถอดออก</button>
            </li>
          ))}
        </ul>
      )}

      {adding && (
        <div className="mt-2 rounded-lg border border-gray-200 p-3 space-y-2">
          <input className={input} placeholder="ชื่อชิ้นส่วน เช่น RAM DDR4 16GB" value={form.name} onChange={set('name')} />
          <div className="grid grid-cols-2 gap-2">
            <DateInput className={input} type="date" value={form.acquired_at} onChange={set('acquired_at')} />
            <input className={input} type="number" min={0} step="0.01" placeholder="ราคา (บาท)"
              value={form.unit_value} onChange={set('unit_value')} />
            <input className={input} placeholder="SN (ถ้ามี)" value={form.serial_number} onChange={set('serial_number')} />
            <input className={input} type="number" min={1} placeholder="อายุใช้งาน (ปี)"
              value={form.useful_life_years} onChange={set('useful_life_years')} />
          </div>
          <input className={input} placeholder="หมายเหตุ (ถ้ามี)" value={form.note} onChange={set('note')} />
          {qualityTracked && (
            <QualityAssessField
              currentQuality={currentQuality} defaultDrop={defaultDrop}
              value={qualityAfter} onChange={setQualityAfter}
            />
          )}
          {parts.length > 0 && (
            <select className={input} value={form.replaces_part_id} onChange={set('replaces_part_id')}>
              <option value="">ชิ้นนี้ไม่ได้มาแทนชิ้นไหน (ของเพิ่มใหม่)</option>
              {parts.map((p) => (
                <option key={p.id} value={p.id}>
                  มาแทน: {p.name}{p.is_installed ? '' : ' (ถอดออกแล้ว)'}
                </option>
              ))}
            </select>
          )}
          <div className="flex gap-2">
            <button type="button" onClick={() => { setAdding(false); setForm(EMPTY); setError('') }}
              className="flex-1 rounded-full border border-gray-300 py-1.5 text-xs text-gray-600 hover:bg-gray-50">ยกเลิก</button>
            <button type="button" onClick={submit} disabled={busy || !form.name || !form.acquired_at}
              className="flex-1 rounded-full bg-primary-600 py-1.5 text-xs font-medium text-white hover:bg-primary-700 disabled:opacity-50">
              {busy ? 'กำลังบันทึก…' : 'บันทึกชิ้นส่วน'}
            </button>
          </div>
        </div>
      )}

      {removed.length > 0 && (
        <div className="mt-2">
          <button type="button" onClick={() => setShowRemoved((v) => !v)}
            className="text-xs text-gray-400 hover:text-gray-600">
            {showRemoved ? '▾' : '▸'} ชิ้นส่วนที่ถอดออกแล้ว ({removed.length})
          </button>
          {showRemoved && (
            <ul className="mt-1 space-y-1">
              {removed.map((p) => (
                <li key={p.id} className="text-xs text-gray-400 px-3">
                  {p.name} · ติดตั้ง {formatDate(p.acquired_at)} · ถอดออก {formatDate(p.removed_at)}
                  {p.removed_reason && ` (${p.removed_reason})`}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {installed.length > 0 && (
        <p className="mt-2 text-xs text-gray-600">
          มูลค่ารวมทั้งเครื่อง: <span className="font-medium">{formatMoney((equipmentValue ?? 0) + partsValue)}</span> บ.
          {equipmentBookValue != null && (
            <span className="text-gray-400"> · ตามบัญชี {formatMoney(equipmentBookValue + partsBook)} บ.</span>
          )}
        </p>
      )}

      {removeTarget && (
        <div className="mt-2 rounded-lg border border-orange-200 bg-orange-50 p-3 space-y-2">
          <p className="text-xs text-orange-800">
            ถอด <span className="font-medium">{removeTarget.name}</span> ออก — ประวัติจะยังถูกเก็บไว้
          </p>
          <p className="text-xs text-orange-700/80">
            ระบบไม่ตัด/คืนสต็อกให้ ถ้าจะเอาของที่ถอดออกเข้าคลังให้ยืม ต้องเพิ่มเป็นวัสดุแยกเองที่หน้าจัดการอุปกรณ์
          </p>
          <input className={input} placeholder="เหตุผล เช่น อัพเกรดเป็น 16GB"
            value={removeReason} onChange={(e) => setRemoveReason(e.target.value)} />
          <div className="flex gap-2">
            <button type="button" onClick={() => { setRemoveTarget(null); setRemoveReason('') }}
              className="flex-1 rounded-full border border-gray-300 bg-white py-1.5 text-xs text-gray-600 hover:bg-gray-50">ยกเลิก</button>
            <button type="button" onClick={confirmRemove} disabled={!removeReason.trim()}
              className="flex-1 rounded-full bg-orange-500 py-1.5 text-xs font-medium text-white hover:bg-orange-600 disabled:opacity-50">
              ยืนยันถอดออก
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
