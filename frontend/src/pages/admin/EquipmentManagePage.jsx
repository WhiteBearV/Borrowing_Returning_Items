import { Fragment, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { equipmentApi } from '../../api/equipmentApi.js'
import { bundleApi } from '../../api/bundleApi.js'
import { useAuthContext } from '../../context/AuthContext.jsx'
import ConfirmModal from '../../components/common/ConfirmModal.jsx'
import Pagination from '../../components/common/Pagination.jsx'
import Tooltip from '../../components/common/Tooltip.jsx'
import { openPdf } from '../../utils/openPdf.js'

const EMPTY_FORM = { code: '', serial_number: '', name: '', category_ids: [], item_type: 'durable', description: '', location: '', unit: '', unit_value: '', quantity_total: 1, image_urls: [], is_borrowable: true }

// ไอคอนสถานที่ (แทนอีโมจิหมุด 📍 เดิม) — เส้นสไตล์เดียวกับไอคอนอื่นในระบบ (currentColor, stroke)
const LocationIcon = ({ className = 'w-3.5 h-3.5' }) => (
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={`inline shrink-0 ${className}`}>
    <path d="M15 10.5a3 3 0 11-6 0 3 3 0 016 0z" />
    <path d="M19.5 10.5c0 7.142-7.5 11.25-7.5 11.25S4.5 17.642 4.5 10.5a7.5 7.5 0 1115 0z" />
  </svg>
)

const IMG_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const imageSrc = (url) => (url?.startsWith('/') ? `${IMG_BASE}${url}` : url)

// FastAPI 422 คืน detail เป็น array ของ object — บังคับให้ได้ string เสมอ กัน React crash
const errMsg = (err, fallback) => {
  const d = err.response?.data?.detail
  if (typeof d === 'string') return d
  if (Array.isArray(d)) return d.map((e) => e.msg).join(', ')
  return fallback
}

function EquipmentModal({ initial, categories, onClose, onSave }) {
  const isEdit = !!initial?.id
  const [form, setForm] = useState(
    isEdit
      ? { ...initial, image_urls: initial.image_urls ?? (initial.image_url ? [initial.image_url] : []), category_ids: (initial.categories ?? []).map((c) => c.id) }
      : EMPTY_FORM,
  )
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [uploading, setUploading] = useState(false)

  // ชุดอุปกรณ์ที่อุปกรณ์ชิ้นนี้เป็นสมาชิกอยู่ — แก้ไขได้ตรงนี้แทนที่จะต้องไปหน้า "ชุดอุปกรณ์" แยก
  // เฉพาะตอนแก้ไข (มี id แล้ว) ของใหม่ยังไม่มี id ให้ผูกกับชุดไม่ได้
  const [bundles, setBundles] = useState([])
  const [bundleMembership, setBundleMembership] = useState({}) // { [bundleId]: { included, trigger } }

  useEffect(() => {
    if (!isEdit) return
    bundleApi.list().then((list) => {
      setBundles(list)
      const membership = {}
      for (const b of list) {
        membership[b.id] = {
          included: b.items.some((i) => i.equipment_id === initial.id),
          trigger: b.trigger_equipment_id === initial.id,
        }
      }
      setBundleMembership(membership)
    }).catch(() => {})
  }, [])

  // ห้ามเป็นทั้งสมาชิกและตัวกระตุ้นพร้อมกัน (backend บังคับ) — ต้องเช็คค่า "ใหม่" ของ included ไม่ใช่ค่าเดิม
  // ไม่งั้นติ๊กเข้าเป็นสมาชิกทั้งที่ยังเป็นตัวกระตุ้นอยู่ได้ (เจอบั๊กจริง — บันทึกแล้ว 400 ทุกครั้งเพราะชนกัน)
  const toggleBundleIncluded = (bundleId) => setBundleMembership((m) => {
    const included = !m[bundleId].included
    return { ...m, [bundleId]: { included, trigger: included ? false : m[bundleId].trigger } }
  })
  const toggleBundleTrigger = (bundleId) => setBundleMembership((m) => {
    const trigger = !m[bundleId].trigger
    return { ...m, [bundleId]: { included: trigger ? false : m[bundleId].included, trigger } }
  })

  // บันทึกชุดที่สมาชิกภาพ/ตัวกระตุ้นเปลี่ยนไปจากตอนเปิดฟอร์ม — เรียกหลัง equipment บันทึกสำเร็จแล้ว
  const saveBundleChanges = async (equipmentId) => {
    for (const b of bundles) {
      const m = bundleMembership[b.id]
      const wasIncluded = b.items.some((i) => i.equipment_id === equipmentId)
      const wasTrigger = b.trigger_equipment_id === equipmentId
      if (m.included === wasIncluded && m.trigger === wasTrigger) continue
      const items = m.included
        ? (wasIncluded ? b.items : [...b.items, { equipment_id: equipmentId, quantity: 1 }])
        : b.items.filter((i) => i.equipment_id !== equipmentId)
      await bundleApi.update(b.id, {
        trigger_equipment_id: m.trigger ? equipmentId : (wasTrigger ? null : b.trigger_equipment_id),
        items: items.map(({ equipment_id, quantity }) => ({ equipment_id, quantity })),
      })
    }
  }

  const uploadImage = async (e) => {
    const files = Array.from(e.target.files ?? [])
    if (!files.length) return
    e.target.value = ''  // reset ให้เลือกไฟล์เดิมซ้ำได้
    setError('')
    setUploading(true)
    try {
      const results = await Promise.all(files.map((file) => equipmentApi.uploadImage(file)))
      setForm((f) => ({ ...f, image_urls: [...f.image_urls, ...results.map((r) => r.image_url)] }))
    } catch (err) {
      setError(errMsg(err, 'อัปโหลดรูปไม่สำเร็จ'))
    } finally {
      setUploading(false)
    }
  }

  const removeImage = (url) => setForm((f) => ({ ...f, image_urls: f.image_urls.filter((u) => u !== url) }))

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })
  // เปลี่ยนออกจาก consumable แล้ว unit เดิม (ที่กรอกไว้ตอนเป็นวัสดุสิ้นเปลือง) ไม่มีความหมายแล้ว — เคลียร์ทิ้ง
  const setItemType = (e) => setForm((f) => ({
    ...f, item_type: e.target.value, unit: e.target.value === 'consumable' ? f.unit : '',
  }))
  const toggleCategory = (id) =>
    setForm((f) => ({
      ...f,
      category_ids: f.category_ids.includes(id)
        ? f.category_ids.filter((c) => c !== id)
        : [...f.category_ids, id],
    }))

  const submit = async (e) => {
    e.preventDefault()
    if (form.category_ids.length === 0) { setError('เลือกหมวดหมู่อย่างน้อย 1 หมวด'); return }
    // บังคับรูปเฉพาะตอนเพิ่มใหม่ ของเดิมที่นำเข้าจากทะเบียนยังไม่มีรูป ต้องแก้ไขได้อยู่
    if (!isEdit && form.image_urls.length === 0) { setError('แนบรูปอุปกรณ์อย่างน้อย 1 รูป'); return }
    setError('')
    setLoading(true)
    try {
      const payload = {
        ...form,
        quantity_total: Number(form.quantity_total),
        description: form.description || undefined,
        serial_number: form.serial_number || undefined,
        location: form.location || undefined,
        unit: form.unit || undefined,
        unit_value: form.unit_value === '' || form.unit_value == null ? undefined : Number(form.unit_value),
        image_urls: form.image_urls,
      }
      if (isEdit) {
        await equipmentApi.update(initial.id, payload)
        await saveBundleChanges(initial.id)
      } else {
        await equipmentApi.create(payload)
      }
      onSave()
    } catch (err) {
      setError(errMsg(err, 'บันทึกไม่สำเร็จ'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50 px-4 overflow-y-auto py-8">
      {/* กว้างขึ้น + 2 คอลัมน์ — เดิมคอลัมน์เดียวยาวลงมากเพราะฟิลด์เพิ่มขึ้นเรื่อยๆ (code/item_type แก้ได้, สถานะ, ชุดอุปกรณ์) */}
      <div className="bg-white rounded-2xl p-6 w-full max-w-2xl shadow-xl">
        <h2 className="font-bold text-gray-800 mb-4">{isEdit ? 'แก้ไขอุปกรณ์' : 'เพิ่มอุปกรณ์ใหม่'}</h2>
        {error && <p className="mb-3 text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>}
        <form onSubmit={submit} className="grid grid-cols-1 md:grid-cols-2 gap-x-4 gap-y-3">
          {[
            { label: `รหัสอุปกรณ์${form.item_type === 'consumable' ? '' : ' *'}`, key: 'code',
              required: form.item_type !== 'consumable', disabled: false,
              placeholder: form.item_type === 'consumable' ? 'เว้นว่างได้ ระบบจะออกรหัสให้อัตโนมัติ' : undefined },
            { label: 'SN (Serial Number ผู้ผลิต)', key: 'serial_number', placeholder: 'เลขที่ผู้ผลิตติดมากับเครื่อง (ไม่บังคับ)',
              tip: 'เลขประจำเครื่องจากผู้ผลิต คนละอย่างกับรหัสอุปกรณ์ด้านบน — ใช้ยืนยันว่าเป็นเครื่องจริงตอนตรวจนับอุปกรณ์' },
            { label: 'ชื่ออุปกรณ์ *', key: 'name', required: true },
            { label: 'สถานที่เก็บ', key: 'location', placeholder: 'เช่น 15312 ตู้A ชั้น3 (ไม่บังคับ)' },
          ].map(({ label, key, required, disabled, placeholder, tip }) => (
            <div key={key}>
              <label className="flex items-center gap-1.5 text-xs font-medium text-gray-600 mb-1">
                {label}
                {tip && <Tooltip text={tip} />}
              </label>
              <input type="text" required={required} disabled={disabled} value={form[key]} onChange={set(key)}
                placeholder={placeholder}
                className="w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:bg-gray-50 disabled:text-gray-400" />
            </div>
          ))}

          <div className="md:col-span-2">
            <label className="block text-xs font-medium text-gray-600 mb-1">
              รูปภาพ {form.image_urls.length > 0 && <span className="text-gray-400">({form.image_urls.length} รูป · รูปแรก = ปก)</span>}
            </label>
            {form.image_urls.length > 0 && (
              <div className="flex flex-wrap gap-2 mb-2">
                {form.image_urls.map((url, i) => (
                  <div key={url} className="relative group">
                    <img src={imageSrc(url)} alt="" className="w-16 h-16 rounded-lg object-cover border border-gray-200" />
                    {i === 0 && <span className="absolute bottom-0 inset-x-0 bg-primary-600/80 text-white text-[10px] text-center rounded-b-lg">ปก</span>}
                    <button type="button" onClick={() => removeImage(url)}
                      className="absolute -top-1.5 -right-1.5 bg-red-500 text-white rounded-full w-5 h-5 text-xs leading-none flex items-center justify-center shadow hover:bg-red-600">×</button>
                  </div>
                ))}
              </div>
            )}
            <input type="file" accept="image/*" multiple onChange={uploadImage} disabled={uploading}
              className="block w-full text-xs text-gray-500 file:mr-2 file:rounded-lg file:border-0 file:bg-primary-50 file:px-3 file:py-1.5 file:text-xs file:font-medium file:text-primary-700 hover:file:bg-primary-100" />
            {uploading && <p className="mt-1 text-xs text-gray-400">กำลังอัปโหลด…</p>}
          </div>

          <div className="md:col-span-2">
            <label className="block text-xs font-medium text-gray-600 mb-1">หมวดหมู่ * (เลือกได้หลายหมวด)</label>
            <div className="flex flex-wrap gap-1.5 rounded-lg border border-gray-300 p-2 max-h-32 overflow-y-auto">
              {categories.map((c) => {
                const on = form.category_ids.includes(c.id)
                return (
                  <button type="button" key={c.id} onClick={() => toggleCategory(c.id)}
                    className={`rounded-full px-2.5 py-1 text-xs font-medium transition-colors ${
                      on ? 'bg-primary-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                    }`}>
                    {c.name}
                  </button>
                )
              })}
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">ประเภท *</label>
            <select value={form.item_type} onChange={setItemType}
              className="w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:bg-gray-50">
              <option value="durable">ครุภัณฑ์</option>
              <option value="material">วัสดุ</option>
              <option value="consumable">วัสดุสิ้นเปลือง</option>
            </select>
          </div>

          {isEdit && (
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">สถานะ</label>
              <select value={form.status} onChange={set('status')}
                className="w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500">
                <option value="available">พร้อมให้ยืม</option>
                <option value="unavailable">ไม่อนุญาตให้ยืม</option>
                <option value="damaged">เสียหาย</option>
                <option value="under_repair">ซ่อมอยู่</option>
                <option value="retired">ปลดระวาง</option>
              </select>
            </div>
          )}

          <label className="flex items-start gap-2 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2">
            <input type="checkbox" checked={!form.is_borrowable} className="mt-0.5"
              onChange={(e) => setForm({ ...form, is_borrowable: !e.target.checked })} />
            <span className="text-xs text-gray-600">
              <span className="font-medium text-gray-700">ของประจำห้อง — ห้ามยืมออก</span>
              <br />เช่น โต๊ะ ตู้ ทีวี เครื่องที่ติดตั้งประจำที่ — นักศึกษาจะเห็นแต่ยืมไม่ได้
            </span>
          </label>

          <div className={form.item_type === 'consumable' ? 'grid grid-cols-3 gap-3' : 'grid grid-cols-2 gap-3'}>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">จำนวนทั้งหมด *</label>
              <input type="number" min={1} required value={form.quantity_total} onChange={set('quantity_total')}
                className="w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
            </div>
            {form.item_type === 'consumable' && (
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">หน่วย</label>
                <input type="text" value={form.unit} onChange={set('unit')} placeholder="ชิ้น / ก้อน…"
                  className="w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
              </div>
            )}
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">มูลค่า/ชิ้น (บาท)</label>
              <input type="number" min={0} step="0.01" value={form.unit_value ?? ''} onChange={set('unit_value')}
                placeholder="เช่น 200 (เว้นว่างได้)"
                className="w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
            </div>
          </div>

          {isEdit && bundles.length > 0 && (
            <div className="md:col-span-2">
              <label className="flex items-center gap-1.5 text-xs font-medium text-gray-600 mb-1">
                ชุดอุปกรณ์
                <Tooltip text={'ติ๊กชื่อชุด = อุปกรณ์นี้เป็นสมาชิกของชุดนั้น\nติ๊ก "ตัวกระตุ้น" เพิ่ม = กด "+ เพิ่มในตะกร้า" บนอุปกรณ์ตัวนี้แล้วจะได้อุปกรณ์ทั้งชุดมาในตะกร้าอัตโนมัติ (เลือกตัวกระตุ้นได้ชุดละ 1 ชิ้น)'} />
              </label>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-3 gap-y-1.5 rounded-lg border border-gray-300 p-2 max-h-32 overflow-y-auto">
                {bundles.map((b) => {
                  const m = bundleMembership[b.id]
                  if (!m) return null
                  return (
                    <div key={b.id} className="flex items-center gap-2 text-xs">
                      <label className="flex items-center gap-1.5 flex-1 min-w-0">
                        <input type="checkbox" checked={m.included} onChange={() => toggleBundleIncluded(b.id)} />
                        <span className="truncate text-gray-700">{b.name}</span>
                      </label>
                      {/* โชว์ตลอดแม้ยังไม่ติ๊ก "สมาชิก" เพราะตัวกระตุ้นของชุด included=false เสมอ (คนละสถานะกับสมาชิก)
                          — เดิมซ่อนไว้จนกว่าจะติ๊กสมาชิกก่อน ทำให้แก้ไข/ถอดความเป็นตัวกระตุ้นไม่ได้เลย (เจอบั๊กจริง) */}
                      {(m.included || m.trigger) && (
                        <label className="flex items-center gap-1 shrink-0 text-gray-500">
                          <input type="checkbox" checked={m.trigger} onChange={() => toggleBundleTrigger(b.id)} />
                          ตัวกระตุ้น
                        </label>
                      )}
                    </div>
                  )
                })}
              </div>
              <p className="mt-1 text-xs text-gray-400">
                ติ๊ก "ตัวกระตุ้น" = กด "+ เพิ่มในตะกร้า" บนอุปกรณ์นี้แล้วได้ทั้งชุดอัตโนมัติ
              </p>
            </div>
          )}

          <div className="md:col-span-2">
            <label className="block text-xs font-medium text-gray-600 mb-1">คำอธิบาย</label>
            <textarea rows={2} value={form.description} onChange={set('description')}
              className="w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-primary-500" />
          </div>

          <div className="md:col-span-2 flex gap-3 pt-2">
            <button type="button" onClick={onClose} className="flex-1 rounded-full border py-2 text-sm text-gray-600 hover:bg-gray-50">ยกเลิก</button>
            <button type="submit" disabled={loading}
              className="flex-1 rounded-full bg-primary-600 py-2 text-sm font-semibold text-white hover:bg-primary-700 disabled:opacity-50">
              {loading ? 'กำลังบันทึก…' : 'บันทึก'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ฟิลด์ที่แก้พร้อมกันหลายหน่วยได้อย่างปลอดภัย — ต้องตรงกับ EquipmentBulkUpdate ฝั่ง backend
// (ไม่รวม code/serial_number/quantity_* — ตั้งค่าเดียวกันทับหลายแถวพร้อมกันไม่มีความหมาย/ชน unique constraint
// ดู docstring EquipmentBulkUpdate ฝั่ง backend)
const BULK_FIELDS = [
  { key: 'name', label: 'ชื่ออุปกรณ์', type: 'text' },
  {
    key: 'item_type', label: 'ประเภท', type: 'select',
    options: [['durable', 'ครุภัณฑ์'], ['material', 'วัสดุ'], ['consumable', 'วัสดุสิ้นเปลือง']],
  },
  { key: 'category_ids', label: 'หมวดหมู่ (แทนที่ของเดิมทั้งหมด)', type: 'categories' },
  { key: 'location', label: 'สถานที่เก็บ', type: 'text', placeholder: 'เช่น 15312 ตู้A ชั้น3' },
  { key: 'description', label: 'คำอธิบาย', type: 'textarea' },
  { key: 'unit', label: 'หน่วย', type: 'text', placeholder: 'ชิ้น / ก้อน…' },
  { key: 'unit_value', label: 'มูลค่า/ชิ้น (บาท)', type: 'number' },
  { key: 'low_stock_threshold', label: 'แจ้งเตือนของใกล้หมด (จำนวน)', type: 'number' },
  {
    key: 'status', label: 'สถานะ', type: 'select',
    options: [['available', 'พร้อมให้ยืม'], ['unavailable', 'ไม่อนุญาตให้ยืม'],
      ['damaged', 'เสียหาย'], ['under_repair', 'ซ่อมอยู่'], ['retired', 'ปลดระวาง']],
  },
  { key: 'is_borrowable', label: 'อนุญาตให้ยืม', type: 'bool' },
]

// แก้ไขหลายหน่วยพร้อมกัน — แต่ละฟิลด์เป็น checkbox เปิดใช้ + input คู่กัน ไม่ติ๊ก = ไม่ส่งฟิลด์นั้น = ไม่แตะของเดิม
function BulkEditModal({ count, categories, onClose, onSave }) {
  const [enabled, setEnabled] = useState({})
  const [values, setValues] = useState({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const toggleField = (key) => setEnabled((e) => ({ ...e, [key]: !e[key] }))
  const setVal = (key, v) => setValues((s) => ({ ...s, [key]: v }))
  const toggleCategory = (id) => setVal(
    'category_ids',
    (values.category_ids ?? []).includes(id)
      ? values.category_ids.filter((c) => c !== id)
      : [...(values.category_ids ?? []), id],
  )

  const submit = async (e) => {
    e.preventDefault()
    if (enabled.category_ids && (values.category_ids ?? []).length === 0) {
      setError('เลือกหมวดหมู่อย่างน้อย 1 หมวด หรือไม่ติ๊กช่องนี้ถ้าไม่ต้องการแก้'); return
    }
    const update = {}
    for (const f of BULK_FIELDS) {
      if (!enabled[f.key]) continue
      const raw = values[f.key]
      update[f.key] = f.type === 'number' ? (raw === '' || raw == null ? null : Number(raw)) : raw
    }
    if (Object.keys(update).length === 0) { setError('เลือกอย่างน้อย 1 ฟิลด์ที่จะแก้ไข'); return }
    setError('')
    setLoading(true)
    try {
      await onSave(update)
    } catch (err) {
      setError(errMsg(err, 'บันทึกไม่สำเร็จ'))
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50 px-4 overflow-y-auto py-8">
      <div className="bg-white rounded-2xl p-6 w-full max-w-md shadow-xl">
        <h2 className="font-bold text-gray-800 mb-1">แก้ไขหลายรายการ</h2>
        <p className="mb-4 text-xs text-gray-500">แก้พร้อมกัน {count} รายการ — ติ๊กเฉพาะฟิลด์ที่จะแก้ ฟิลด์ที่ไม่ติ๊กจะไม่ถูกแตะ</p>
        {error && <p className="mb-3 text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>}
        <form onSubmit={submit} className="space-y-3">
          {BULK_FIELDS.map((f) => (
            <div key={f.key} className="rounded-lg border border-gray-200 p-2.5">
              <label className="flex items-center gap-2 text-xs font-medium text-gray-700 mb-1.5">
                <input type="checkbox" checked={!!enabled[f.key]} onChange={() => toggleField(f.key)} />
                {f.label}
              </label>
              {enabled[f.key] && f.type === 'textarea' && (
                <textarea rows={2} value={values[f.key] ?? ''} onChange={(e) => setVal(f.key, e.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-primary-500" />
              )}
              {enabled[f.key] && f.type === 'text' && (
                <input type="text" value={values[f.key] ?? ''} placeholder={f.placeholder} onChange={(e) => setVal(f.key, e.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
              )}
              {enabled[f.key] && f.type === 'number' && (
                <input type="number" step="0.01" value={values[f.key] ?? ''} onChange={(e) => setVal(f.key, e.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
              )}
              {enabled[f.key] && f.type === 'select' && (
                <select value={values[f.key] ?? f.options[0][0]} onChange={(e) => setVal(f.key, e.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500">
                  {f.options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
              )}
              {enabled[f.key] && f.type === 'bool' && (
                <select value={values[f.key] === false ? 'false' : 'true'} onChange={(e) => setVal(f.key, e.target.value === 'true')}
                  className="w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500">
                  <option value="true">ยืมได้</option>
                  <option value="false">ห้ามยืมออก (ของประจำห้อง)</option>
                </select>
              )}
              {enabled[f.key] && f.type === 'categories' && (
                <div className="flex flex-wrap gap-1.5 rounded-lg border border-gray-300 p-2 max-h-32 overflow-y-auto">
                  {categories.map((c) => {
                    const on = (values.category_ids ?? []).includes(c.id)
                    return (
                      <button type="button" key={c.id} onClick={() => toggleCategory(c.id)}
                        className={`rounded-full px-2.5 py-1 text-xs font-medium transition-colors ${
                          on ? 'bg-primary-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                        }`}>
                        {c.name}
                      </button>
                    )
                  })}
                </div>
              )}
            </div>
          ))}
          <div className="flex gap-3 pt-2">
            <button type="button" onClick={onClose} className="flex-1 rounded-full border py-2 text-sm text-gray-600 hover:bg-gray-50">ยกเลิก</button>
            <button type="submit" disabled={loading}
              className="flex-1 rounded-full bg-primary-600 py-2 text-sm font-semibold text-white hover:bg-primary-700 disabled:opacity-50">
              {loading ? 'กำลังบันทึก…' : `บันทึก (${count})`}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// เติมของเข้าคลัง (ซื้อเพิ่ม) — พิมพ์แค่จำนวนที่เพิ่ม ไม่ต้องคำนวณยอดรวมใหม่เอง (ต่างจากช่อง "จำนวนทั้งหมด"
// ในฟอร์มแก้ไขที่ต้องพิมพ์ยอดรวมทั้งหมด พิมพ์ผิดแล้วต่ำกว่าเดิมจะทำสต็อกหาย) backend ตัดสินเองว่าจะบวกเข้า
// แถวเดิม (ก้อน/สิ้นเปลือง) หรือสร้างแถวใหม่แยกรหัส (ครุภัณฑ์/วัสดุที่แยกรายชิ้นแล้ว)
function RestockModal({ name, onClose, onSave }) {
  const [count, setCount] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const submit = async (e) => {
    e.preventDefault()
    const n = Number(count)
    if (!Number.isInteger(n) || n <= 0) { setError('กรอกจำนวนที่ซื้อเพิ่มเป็นเลขจำนวนเต็มมากกว่า 0'); return }
    setError('')
    setLoading(true)
    try {
      await onSave(n)
    } catch (err) {
      setError(errMsg(err, 'เติมของไม่สำเร็จ'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50 px-4">
      <div className="bg-white rounded-2xl p-6 w-full max-w-sm shadow-xl">
        <h2 className="font-bold text-gray-800 mb-1">เพิ่มจำนวน</h2>
        <p className="text-sm text-gray-500 mb-4">{name}</p>
        {error && <p className="mb-3 text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>}
        <form onSubmit={submit}>
          <label className="block text-xs font-medium text-gray-600 mb-1">ซื้อเพิ่มกี่ชิ้น</label>
          <input type="number" min={1} step={1} autoFocus value={count} onChange={(e) => setCount(e.target.value)}
            placeholder="เช่น 7"
            className="w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
          <p className="mt-1 text-xs text-gray-400">ระบบจะบวกเข้ากับของเดิมให้เอง ไม่ต้องคำนวณยอดรวมใหม่เอง</p>
          <div className="flex gap-3 pt-4">
            <button type="button" onClick={onClose} className="flex-1 rounded-full border py-2 text-sm text-gray-600 hover:bg-gray-50">ยกเลิก</button>
            <button type="submit" disabled={loading}
              className="flex-1 rounded-full bg-emerald-600 py-2 text-sm font-semibold text-white hover:bg-emerald-700 disabled:opacity-50">
              {loading ? 'กำลังบันทึก…' : 'เพิ่ม'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default function EquipmentManagePage() {
  // เข้าถึงหน้านี้พร้อมกรองประเภท/สถานะได้ทันทีผ่าน query string เช่น /admin/equipment?status=low_stock
  // (ลิงก์จาก "ภาพรวมคลังอุปกรณ์"/การ์ดแจ้งเตือนใน dashboard ใช้ path นี้) — อ่านแค่ตอน mount ครั้งแรกพอ ไม่ sync สองทาง
  const [searchParams] = useSearchParams()
  const [data, setData] = useState({ items: [], total: 0 })
  const [categories, setCategories] = useState([])
  const [search, setSearch] = useState('')
  const [filterCategory, setFilterCategory] = useState('')
  const [filterType, setFilterType] = useState(searchParams.get('item_type') || '')
  const [filterStatus, setFilterStatus] = useState(searchParams.get('status') || '')
  const [page, setPage] = useState(1)
  const [modal, setModal] = useState(null) // null | 'create' | equipment object
  const [confirm, setConfirm] = useState(null) // { title, message, onConfirm }
  const [loading, setLoading] = useState(true)
  // เลือกหลายรายการ (checkbox) — เก็บ equipment_id จริง (แถวเดี่ยว หรือหน่วยย่อยที่กางกลุ่มดูแล้ว)
  const [selected, setSelected] = useState(() => new Set())
  const [showBulkEdit, setShowBulkEdit] = useState(false)
  const [bulkResult, setBulkResult] = useState(null) // { deleted, failed } — โชว์สรุปหลังลบหลายรายการ
  const [restock, setRestock] = useState(null) // { id, name, groupId } — เติมของ (ซื้อเพิ่ม)
  const [showCats, setShowCats] = useState(false)
  const [showDocs, setShowDocs] = useState(false)
  const [showImport, setShowImport] = useState(false)
  // ช่วงวันที่ default = เดือนนี้ (ต้นเดือน → วันนี้)
  const _today = new Date().toISOString().slice(0, 10)
  const [docRange, setDocRange] = useState({ from: _today.slice(0, 8) + '01', to: _today })

  const reloadCategories = () => equipmentApi.listCategories().then(setCategories).catch(() => {})

  // ยุบครุภัณฑ์รุ่นเดียวกันหลายหน่วยเป็นแถวเดียว (เหมือนหน้ายืมของนักศึกษา) — กางดูรายหน่วยได้ผ่าน expanded
  const load = () => {
    setLoading(true)
    equipmentApi.listGrouped({
      search: search || undefined,
      category_id: filterCategory || undefined,
      item_type: filterType || undefined,
      status: filterStatus || undefined,
      page, page_size: 15,
    }).then(setData).finally(() => setLoading(false))
  }

  useEffect(() => { reloadCategories() }, [])
  useEffect(() => { load() }, [search, filterCategory, filterType, filterStatus, page])
  // เปลี่ยนตัวกรอง/หน้า = แถวที่เห็นเปลี่ยนไป การเลือกเดิมอาจอ้างถึงแถวที่ไม่อยู่ในจอแล้ว เคลียร์กันสับสน
  useEffect(() => { setSelected(new Set()) }, [search, filterCategory, filterType, filterStatus, page])

  const toggleSelect = (id) => setSelected((prev) => {
    const next = new Set(prev)
    if (next.has(id)) next.delete(id); else next.add(id)
    return next
  })

  // ติ๊กที่แถวกลุ่ม (อุปกรณ์เก่าจากทะเบียนส่วนใหญ่ยุบรวมหลายหน่วยแบบนี้) = เลือกทุกหน่วยในกลุ่มทีเดียว
  // ไม่ต้องกด "ดูรายหน่วย" ไล่ติ๊กเองทีละชิ้นก่อน — โหลดรายหน่วยให้อัตโนมัติถ้ายังไม่เคยกางดู (เห็นเป็นโบนัสว่าเลือกอะไรไปบ้าง)
  const toggleSelectGroup = async (eq) => {
    let members = expanded[eq.id]
    if (!members) {
      const detail = await equipmentApi.getGrouped(eq.id)
      members = detail.members
      setExpanded((e) => ({ ...e, [eq.id]: members }))
    }
    const memberIds = members.map((m) => m.id)
    const allSelected = memberIds.length > 0 && memberIds.every((id) => selected.has(id))
    setSelected((prev) => {
      const next = new Set(prev)
      memberIds.forEach((id) => (allSelected ? next.delete(id) : next.add(id)))
      return next
    })
  }

  // หาชื่อ/รหัสมาโชว์ในสรุปผลลบหลายรายการ — ใช้ข้อมูลที่กำลังแสดงอยู่บนจอ (แถวบน + หน่วยย่อยที่กางอยู่)
  const labelFor = (id) => {
    const top = data.items.find((e) => e.id === id)
    if (top) return `${top.name} (${top.code})`
    for (const members of Object.values(expanded)) {
      const m = members.find((u) => u.id === id)
      if (m) return m.code
    }
    return id
  }

  // { [groupId]: EquipmentUnitSummary[] } — กลุ่มที่กำลังกางดูหน่วยย่อยอยู่
  const [expanded, setExpanded] = useState({})

  const toggleExpand = (groupId) => {
    if (expanded[groupId]) {
      setExpanded((e) => { const n = { ...e }; delete n[groupId]; return n })
      return
    }
    equipmentApi.getGrouped(groupId).then((detail) => setExpanded((e) => ({ ...e, [groupId]: detail.members })))
  }

  const refreshExpanded = (groupId) => {
    if (!(groupId in expanded)) return
    equipmentApi.getGrouped(groupId).then((detail) => setExpanded((e) => ({ ...e, [groupId]: detail.members })))
  }

  // แก้ไขหน่วยเดียวในกลุ่ม — ต้องโหลดข้อมูลเต็มก่อน (การ์ดกลุ่มมีแค่ฟิลด์สรุป)
  const editMember = (id) => { equipmentApi.get(id).then(setModal) }

  // ปลดระวาง: ถามเหตุผลด้วย prompt (ใช้ออกใบปลดระวาง/ร่างออก ภายหลัง) — ยกเลิกได้ถ้ากด Cancel
  // groupId: ถ้าปลดระวางหน่วยย่อยในกลุ่มที่กางอยู่ ต้อง refresh รายการหน่วยย่อยด้วย
  const retire = (id, name, groupId) => {
    const reason = window.prompt(`ปลดระวาง "${name}"\nระบุเหตุผล (เช่น ชำรุด/สูญหาย/หมดสภาพ):`, '')
    if (reason === null) return // กด Cancel
    setConfirm({
      title: 'ปลดระวางอุปกรณ์',
      message: `ปลดระวาง "${name}" ?\nเหตุผล: ${reason.trim() || '(ไม่ระบุ)'}\nอุปกรณ์จะไม่สามารถยืมได้อีก`,
      confirmLabel: 'ปลดระวาง',
      danger: true,
      onConfirm: async () => {
        setConfirm(null)
        try {
          await equipmentApi.retire(id, reason.trim())
          load()
          if (groupId) refreshExpanded(groupId)
        } catch (e) {
          alert(e.response?.data?.detail || 'ปลดระวางไม่สำเร็จ')
        }
      },
    })
  }

  // ดาวน์โหลด PDF ใบรับเข้าคลัง (receipt) / ใบปลดระวาง (disposal) ตามช่วงวันที่
  const downloadDoc = async (kind) => {
    if (!docRange.from || !docRange.to) { alert('กรุณาเลือกช่วงวันที่'); return }
    try {
      openPdf(await equipmentApi.stockDocument(kind, docRange.from, docRange.to))
    } catch (e) {
      alert(e.response?.data?.detail || 'ไม่สามารถสร้างเอกสารได้')
    }
  }

  const downloadRepairDoc = async () => {
    try {
      openPdf(await equipmentApi.repairDocument())
    } catch (e) {
      alert(e.response?.data?.detail || 'ไม่สามารถสร้างเอกสารได้')
    }
  }

  // แยกวัสดุก้อนเดียว (quantity_total>1) เป็นรายชิ้นคนละรหัส — ยืมจากรุ่นนี้จะแยกเป็นคนละรายการยืมอัตโนมัติหลังแยก
  const splitUnits = (id, name, count) => setConfirm({
    title: 'แยกเป็นรายชิ้น',
    message: `แยก "${name}" (${count} ชิ้น) ให้เป็นคนละรหัสทั้งหมด ${count} รายการ?\nยืมของจากรุ่นนี้จะแยกเป็นคนละรายการยืมโดยอัตโนมัติหลังแยกแล้ว (ทำครั้งเดียว ย้อนกลับไม่ได้)`,
    confirmLabel: 'แยกเป็นรายชิ้น',
    onConfirm: async () => {
      setConfirm(null)
      try {
        await equipmentApi.split(id)
        load()
      } catch (e) {
        alert(e.response?.data?.detail || 'แยกไม่สำเร็จ')
      }
    },
  })

  const deletePermanent = (id, name, groupId) => setConfirm({
    title: 'ลบอุปกรณ์ถาวร',
    message: `ลบ "${name}" ออกจากระบบถาวร?\n(ทำได้เฉพาะอุปกรณ์ที่ไม่มีประวัติการยืม)`,
    confirmLabel: 'ลบถาวร',
    danger: true,
    onConfirm: async () => {
      setConfirm(null)
      try {
        await equipmentApi.deletePermanent(id)
        load()
        if (groupId) refreshExpanded(groupId)
      } catch (e) {
        alert(e.response?.data?.detail || 'ลบไม่สำเร็จ')
      }
    },
  })

  // ลบถาวรหลายรายการที่เลือกไว้พร้อมกัน — best-effort: ชิ้นที่ลบไม่ได้ (เช่นยังไม่ปลดระวาง) โชว์เหตุผลแยก
  // ไม่บล็อกชิ้นอื่นที่เหลือ
  const bulkDeleteSelected = () => setConfirm({
    title: 'ลบอุปกรณ์ถาวรหลายรายการ',
    message: `ลบอุปกรณ์ที่เลือกไว้ ${selected.size} รายการออกจากระบบถาวร?\n`
      + 'ทำได้เฉพาะชิ้นที่ปลดระวางแล้วและไม่มีประวัติการยืมค้าง — ชิ้นที่ลบไม่ได้จะแสดงเหตุผลแยกให้เห็น ไม่กระทบชิ้นอื่น',
    confirmLabel: 'ลบถาวร',
    danger: true,
    onConfirm: async () => {
      setConfirm(null)
      try {
        const result = await equipmentApi.bulkDelete([...selected])
        setBulkResult({ title: 'ผลการลบถาวรหลายรายการ', succeeded: result.deleted, failed: result.failed })
        setSelected(new Set())
        load()
        Object.keys(expanded).forEach(refreshExpanded)
      } catch (e) {
        alert(e.response?.data?.detail || 'ลบไม่สำเร็จ')
      }
    },
  })

  // ปลดระวางหลายรายการที่เลือกไว้พร้อมกัน — เหตุผลเดียวกันใช้กับทุกชิ้น (เหมือน retire() เดี่ยว ถามด้วย prompt)
  // best-effort: ชิ้นที่ปลดระวางไม่ได้โชว์เหตุผลแยก ไม่บล็อกชิ้นอื่น
  const bulkRetireSelected = () => {
    const reason = window.prompt(`ปลดระวางอุปกรณ์ที่เลือกไว้ ${selected.size} รายการ\nระบุเหตุผล (เช่น ชำรุด/สูญหาย/หมดสภาพ):`, '')
    if (reason === null) return // กด Cancel
    setConfirm({
      title: 'ปลดระวางอุปกรณ์หลายรายการ',
      message: `ปลดระวางอุปกรณ์ที่เลือกไว้ ${selected.size} รายการ?\nเหตุผล: ${reason.trim() || '(ไม่ระบุ)'}\nอุปกรณ์จะไม่สามารถยืมได้อีก`,
      confirmLabel: 'ปลดระวาง',
      danger: true,
      onConfirm: async () => {
        setConfirm(null)
        try {
          const result = await equipmentApi.bulkRetire([...selected], reason.trim())
          setBulkResult({ title: 'ผลการปลดระวางหลายรายการ', succeeded: result.retired, failed: result.failed })
          setSelected(new Set())
          load()
          Object.keys(expanded).forEach(refreshExpanded)
        } catch (e) {
          alert(e.response?.data?.detail || 'ปลดระวางไม่สำเร็จ')
        }
      },
    })
  }

  const STATUS_STYLE = { available: 'text-green-600', borrowed: 'text-primary-600', under_repair: 'text-yellow-600', damaged: 'text-red-500', retired: 'text-gray-400', unavailable: 'text-gray-500' }
  const STATUS_LABEL = { available: 'พร้อม', borrowed: 'ถูกยืม', under_repair: 'ซ่อม', damaged: 'เสียหาย', retired: 'ปลดระวาง', unavailable: 'ไม่อนุญาตให้ยืม' }
  // equipment.status ฝั่ง backend คือสถานะ "ยืมได้ไหม" ของหน่วยเอง (available/damaged/...) ไม่ใช่ "ถูกยืมอยู่ไหม"
  // (ดู _apply_status_filter) — หน่วยที่ถูกยืมออกไปสถานะยังเป็น available เหมือนเดิม แค่ quantity_available ลดลง
  // เคยลอง derive "ถูกยืม" จาก quantity_available < quantity_total เฉยๆ แต่ผิด — ช่องว่างนั้นเกิดจากของ
  // เสีย/สูญหายที่คืนไปแล้ว (ไม่คืนสต็อก) ได้ด้วย ไม่ได้แปลว่ามีคนถือของอยู่จริงเสมอไป ต้องใช้ flag จริงจาก
  // backend (is_currently_borrowed มาจาก borrow_items ที่ยังไม่คืนจริง) แทน
  const unitDisplayStatus = (u) => (u.status === 'available' && u.is_currently_borrowed ? 'borrowed' : u.status)

  return (
    <div className="max-w-5xl mx-auto px-4 py-8">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-6">
        <h1 className="text-2xl font-light text-gray-800">จัดการอุปกรณ์</h1>
        <div className="flex flex-wrap gap-2">
          <button onClick={() => setShowDocs((v) => !v)}
            className="rounded-full border border-gray-300 px-4 py-2 text-sm font-medium text-gray-600 hover:bg-gray-50">
            เอกสารคลัง
          </button>
          <button onClick={() => setShowCats(true)}
            className="rounded-full border border-gray-300 px-4 py-2 text-sm font-medium text-gray-600 hover:bg-gray-50">
            จัดการหมวดหมู่
          </button>
          <button onClick={() => setShowImport(true)}
            className="rounded-full border border-primary-300 px-4 py-2 text-sm font-medium text-primary-700 hover:bg-primary-50">
            นำเข้าจากไฟล์ทะเบียน
          </button>
          <button onClick={() => setModal('create')}
            className="rounded-full bg-primary-600 px-4 py-2 text-sm font-semibold text-white hover:bg-primary-700">
            + เพิ่มอุปกรณ์
          </button>
        </div>
      </div>

      {showDocs && (
        <div className="mb-6 rounded-lg border border-gray-200 bg-gray-50 p-4">
          <h2 className="mb-1 text-sm font-bold text-gray-700">เอกสารคลัง (ร่างเข้า / ร่างออก)</h2>
          <p className="mb-3 text-xs text-gray-500">ออกใบรับเข้าคลัง/ใบปลดระวางเป็น PDF ตามช่วงวันที่ที่นำเข้า/ปลดระวาง</p>
          <div className="flex flex-wrap items-end gap-3">
            <label className="text-xs text-gray-600">
              จากวันที่
              <input type="date" value={docRange.from}
                onChange={(e) => setDocRange((r) => ({ ...r, from: e.target.value }))}
                className="mt-1 block rounded-lg border border-gray-300 px-3 py-2 text-sm" />
            </label>
            <label className="text-xs text-gray-600">
              ถึงวันที่
              <input type="date" value={docRange.to}
                onChange={(e) => setDocRange((r) => ({ ...r, to: e.target.value }))}
                className="mt-1 block rounded-lg border border-gray-300 px-3 py-2 text-sm" />
            </label>
            <button onClick={() => downloadDoc('receipt')}
              className="rounded-full bg-primary-600 px-4 py-2 text-sm font-semibold text-white hover:bg-primary-700">
              ใบรับเข้าคลัง (ร่างเข้า)
            </button>
            <button onClick={() => downloadDoc('disposal')}
              className="rounded-full bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700">
              ใบปลดระวาง (ร่างออก)
            </button>
          </div>
          <div className="mt-4 border-t border-gray-200 pt-3">
            <p className="mb-2 text-xs text-gray-500">
              บันทึกขออนุมัติซ่อมแซมครุภัณฑ์ — ออกจากครุภัณฑ์ที่สถานะชำรุด/กำลังซ่อมทั้งหมด (ลักษณะที่ชำรุดดึงจากตอนรับคืน)
            </p>
            <button onClick={downloadRepairDoc}
              className="rounded-full bg-amber-600 px-4 py-2 text-sm font-semibold text-white hover:bg-amber-700">
              ใบขออนุมัติซ่อมแซมครุภัณฑ์
            </button>
          </div>
        </div>
      )}

      <div className="flex flex-col sm:flex-row gap-3 mb-4">
        <input type="text" placeholder="ค้นหาชื่อหรือรหัสอุปกรณ์…" value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(1) }}
          className="flex-1 min-w-0 rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
        <select value={filterCategory} onChange={(e) => { setFilterCategory(e.target.value); setPage(1) }}
          className="w-full sm:w-44 shrink-0 rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500">
          <option value="">ทุกหมวดหมู่</option>
          {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <select value={filterType} onChange={(e) => { setFilterType(e.target.value); setPage(1) }}
          className="w-full sm:w-40 shrink-0 rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500">
          <option value="">ทุกประเภท</option>
          <option value="durable">ครุภัณฑ์</option>
          <option value="material">วัสดุ</option>
          <option value="consumable">วัสดุสิ้นเปลือง</option>
        </select>
        <select value={filterStatus} onChange={(e) => { setFilterStatus(e.target.value); setPage(1) }}
          className="w-full sm:w-40 shrink-0 rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500">
          <option value="">ทุกสถานะ</option>
          <option value="available">พร้อมให้ยืม</option>
          <option value="unavailable">ไม่อนุญาตให้ยืม</option>
          <option value="damaged">เสียหาย</option>
          <option value="under_repair">ซ่อมอยู่</option>
          <option value="retired">ปลดระวาง</option>
          {/* 2 ตัวนี้ derive จากเกณฑ์/ตารางอื่น ไม่ใช่ equipment.status ตรงๆ (ดู equipment_service._apply_status_filter)
              เดิมดูได้แค่กดเข้ามาจาก dashboard เฉยๆ ไม่มี filter ให้กรองต่อ */}
          <option value="low_stock">สต็อกต่ำ</option>
          <option value="borrowed">ถูกยืมอยู่</option>
        </select>
      </div>

      {selected.size > 0 && (
        <div className="mb-4 flex flex-wrap items-center gap-3 rounded-lg border border-primary-200 bg-primary-50 px-4 py-2.5">
          <span className="text-sm font-medium text-primary-800">เลือกอยู่ {selected.size} รายการ</span>
          <button onClick={() => setShowBulkEdit(true)}
            className="rounded-full border border-primary-300 bg-white px-3 py-1 text-xs font-medium text-primary-700 hover:bg-primary-100">
            แก้ไขหลายรายการ
          </button>
          <button onClick={bulkRetireSelected}
            className="rounded-full border border-orange-300 bg-white px-3 py-1 text-xs font-medium text-orange-600 hover:bg-orange-50">
            ปลดระวางที่เลือก ({selected.size})
          </button>
          <button onClick={bulkDeleteSelected}
            className="rounded-full bg-red-600 px-3 py-1 text-xs font-semibold text-white hover:bg-red-700">
            ลบถาวรที่เลือก ({selected.size})
          </button>
          <button onClick={() => setSelected(new Set())} className="text-xs text-gray-400 hover:underline">ยกเลิกการเลือก</button>
        </div>
      )}

      {loading ? (
        <p className="text-center text-gray-400 py-16">กำลังโหลด…</p>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                {['', 'รูป', 'รหัส', 'ชื่อ', 'หมวดหมู่', 'ประเภท', 'คงเหลือ', 'สถานะ', ''].map((h, i) => (
                  <th key={i} className="px-4 py-2.5 text-left text-xs font-semibold text-gray-500">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {data.items.map((eq) => {
                const grouped = eq.unit_count > 1
                const members = expanded[eq.id]
                return (
                  <Fragment key={eq.id}>
                    <tr className="hover:bg-gray-50">
                      <td className="px-4 py-2">
                        <input type="checkbox"
                          checked={grouped ? Boolean(members?.length) && members.every((m) => selected.has(m.id)) : selected.has(eq.id)}
                          onChange={() => (grouped ? toggleSelectGroup(eq) : toggleSelect(eq.id))} />
                      </td>
                      <td className="px-4 py-2">
                        {eq.image_url
                          ? <img src={imageSrc(eq.image_url)} alt="" className="w-10 h-10 rounded object-cover border border-gray-200" />
                          : <div title="ยังไม่มีรูป — ควรเพิ่มรูปให้ครบ"
                                 className="w-10 h-10 rounded bg-amber-50 border border-amber-300 flex items-center justify-center text-amber-400">🖼</div>}
                      </td>
                      <td className="px-4 py-2.5 font-mono text-xs text-gray-500">{eq.code}</td>
                      <td className="px-4 py-2.5 font-medium text-gray-800">
                        {eq.name}
                        {grouped && (
                          <button onClick={() => toggleExpand(eq.id)} className="ml-2 text-xs font-normal text-primary-600 hover:underline">
                            {members ? 'ซ่อนรายหน่วย ▲' : `${eq.unit_count} หน่วย ▾`}
                          </button>
                        )}
                        {/* กระจายอยู่มากกว่า 1 สถานที่ (เช่นแยกเป็นรายชิ้นแล้วย้ายบางชิ้น) — โชว์สรุปแยกตามสถานที่ */}
                        {eq.locations && eq.locations.length > 1 && (
                          <div className="mt-0.5 text-xs font-normal text-gray-400">
                            <LocationIcon /> {eq.locations.map((l) => `${l.location} (${l.count})`).join(' · ')}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-gray-500 text-xs">{(eq.categories ?? []).map((c) => c.name).join(', ') || '—'}</td>
                      <td className="px-4 py-2.5 text-gray-500">{{ durable: 'ครุภัณฑ์', material: 'วัสดุ', consumable: 'สิ้นเปลือง' }[eq.item_type] ?? eq.item_type}</td>
                      <td className="px-4 py-2.5 text-gray-600">{eq.quantity_available}/{eq.quantity_total} {eq.unit ?? ''}</td>
                      {/* การ์ดกลุ่มหลายหน่วย (grouped) สถานะ "available" มาจาก backend แปลว่ามีหน่วยว่างอย่างน้อย 1 ชิ้นอยู่แล้ว
                          (ดู _build_group_response) ไม่ derive ซ้ำตรงนี้ — derive เฉพาะแถวเดี่ยว 1 หน่วยที่ค่า quantity เป็นของหน่วยนั้นจริง */}
                      <td className={`px-4 py-2.5 font-medium ${STATUS_STYLE[grouped ? eq.status : unitDisplayStatus(eq)] ?? ''}`}>
                        {STATUS_LABEL[grouped ? eq.status : unitDisplayStatus(eq)] ?? eq.status}
                        {!eq.is_borrowable && <span className="ml-1 text-xs text-gray-500">· ของประจำห้อง</span>}
                        {!grouped && eq.holder && (
                          <div className="font-normal text-gray-400 text-xs">
                            {eq.holder.holder_name}{eq.holder.student_number ? ` (${eq.holder.student_number})` : ''}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-2.5">
                        {grouped ? (
                          <div className="flex gap-3">
                            <button onClick={() => toggleExpand(eq.id)} className="text-xs text-primary-600 hover:underline">
                              {members ? 'ปิด' : 'ดูรายหน่วย'}
                            </button>
                            <button onClick={() => setRestock({ id: eq.id, name: eq.name })} className="text-xs text-emerald-600 hover:underline">+ เพิ่มจำนวน</button>
                          </div>
                        ) : (
                          <div className="flex gap-3">
                            <button onClick={() => setModal(eq)} className="text-xs text-primary-600 hover:underline">แก้ไข</button>
                            <button onClick={() => setRestock({ id: eq.id, name: eq.name })} className="text-xs text-emerald-600 hover:underline">+ เพิ่มจำนวน</button>
                            {eq.item_type === 'material' && eq.unit_count === 1 && eq.quantity_total > 1 && eq.status !== 'retired' && (
                              <span className="inline-flex items-center gap-1">
                                <button onClick={() => splitUnits(eq.id, eq.name, eq.quantity_total)} className="text-xs text-purple-600 hover:underline">แยกเป็นรายชิ้น</button>
                                <Tooltip text={'แยกของที่เก็บเป็นแถวเดียวจำนวนรวม ให้เป็นรายชิ้น คนละรหัส — ทำแล้วยืมหลายชิ้นพร้อมกันจะแยกรายการให้อัตโนมัติ และแก้สถานที่เก็บทีละชิ้นได้ (ย้อนกลับไม่ได้)'} />
                              </span>
                            )}
                            {eq.status !== 'retired' && (
                              <button onClick={() => retire(eq.id, eq.name)} className="text-xs text-orange-500 hover:underline">ปลดระวาง</button>
                            )}
                            {eq.status === 'retired' && (
                              <button onClick={() => deletePermanent(eq.id, eq.name)} className="text-xs text-red-600 hover:underline font-medium">ลบถาวร</button>
                            )}
                          </div>
                        )}
                      </td>
                    </tr>

                    {grouped && members && members.map((u) => (
                      <tr key={u.id} className="bg-gray-50/60">
                        <td className="px-4 py-1.5">
                          <input type="checkbox" checked={selected.has(u.id)} onChange={() => toggleSelect(u.id)} />
                        </td>
                        <td className="px-4 py-1.5" />
                        <td className="px-4 py-1.5 pl-8 font-mono text-xs text-gray-500">{u.code}</td>
                        <td className="px-4 py-1.5 text-xs text-gray-400" colSpan={3}>
                          <LocationIcon /> {u.location || 'ไม่ระบุสถานที่'}
                          {u.serial_number && <span className="ml-2">· SN: {u.serial_number}</span>}
                        </td>
                        <td className="px-4 py-1.5 text-xs text-gray-500">{u.quantity_available}/{u.quantity_total}</td>
                        <td className={`px-4 py-1.5 text-xs font-medium ${STATUS_STYLE[unitDisplayStatus(u)] ?? ''}`}>
                          {STATUS_LABEL[unitDisplayStatus(u)] ?? u.status}
                          {u.holder && (
                            <div className="font-normal text-gray-400">
                              {u.holder.holder_name}{u.holder.student_number ? ` (${u.holder.student_number})` : ''}
                            </div>
                          )}
                        </td>
                        <td className="px-4 py-1.5">
                          <div className="flex gap-3">
                            <button onClick={() => editMember(u.id)} className="text-xs text-primary-600 hover:underline">แก้ไข</button>
                            {u.status !== 'retired' && (
                              <button onClick={() => retire(u.id, eq.name, eq.id)} className="text-xs text-orange-500 hover:underline">ปลดระวาง</button>
                            )}
                            {u.status === 'retired' && (
                              <button onClick={() => deletePermanent(u.id, eq.name, eq.id)} className="text-xs text-red-600 hover:underline font-medium">ลบถาวร</button>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
          {data.items.length === 0 && <p className="text-center text-gray-400 py-10">ไม่พบอุปกรณ์</p>}
        </div>
      )}

      <Pagination page={page} total={data.total} pageSize={15} onChange={setPage} />

      {modal && (
        <EquipmentModal
          initial={modal === 'create' ? null : modal}
          categories={categories}
          onClose={() => setModal(null)}
          onSave={() => { setModal(null); load(); Object.keys(expanded).forEach(refreshExpanded) }}
        />
      )}

      {restock && (
        <RestockModal
          name={restock.name}
          onClose={() => setRestock(null)}
          onSave={async (count) => {
            await equipmentApi.restock(restock.id, count)
            setRestock(null)
            load()
            Object.keys(expanded).forEach(refreshExpanded)
          }}
        />
      )}

      {confirm && (
        <ConfirmModal
          title={confirm.title}
          message={confirm.message}
          confirmLabel={confirm.confirmLabel}
          danger={confirm.danger}
          onConfirm={confirm.onConfirm}
          onCancel={() => setConfirm(null)}
        />
      )}

      {showBulkEdit && (
        <BulkEditModal
          count={selected.size}
          categories={categories}
          onClose={() => setShowBulkEdit(false)}
          onSave={async (update) => {
            await equipmentApi.bulkUpdate([...selected], update)
            setShowBulkEdit(false)
            setSelected(new Set())
            load()
            Object.keys(expanded).forEach(refreshExpanded)
          }}
        />
      )}

      {bulkResult && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50 px-4">
          <div className="bg-white rounded-2xl p-6 w-full max-w-md shadow-xl">
            <h2 className="font-bold text-gray-800 mb-3">{bulkResult.title}</h2>
            <p className="text-sm text-green-700 mb-2">สำเร็จ {bulkResult.succeeded.length} รายการ</p>
            {bulkResult.failed.length > 0 && (
              <div className="mb-3">
                <p className="text-sm text-red-600 mb-1">ไม่สำเร็จ {bulkResult.failed.length} รายการ</p>
                <ul className="max-h-48 overflow-y-auto space-y-1 rounded-lg bg-gray-50 p-2 text-xs text-gray-600">
                  {bulkResult.failed.map((f) => (
                    <li key={f.equipment_id}>{labelFor(f.equipment_id)} — {f.reason}</li>
                  ))}
                </ul>
              </div>
            )}
            <button onClick={() => setBulkResult(null)}
              className="mt-2 w-full rounded-full bg-primary-600 py-2 text-sm font-semibold text-white hover:bg-primary-700">
              ปิด
            </button>
          </div>
        </div>
      )}

      {showCats && (
        <CategoryModal
          categories={categories}
          onClose={() => { setShowCats(false); load() }}
          onChanged={reloadCategories}
        />
      )}

      {showImport && (
        <ImportModal
          categories={categories}
          onClose={() => setShowImport(false)}
          onDone={() => { setShowImport(false); reloadCategories(); load() }}
        />
      )}
    </div>
  )
}

const IMPORT_ACTION = {
  new: { label: 'เพิ่มใหม่', cls: 'bg-green-50 text-green-700', log: 'เพิ่มอุปกรณ์เข้าคลัง' },
  update: { label: 'อัปเดต', cls: 'bg-primary-50 text-primary-700', log: 'แก้ไขข้อมูลอุปกรณ์' },
  retire: { label: 'เสนอปลดระวาง', cls: 'bg-red-50 text-red-700', log: 'ปลดระวางอุปกรณ์' },
  unchanged: { label: 'ไม่เปลี่ยน', cls: 'bg-gray-50 text-gray-500', log: '—' },
}
const FIELD_LABEL = { name: 'ชื่อ', location: 'สถานที่', status: 'สถานะ', quantity_total: 'จำนวน', serial_number: 'SN' }
const IMPORT_STATUS = { available: 'ปกติ', damaged: 'ชำรุด', unavailable: 'สูญหาย/เสื่อมสภาพ', retired: 'ปลดระวาง', borrowed: 'ถูกยืม', under_repair: 'ซ่อม' }
const EDITABLE_STATUS = ['available', 'damaged', 'unavailable']
const ITEM_TYPES = [['durable', 'ครุภัณฑ์'], ['material', 'วัสดุใช้ซ้ำ'], ['consumable', 'วัสดุสิ้นเปลือง']]
const fmtVal = (field, v) => (field === 'status' ? (IMPORT_STATUS[v] ?? v) : (v ?? '—'))

// นำเข้าจากไฟล์ทะเบียน 3 จังหวะ: อัปโหลด → สรุปว่าไฟล์เปลี่ยนอะไร → ร่างเอกสาร (ตรวจ/แก้/ตัดออก) → บันทึกจริง
function ImportModal({ categories, onClose, onDone }) {
  const { user } = useAuthContext()
  const [step, setStep] = useState('upload') // upload | summary | draft
  const [file, setFile] = useState(null)
  const [meta, setMeta] = useState(null)     // { import_id, filename, summary, skipped }
  const [rows, setRows] = useState([])       // ร่างที่แก้ได้
  const [expanded, setExpanded] = useState(null) // code ของแถวที่กางแก้อยู่
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const upload = async () => {
    if (!file) return
    setBusy(true); setError('')
    try {
      const res = await equipmentApi.importPreview(file)
      setMeta(res)
      // retire ไม่ติ๊กมาให้เอง — ถ้าไฟล์เป็นทะเบียนบางส่วน ของที่ยังอยู่จะโดนปลดระวางทั้งดุ้น
      setRows(res.rows.filter((r) => r.action !== 'unchanged').map((r) => ({
        ...r,
        include: r.action !== 'retire',
        quantity: r.quantity_total ?? 1,
        unit: r.unit ?? '',
        // หมวดหมู่: ของใหม่ใช้ที่ระบบเดาจากชื่อ / ของเดิมปล่อยว่าง = ไม่แตะหมวดเดิมใน DB
        categories: r.action === 'new' && r.category ? [r.category] : [],
        description: '',
        image_urls: [],
        reason: '',
      })))
      setStep('summary')
    } catch (err) {
      setError(errMsg(err, 'อ่านไฟล์ไม่สำเร็จ'))
    } finally { setBusy(false) }
  }

  const patch = (code, changes) => setRows((rs) => rs.map((r) => (r.code === code ? { ...r, ...changes } : r)))

  const uploadImages = async (code, files) => {
    if (!files?.length) return
    setBusy(true); setError('')
    try {
      const res = await Promise.all([...files].map((f) => equipmentApi.uploadImage(f)))
      setRows((rs) => rs.map((r) => (r.code === code
        ? { ...r, image_urls: [...r.image_urls, ...res.map((x) => x.image_url)] } : r)))
    } catch (err) {
      setError(errMsg(err, 'อัปโหลดรูปไม่สำเร็จ'))
    } finally { setBusy(false) }
  }

  const selected = rows.filter((r) => r.include)

  const commit = async () => {
    setBusy(true); setError('')
    try {
      const applied = await equipmentApi.importCommit(meta.import_id, {
        filename: meta.filename,
        rows: selected.map((r) => ({
          code: r.code, action: r.action, name: r.name, location: r.location, status: r.status,
          item_type: r.item_type, quantity: Number(r.quantity) || 1, unit: r.unit || null,
          categories: r.categories, description: r.description || null,
          image_urls: r.image_urls, reason: r.reason || null,
          serial_number: r.serial_number || null,
        })),
      })
      alert(`บันทึกเข้าระบบแล้ว — เพิ่ม ${applied.new} · แก้ไข ${applied.update} · ปลดระวาง ${applied.retire}\n`
        + 'ออกใบรับเข้าคลัง/ใบปลดระวาง (PDF) ได้จากปุ่ม "เอกสารคลัง"')
      onDone()
    } catch (err) {
      setError(errMsg(err, 'บันทึกไม่สำเร็จ'))
      setBusy(false)
    }
  }

  const s = meta?.summary
  const today = new Date().toLocaleDateString('th-TH', { day: '2-digit', month: 'long', year: 'numeric' })
  const count = (a) => selected.filter((r) => r.action === a).length

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
      <div className="flex max-h-[92vh] w-full max-w-6xl flex-col rounded-xl bg-white">
        <div className="border-b border-gray-200 px-6 py-4">
          <h2 className="text-lg font-bold text-gray-800">
            {step === 'draft' ? 'ร่างเอกสารปรับปรุงคลัง — ตรวจก่อนบันทึก' : 'นำเข้าอุปกรณ์จากไฟล์ทะเบียน (Excel / รูปถ่าย / PDF)'}
          </h2>
          <p className="mt-0.5 text-xs text-gray-500">
            {step === 'draft'
              ? 'นี่คือรายการที่จะถูกบันทึกเข้าระบบและลง log — กด “แก้ไข” เพื่อเติมหมวดหมู่ รูป คำอธิบาย ประเภท/จำนวน ได้เหมือนเพิ่มทีละชิ้น'
              : 'ไฟล์ Excel: อ่านชีต “คณะเทคโนฯดิจิทัล”, “ครุภัณฑ์ที่ได้รับพระราชทาน” และ “วัสดุ” · รูปถ่าย/PDF ของทะเบียนวัสดุก็ได้ (โหมดทดลอง — อ่านด้วย OCR ต้องตรวจทุกแถวก่อนบันทึก)'}
          </p>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-4">
          {error && <p className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">{error}</p>}

          {step === 'upload' && (
            <div className="flex items-center gap-3 py-4">
              <input type="file" accept=".xlsx,.pdf,image/*" onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="flex-1 text-sm" />
              <button onClick={upload} disabled={!file || busy}
                className="rounded-full bg-primary-600 px-4 py-2 text-sm font-semibold text-white hover:bg-primary-700 disabled:opacity-50">
                {busy ? 'กำลังอ่านไฟล์…' : 'อ่านไฟล์'}
              </button>
            </div>
          )}

          {step === 'summary' && (
            <>
              <div className="mb-4 grid grid-cols-4 gap-2 text-center">
                {[['เพิ่มใหม่', s.new, 'text-green-700'], ['อัปเดต', s.update, 'text-primary-700'],
                  ['ไม่พบในไฟล์', s.retire, 'text-red-700'], ['ไม่เปลี่ยน', s.unchanged, 'text-gray-500']].map(([label, n, cls]) => (
                  <div key={label} className="rounded-lg border border-gray-200 py-2">
                    <p className={`text-xl font-bold ${cls}`}>{n}</p>
                    <p className="text-xs text-gray-500">{label}</p>
                  </div>
                ))}
              </div>

              {meta.skipped.length > 0 && (
                <p className="mb-3 rounded-lg bg-yellow-50 px-3 py-2 text-xs text-yellow-800">
                  ข้าม {meta.skipped.length} รายการที่ไม่มีเลขครุภัณฑ์/รหัสในไฟล์ (ต้องออกเลขก่อนจึงนำเข้าได้)
                </p>
              )}

              <div className="rounded-lg border border-gray-200">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-gray-50 text-left text-gray-500">
                    <tr>{['การกระทำ', 'รหัส', 'ชื่อ', 'รายละเอียดที่เปลี่ยน'].map((h) => (
                      <th key={h} className="px-3 py-2 font-medium">{h}</th>))}</tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {rows.length === 0 && (
                      <tr><td colSpan={4} className="px-3 py-6 text-center text-gray-400">ไฟล์นี้ตรงกับคลังทุกรายการ ไม่มีอะไรต้องเปลี่ยน</td></tr>
                    )}
                    {rows.map((r) => (
                      <tr key={r.code}>
                        <td className="px-3 py-2">
                          <span className={`rounded px-1.5 py-0.5 font-medium ${IMPORT_ACTION[r.action].cls}`}>{IMPORT_ACTION[r.action].label}</span>
                        </td>
                        <td className="px-3 py-2 font-mono text-gray-600">{r.code}</td>
                        <td className="px-3 py-2 text-gray-800">{r.name}</td>
                        <td className="px-3 py-2 text-gray-500">
                          {r.action === 'new' && `สถานะ ${IMPORT_STATUS[r.status] ?? r.status}${r.location ? ` · ${r.location}` : ''}${r.serial_number ? ` · SN: ${r.serial_number}` : ''}`}
                          {r.action === 'retire' && 'ไม่พบในไฟล์ทะเบียนฉบับนี้'}
                          {r.action === 'update' && Object.entries(r.changes).map(([f, [oldV, newV]]) => (
                            <div key={f}>{FIELD_LABEL[f] ?? f}: <span className="line-through">{fmtVal(f, oldV)}</span> → <span className="text-gray-800">{fmtVal(f, newV)}</span></div>
                          ))}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}

          {step === 'draft' && (
            <div className="rounded-lg border border-gray-300 p-5">
              {/* หัวเอกสาร — เหมือนใบรับเข้าคลังที่จะออกเป็น PDF หลังบันทึก */}
              <div className="mb-4 border-b border-dashed border-gray-300 pb-3 text-center">
                <p className="text-xs text-gray-500">สถาบันเทคโนโลยีจิตรลดา — คณะเทคโนโลยีดิจิทัล</p>
                <p className="text-base font-bold text-gray-800">บันทึกปรับปรุงคลังครุภัณฑ์/วัสดุ (ร่าง)</p>
                <p className="mt-1 text-xs text-gray-500">
                  วันที่ {today} · ผู้ทำรายการ {user?.full_name ?? '—'} · ที่มา: {meta.filename}
                </p>
              </div>

              <table className="w-full text-xs">
                <thead className="border-b border-gray-200 text-left text-gray-500">
                  <tr>
                    {['บันทึก', 'log ที่จะลงระบบ', 'รหัส', 'รายการ', 'ประเภท', 'จำนวน', 'สถานที่', 'สถานะ / เหตุผล', ''].map((h, i) => (
                      <th key={i} className="px-2 py-2 font-medium">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {rows.map((r) => {
                    const isRetire = r.action === 'retire'
                    const open = expanded === r.code
                    return (
                      <Fragment key={r.code}>
                        <tr className={r.include ? '' : 'opacity-40'}>
                          <td className="px-2 py-2">
                            <input type="checkbox" checked={r.include}
                              onChange={(e) => patch(r.code, { include: e.target.checked })} />
                          </td>
                          <td className="px-2 py-2">
                            <span className={`rounded px-1.5 py-0.5 font-medium ${IMPORT_ACTION[r.action].cls}`}>
                              {IMPORT_ACTION[r.action].log}
                            </span>
                          </td>
                          <td className="px-2 py-2 font-mono text-gray-600">{r.code}</td>
                          <td className="px-2 py-2">
                            {isRetire ? <span className="text-gray-700">{r.name}</span> : (
                              <input value={r.name} disabled={!r.include}
                                onChange={(e) => patch(r.code, { name: e.target.value })}
                                className="w-full min-w-40 rounded border border-gray-200 px-2 py-1" />
                            )}
                          </td>
                          <td className="px-2 py-2">
                            {isRetire ? <span className="text-gray-500">{ITEM_TYPES.find(([v]) => v === r.item_type)?.[1]}</span> : (
                              <select value={r.item_type} disabled={!r.include}
                                onChange={(e) => patch(r.code, { item_type: e.target.value })}
                                className="rounded border border-gray-200 bg-white px-1 py-1">
                                {ITEM_TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                              </select>
                            )}
                          </td>
                          <td className="px-2 py-2">
                            {isRetire ? <span className="text-gray-500">{r.quantity}</span> : (
                              <input type="number" min="1" value={r.quantity} disabled={!r.include || r.item_type === 'durable'}
                                onChange={(e) => patch(r.code, { quantity: e.target.value })}
                                className="w-16 rounded border border-gray-200 px-2 py-1 disabled:bg-gray-50" />
                            )}
                          </td>
                          <td className="px-2 py-2">
                            {isRetire ? <span className="text-gray-500">{r.location || '—'}</span> : (
                              <input value={r.location ?? ''} disabled={!r.include}
                                onChange={(e) => patch(r.code, { location: e.target.value || null })}
                                className="w-24 rounded border border-gray-200 px-2 py-1" />
                            )}
                          </td>
                          <td className="px-2 py-2">
                            {isRetire ? (
                              <input value={r.reason} disabled={!r.include}
                                placeholder="เหตุผลปลดระวาง (เช่น จำหน่ายออก)"
                                onChange={(e) => patch(r.code, { reason: e.target.value })}
                                className="w-48 rounded border border-gray-200 px-2 py-1" />
                            ) : (
                              <select value={r.status} disabled={!r.include}
                                onChange={(e) => patch(r.code, { status: e.target.value })}
                                className="rounded border border-gray-200 bg-white px-1 py-1">
                                {EDITABLE_STATUS.map((v) => <option key={v} value={v}>{IMPORT_STATUS[v]}</option>)}
                              </select>
                            )}
                          </td>
                          <td className="px-2 py-2">
                            {!isRetire && (
                              <button onClick={() => setExpanded(open ? null : r.code)} disabled={!r.include}
                                className="text-primary-600 hover:underline disabled:text-gray-300">
                                {open ? 'ปิด ▲' : 'แก้ไข ▾'}
                              </button>
                            )}
                          </td>
                        </tr>

                        {open && (
                          <tr className="bg-gray-50">
                            <td colSpan={9} className="px-4 py-3">
                              <div className="grid grid-cols-3 gap-4">
                                <div>
                                  <p className="mb-1 font-medium text-gray-600">หมวดหมู่</p>
                                  <div className="max-h-28 overflow-y-auto rounded border border-gray-200 bg-white p-2">
                                    {categories.map((c) => (
                                      <label key={c.id} className="flex items-center gap-1.5 py-0.5">
                                        <input type="checkbox" checked={r.categories.includes(c.name)}
                                          onChange={(e) => patch(r.code, {
                                            categories: e.target.checked
                                              ? [...r.categories, c.name]
                                              : r.categories.filter((n) => n !== c.name),
                                          })} />
                                        <span>{c.name}</span>
                                      </label>
                                    ))}
                                  </div>
                                  {r.categories.length === 0 && (
                                    <p className="mt-1 text-gray-400">
                                      {r.action === 'new' ? 'ยังไม่เลือก — จะเข้าหมวด “ไม่ระบุหมวดหมู่”' : 'ไม่เลือก = ใช้หมวดเดิมใน DB'}
                                    </p>
                                  )}
                                </div>

                                <div>
                                  <p className="mb-1 font-medium text-gray-600">คำอธิบาย</p>
                                  <textarea rows={3} value={r.description}
                                    onChange={(e) => patch(r.code, { description: e.target.value })}
                                    placeholder={r.action === 'update' ? 'เว้นว่าง = ไม่แก้คำอธิบายเดิม' : 'รายละเอียดเพิ่มเติม'}
                                    className="w-full rounded border border-gray-200 px-2 py-1" />
                                  {r.item_type !== 'durable' && (
                                    <label className="mt-2 block font-medium text-gray-600">
                                      หน่วยนับ
                                      <input value={r.unit} onChange={(e) => patch(r.code, { unit: e.target.value })}
                                        placeholder="เช่น ม้วน / ชิ้น / เมตร"
                                        className="mt-1 w-full rounded border border-gray-200 px-2 py-1 font-normal" />
                                    </label>
                                  )}
                                </div>

                                <div>
                                  <p className="mb-1 font-medium text-gray-600">รูปภาพ (รูปแรก = ปก)</p>
                                  {r.image_urls.length > 0 && (
                                    <div className="mb-2 flex flex-wrap gap-1">
                                      {r.image_urls.map((url) => (
                                        <div key={url} className="relative">
                                          <img src={imageSrc(url)} alt="" className="h-14 w-14 rounded border border-gray-200 object-cover" />
                                          <button onClick={() => patch(r.code, { image_urls: r.image_urls.filter((u) => u !== url) })}
                                            className="absolute -right-1 -top-1 h-4 w-4 rounded-full bg-red-600 text-[10px] leading-4 text-white">×</button>
                                        </div>
                                      ))}
                                    </div>
                                  )}
                                  <input type="file" accept="image/*" multiple
                                    onChange={(e) => uploadImages(r.code, e.target.files)}
                                    className="w-full text-[11px]" />
                                  {r.action === 'update' && <p className="mt-1 text-gray-400">ไม่อัปโหลด = ใช้รูปเดิม</p>}
                                </div>
                              </div>
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    )
                  })}
                </tbody>
              </table>

              <p className="mt-4 border-t border-dashed border-gray-300 pt-3 text-xs text-gray-500">
                จะบันทึกทั้งหมด {selected.length} รายการ — เพิ่ม {count('new')} · แก้ไข {count('update')} · ปลดระวาง {count('retire')}
                <span className="block">ทุกบรรทัดจะถูกลง audit log ในชื่อ {user?.full_name ?? '—'} และนำไปออกใบรับเข้าคลัง/ใบปลดระวาง (PDF) ได้</span>
              </p>
            </div>
          )}
        </div>

        <div className="flex justify-between gap-2 border-t border-gray-200 px-6 py-4">
          <button onClick={step === 'draft' ? () => setStep('summary') : onClose} disabled={busy}
            className="rounded-full border border-gray-300 px-4 py-2 text-sm text-gray-600 hover:bg-gray-50">
            {step === 'draft' ? '← กลับไปแก้' : 'ปิด'}
          </button>
          {step === 'summary' && (
            <button onClick={() => setStep('draft')} disabled={rows.length === 0}
              className="rounded-full bg-primary-600 px-4 py-2 text-sm font-semibold text-white hover:bg-primary-700 disabled:opacity-50">
              ตรวจร่างเอกสาร →
            </button>
          )}
          {step === 'draft' && (
            <button onClick={commit} disabled={busy || selected.length === 0}
              className="rounded-full bg-primary-600 px-4 py-2 text-sm font-semibold text-white hover:bg-primary-700 disabled:opacity-50">
              {busy ? 'กำลังบันทึก…' : `ยืนยันบันทึกเข้าระบบ (${selected.length})`}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

function CategoryModal({ categories, onClose, onChanged }) {
  const [newName, setNewName] = useState('')
  const [editing, setEditing] = useState(null) // { id, name }
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const run = async (fn) => {
    setError('')
    setBusy(true)
    try { await fn(); await onChanged() }
    catch (err) { setError(errMsg(err, 'ทำรายการไม่สำเร็จ')) }
    finally { setBusy(false) }
  }

  const add = (e) => {
    e.preventDefault()
    if (!newName.trim()) return
    run(async () => { await equipmentApi.createCategory({ name: newName.trim() }); setNewName('') })
  }
  const saveEdit = () => run(async () => {
    await equipmentApi.updateCategory(editing.id, { name: editing.name.trim() })
    setEditing(null)
  })
  const remove = (c) => run(() => equipmentApi.deleteCategory(c.id))

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50 px-4">
      <div className="bg-white rounded-2xl p-6 w-full max-w-md shadow-xl">
        <h2 className="font-bold text-gray-800 mb-4">จัดการหมวดหมู่</h2>
        {error && <p className="mb-3 text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>}

        <form onSubmit={add} className="flex gap-2 mb-4">
          <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="ชื่อหมวดหมู่ใหม่"
            className="flex-1 rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
          <button type="submit" disabled={busy}
            className="rounded-full bg-primary-600 px-4 text-sm font-semibold text-white hover:bg-primary-700 disabled:opacity-50">เพิ่ม</button>
        </form>

        <div className="max-h-72 overflow-y-auto divide-y divide-gray-100">
          {categories.map((c) => (
            <div key={c.id} className="flex items-center gap-2 py-2">
              {editing?.id === c.id ? (
                <>
                  <input value={editing.name} onChange={(e) => setEditing({ ...editing, name: e.target.value })}
                    className="flex-1 rounded-lg border border-gray-300 px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
                  <button onClick={saveEdit} disabled={busy} className="text-xs text-primary-600 hover:underline">บันทึก</button>
                  <button onClick={() => setEditing(null)} className="text-xs text-gray-400 hover:underline">ยกเลิก</button>
                </>
              ) : (
                <>
                  <span className="flex-1 text-sm text-gray-700">{c.name}</span>
                  <button onClick={() => setEditing({ id: c.id, name: c.name })} className="text-xs text-primary-600 hover:underline">แก้ไข</button>
                  <button onClick={() => remove(c)} disabled={busy} className="text-xs text-red-500 hover:underline">ลบ</button>
                </>
              )}
            </div>
          ))}
          {categories.length === 0 && <p className="text-center text-gray-400 py-6 text-sm">ยังไม่มีหมวดหมู่</p>}
        </div>

        <button onClick={onClose} className="mt-4 w-full rounded-full border py-2 text-sm text-gray-600 hover:bg-gray-50">ปิด</button>
      </div>
    </div>
  )
}
