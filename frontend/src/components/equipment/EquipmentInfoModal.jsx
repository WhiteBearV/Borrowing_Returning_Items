import { useEffect, useState } from 'react'
import { equipmentApi } from '../../api/equipmentApi.js'
import { formatAge, formatDate, formatDateTime, formatMoney } from '../../utils/formatDate.js'
import { formatPlace } from '../../utils/location.js'
import StatusBadge from './StatusBadge.jsx'

const TYPE_LABEL = { durable: 'ครุภัณฑ์', material: 'วัสดุใช้ซ้ำ', consumable: 'วัสดุสิ้นเปลือง' }
const IMG_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const imageSrc = (url) => (url?.startsWith('/') ? `${IMG_BASE}${url}` : url)

function Section({ title, rows }) {
  return (
    <div>
      <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-gray-500">{title}</h3>
      <dl className="grid grid-cols-1 gap-x-6 gap-y-1.5 sm:grid-cols-2">
        {rows.map(([label, value]) => (
          <div key={label} className="flex gap-2 text-sm">
            <dt className="w-32 shrink-0 text-gray-500">{label}</dt>
            <dd className="min-w-0 break-words text-gray-800">{value == null || value === '' ? '—' : value}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

/** ดูข้อมูลอุปกรณ์ชิ้นเดียวแบบครบทุกช่อง (อ่านอย่างเดียว) — ตารางจัดการอุปกรณ์โชว์ได้แค่บางคอลัมน์ (23 พ.ย. 69)
 *  onEdit(eq) = เปิดฟอร์มแก้ไขของชิ้นนี้ต่อ */
export default function EquipmentInfoModal({ id, onClose, onEdit }) {
  const [eq, setEq] = useState(null)
  const [parts, setParts] = useState([])
  const [error, setError] = useState('')

  useEffect(() => {
    equipmentApi.get(id).then(setEq).catch((e) => setError(e.response?.data?.detail ?? 'โหลดข้อมูลไม่สำเร็จ'))
    equipmentApi.listParts(id, false).then(setParts).catch(() => {})
  }, [id])

  const holders = eq?.holders ?? []
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-black/40 px-4 py-6 backdrop-blur-sm">
      <div className="w-full max-w-3xl space-y-5 rounded-2xl bg-white p-6 shadow-xl">
        {!eq ? (
          <p className="text-sm text-gray-500">{error || 'กำลังโหลด…'}</p>
        ) : (
          <>
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <h2 className="text-lg font-bold text-gray-800">{eq.name}</h2>
                <p className="font-mono text-xs text-gray-500">{eq.code}{eq.asset_number && ` · ครุภัณฑ์ ${eq.asset_number}`}</p>
                {eq.asset_name && eq.asset_name !== eq.name && <p className="text-xs text-gray-500">ชื่อตามทะเบียน: {eq.asset_name}</p>}
              </div>
              <StatusBadge status={eq.status} isCurrentlyBorrowed={eq.is_currently_borrowed} isBorrowable={eq.is_borrowable} />
            </div>

            {eq.image_urls?.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {eq.image_urls.map((u) => (
                  <a key={u} href={imageSrc(u)} target="_blank" rel="noreferrer">
                    <img src={imageSrc(u)} alt="" className="h-24 w-24 rounded-lg border border-gray-200 object-cover" />
                  </a>
                ))}
              </div>
            )}

            <Section title="ข้อมูลประจำตัว" rows={[
              ['ประเภท', TYPE_LABEL[eq.item_type] ?? eq.item_type],
              ['หมวดหมู่', eq.categories?.map((c) => c.name).join(', ')],
              ['ผู้ผลิต', eq.manufacturer],
              ['รุ่น', eq.model_number],
              ['SN', eq.serial_number],
              ['ห้อง', eq.location],
              ['ตำแหน่งในห้อง', eq.location_detail],
              ['คำอธิบาย', eq.description],
            ]} />

            <Section title="สถานะ & การใช้งาน" rows={[
              ['ให้ยืมออกนอกห้อง', eq.is_borrowable ? 'ได้' : 'ไม่ได้ (ของประจำห้อง)'],
              ['คงเหลือ / ทั้งหมด', `${eq.quantity_available} / ${eq.quantity_total}${eq.unit ? ` ${eq.unit}` : ''}`],
              ['เตือนสต็อกต่ำที่', eq.low_stock_threshold],
              ['ค่าปรับคืนเกินกำหนด', eq.fine_rate_per_day == null ? null : `${eq.fine_rate_name} (${formatMoney(eq.fine_rate_per_day)} บาท/วัน)`],
              ['ผู้ยืมอยู่', holders.length
                ? holders.map((h) => `${h.holder_name ?? 'มีผู้ยืมอยู่'}${h.student_number ? ` (${h.student_number})` : ''}`
                  + `${h.due_date ? ` คืน ${formatDate(h.due_date)}` : ''}${h.quantity > 1 ? ` ×${h.quantity}` : ''}`).join(' · ')
                : 'ไม่มี'],
            ]} />

            <Section title="ทะเบียน & การเงิน" rows={[
              ['ราคาต่อหน่วย', eq.unit_value == null ? 'ยังไม่มีราคา' : `${formatMoney(eq.unit_value)} บาท`],
              ['วันที่ได้มา', eq.acquired_at ? `${formatDate(eq.acquired_at)} (${formatAge(eq.acquired_at)})` : null],
              ['อายุการใช้งาน', eq.useful_life_years ? `${eq.useful_life_years} ปี` : 'ใช้ค่ากลางของระบบ'],
              ['มูลค่าตามบัญชี', eq.book_value == null
                ? (eq.unit_value == null ? null : 'คำนวณไม่ได้ — ยังไม่มีวันที่ได้มา')
                : `${formatMoney(eq.book_value)} บาท${eq.book_value_override != null ? ' (กรอกเอง)' : ''}`],
            ]} />

            {eq.quality_tracked && (
              <Section title="คุณภาพ" rows={[
                ['คุณภาพปัจจุบัน', eq.current_quality == null ? 'ยังไม่เคยประเมิน' : `${eq.current_quality}%`],
                ['ประเมินล่าสุด', eq.quality_baseline_at ? `${formatDateTime(eq.quality_baseline_at)} (${eq.quality_baseline}%)` : null],
                ['อายุที่เหลือ', eq.quality_remaining_life_years == null ? null : `${eq.quality_remaining_life_years} ปี`],
                ['ควรตรวจสภาพ', eq.quality_needs_inspection ? 'ใช่' : 'ไม่'],
              ]} />
            )}

            {parts.length > 0 && (
              <div>
                <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-gray-500">ชิ้นส่วนที่ติดตั้งอยู่</h3>
                <ul className="space-y-1 text-sm text-gray-800">
                  {parts.map((p) => (
                    <li key={p.id}>{p.name}{p.serial_number && <span className="text-gray-500"> · SN {p.serial_number}</span>}
                      {p.acquired_at && <span className="text-gray-500"> · ติดตั้ง {formatDate(p.acquired_at)}</span>}</li>
                  ))}
                </ul>
              </div>
            )}

            <p className="text-xs text-gray-400">
              {formatPlace(eq.location, eq.location_detail) && `ที่เก็บ ${formatPlace(eq.location, eq.location_detail)} · `}
              สร้างในระบบ {formatDateTime(eq.created_at)} · แก้ไขล่าสุด {formatDateTime(eq.updated_at)}
            </p>
          </>
        )}

        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose}
            className="rounded-full border border-gray-300 px-5 py-2 text-sm font-medium text-gray-600 hover:bg-gray-50">ปิด</button>
          {eq && onEdit && (
            <button type="button" onClick={() => onEdit(eq)}
              className="rounded-full bg-primary-600 px-5 py-2 text-sm font-semibold text-white hover:bg-primary-700">แก้ไข</button>
          )}
        </div>
      </div>
    </div>
  )
}
