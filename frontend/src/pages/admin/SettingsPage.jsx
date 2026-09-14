import { useEffect, useState } from 'react'
import { settingsApi } from '../../api/settingsApi.js'
import EmptyState from '../../components/common/EmptyState.jsx'
import { useAuthContext } from '../../context/AuthContext.jsx'
import { isSuperadmin } from '../../utils/role.js'

// ค่าที่ผู้ดูแลคลังแก้เองได้ (ตกลงกับผู้ใช้ 8 ก.ย. 69) — ต้องตรงกับ ADMIN_EDITABLE_KEYS ฝั่ง backend
// ที่เหลือ (ค่าปรับ/ค่าเสื่อม/มูลค่าที่พิมพ์ในใบยืม) เป็นของผู้ดูแลระบบสูงสุดเพราะกระทบเงินและเอกสารย้อนหลัง
const ADMIN_EDITABLE_KEYS = new Set([
  'default_pickup_location', 'default_pickup_time', 'due_soon_notify_days_before',
  'low_stock_threshold_default', 'max_items_per_request', 'max_active_requests_per_student',
  'max_renew_count', 'max_renew_days',
])

// จัดกลุ่มให้อ่านง่ายแทนที่จะเรียงตามตัวอักษรของ key
const GROUPS = [
  { title: 'งานประจำวัน (นัดรับ · แจ้งเตือน · สต็อก)', keys: [
    'default_pickup_location', 'default_pickup_time', 'due_soon_notify_days_before',
    'low_stock_threshold_default'] },
  { title: 'โควต้าการยืม', keys: [
    'max_items_per_request', 'max_active_requests_per_student', 'max_renew_count', 'max_renew_days'] },
  { title: 'ค่าปรับ · ค่าเสื่อม · เอกสาร (ผู้ดูแลระบบสูงสุด)', keys: [
    'fine_per_day_per_item', 'fine_grace_days', 'fine_max_per_item',
    'depreciation_years_default', 'depreciation_salvage_value', 'pdf_value_source'] },
]

// ค่าที่มีตัวเลือกตายตัว — ให้เลือกแทนพิมพ์เอง (พิมพ์ผิดตัวเดียวระบบอ่านไม่ออกทันที)
const CHOICES = {
  pdf_value_source: [['acquisition', 'มูลค่าแท้จริง (ราคาที่ซื้อ)'], ['book', 'มูลค่าตามบัญชี (หักค่าเสื่อมแล้ว)']],
}

export default function SettingsPage() {
  const { user } = useAuthContext()
  const canEditAll = isSuperadmin(user)
  const [settings, setSettings] = useState([])
  const [editing, setEditing] = useState({}) // { [key]: value }
  const [saving, setSaving] = useState({})   // { [key]: bool }
  const [saved, setSaved] = useState({})     // { [key]: bool } — flash feedback
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    settingsApi.list().then(setSettings).finally(() => setLoading(false))
  }, [])

  const [error, setError] = useState('')

  const save = async (key) => {
    const value = editing[key]
    if (value === undefined) return
    setSaving({ ...saving, [key]: true })
    setError('')
    try {
      await settingsApi.update(key, value)
      setSettings((prev) => prev.map((s) => s.key === key ? { ...s, value } : s))
      setEditing((prev) => { const next = { ...prev }; delete next[key]; return next })
      setSaved({ ...saved, [key]: true })
      setTimeout(() => setSaved((p) => { const n = { ...p }; delete n[key]; return n }), 2000)
    } catch (e) {
      setError(e.response?.data?.detail ?? 'บันทึกไม่สำเร็จ')
    } finally {
      setSaving((prev) => { const next = { ...prev }; delete next[key]; return next })
    }
  }

  if (loading) return <EmptyState>กำลังโหลด…</EmptyState>

  // จัดกลุ่มตาม GROUPS แล้วต่อท้ายด้วยค่าที่ยังไม่ได้จัดกลุ่ม (เผื่อมี setting ใหม่ที่ลืมใส่)
  const grouped = GROUPS.map((g) => ({
    ...g, items: g.keys.map((k) => settings.find((s) => s.key === k)).filter(Boolean),
  }))
  const known = new Set(GROUPS.flatMap((g) => g.keys))
  const rest = settings.filter((s) => !known.has(s.key))
  if (rest.length) grouped.push({ title: 'อื่น ๆ', items: rest })

  const renderRow = (s) => {
    const isDirty = editing[s.key] !== undefined && editing[s.key] !== s.value
    // settings.value เป็น String ทุกแถว (ไม่มีคอลัมน์บอกชนิด) — เดาจากค่าปัจจุบันแทน
    const isNumeric = /^-?\d+(\.\d+)?$/.test(s.value)
    const choices = CHOICES[s.key]
    const locked = !canEditAll && !ADMIN_EDITABLE_KEYS.has(s.key)
    return (
      <div key={s.key} className="px-5 py-4 flex flex-wrap items-center gap-4">
        <div className="flex-1 min-w-[16rem]">
          {/* ไม่โชว์ชื่อ key ดิบแล้ว (8 ก.ย. 69) — คนใช้งานอ่านคำอธิบายพอ ไม่ต้องรู้ชื่อคอลัมน์ */}
          <p className="text-sm font-medium text-gray-800">{s.description || s.key}</p>
          {locked && (
            <p className="text-xs text-amber-600 mt-0.5">
              แก้ได้เฉพาะผู้ดูแลระบบสูงสุด — ต้องการเปลี่ยนให้ยื่น "คำขอแก้ไขข้อมูล" พร้อมเหตุผล
            </p>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {choices ? (
            <select value={editing[s.key] ?? s.value} disabled={locked}
              onChange={(e) => setEditing({ ...editing, [s.key]: e.target.value })}
              className="rounded-lg border border-gray-300 px-2 py-1.5 text-sm bg-white w-64 disabled:bg-gray-50 disabled:text-gray-400">
              {choices.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
            </select>
          ) : (
            <input
              type={isNumeric ? 'number' : 'text'}
              {...(isNumeric ? { min: 0 } : {})}
              disabled={locked}
              value={editing[s.key] ?? s.value}
              onChange={(e) => setEditing({ ...editing, [s.key]: e.target.value })}
              className={`rounded-lg border border-gray-300 px-2 py-1.5 text-sm focus:outline-none focus:ring-2
                focus:ring-primary-500 disabled:bg-gray-50 disabled:text-gray-400 ${isNumeric ? 'w-24 text-center' : 'w-64'}`}
            />
          )}
          {isDirty && (
            <button onClick={() => save(s.key)} disabled={saving[s.key]}
              className="rounded-full bg-primary-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-primary-700 disabled:opacity-50">
              {saving[s.key] ? '…' : 'บันทึก'}
            </button>
          )}
          {saved[s.key] && !isDirty && <span className="text-xs text-green-600">✓</span>}
        </div>
      </div>
    )
  }

  return (
    <div className="px-6 py-8">
      <h1 className="text-2xl font-light text-gray-800">การตั้งค่าระบบ</h1>
      <p className="text-xs text-gray-500 mt-1">
        ค่าที่แก้มีผลกับการทำงาน<b>ครั้งถัดไป</b>เท่านั้น — ยอดค่าปรับ/มูลค่าที่บันทึกไปแล้วจะไม่เปลี่ยนตาม
      </p>
      {error && <p className="mt-3 text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>}

      <div className="mt-6 space-y-6">
        {grouped.filter((g) => g.items.length > 0).map((g) => (
          <section key={g.title}>
            <h2 className="text-sm font-semibold text-gray-600 mb-2">{g.title}</h2>
            <div className="bg-white rounded-xl border border-gray-200 divide-y">
              {g.items.map(renderRow)}
            </div>
          </section>
        ))}
      </div>
    </div>
  )
}
