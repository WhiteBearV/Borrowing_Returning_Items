import { Fragment, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { equipmentApi } from '../../api/equipmentApi.js'
import { settingsApi } from '../../api/settingsApi.js'
import { useAuthContext } from '../../context/AuthContext.jsx'
import { isSuperadmin } from '../../utils/role.js'
import ConfirmModal from '../../components/common/ConfirmModal.jsx'
import Pagination from '../../components/common/Pagination.jsx'
import Tooltip from '../../components/common/Tooltip.jsx'
import QrCodeModal from '../../components/equipment/QrCodeModal.jsx'
import AdjustStockModal from '../../components/equipment/AdjustStockModal.jsx'
import QualityAssessField from '../../components/equipment/QualityAssessField.jsx'
import BulkAdjustStockModal from '../../components/equipment/BulkAdjustStockModal.jsx'
import StatusBadge, { STATUS_LABEL } from '../../components/equipment/StatusBadge.jsx'
import EmptyState from '../../components/common/EmptyState.jsx'
import AuditTimeline from '../../components/audit/AuditTimeline.jsx'
import PartsPanel from '../../components/equipment/PartsPanel.jsx'
import { openPdf } from '../../utils/openPdf.js'
import { daysSinceTH, formatAge, formatDate, formatMoney, todayTH } from '../../utils/formatDate.js'
import DateInput from '../../components/common/DateInput.jsx'
import { downloadCsv, fetchAllPages } from '../../utils/csv.js'

const today = () => todayTH()

const TYPE_LABEL = { durable: 'ครุภัณฑ์', material: 'วัสดุใช้ซ้ำ', consumable: 'วัสดุสิ้นเปลือง' }

const EMPTY_FORM = { code: '', serial_number: '', name: '', manufacturer: '', model_number: '', category_ids: [], item_type: 'durable', description: '', location: '', unit: '', unit_value: '', acquired_at: '', useful_life_years: '', book_value_override: '', quantity_total: 1, image_urls: [], is_borrowable: true, low_stock_threshold: '' }

// แบ่งฟอร์มตาม "ความเสี่ยง/วงจรชีวิต" ไม่ใช่ "รายละเอียด vs อื่นๆ" (เฟส 8, feedback ข้อ 15)
// ข้อมูลประจำตัว = แก้ได้อิสระ · สถานะ = เป็น action ที่ต้องมีเหตุผล · ทะเบียน/การเงิน = กระทบตัวเลขย้อนหลัง
const FORM_TABS = [
  { key: 'identity', label: 'ข้อมูลประจำตัว' },
  { key: 'status', label: 'สถานะ & การใช้งาน' },
  { key: 'finance', label: 'ทะเบียน & การเงิน' },
]

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
      // ของที่เพิ่งเพิ่มเข้าระบบส่วนใหญ่คือของที่เพิ่งได้มา — เติมวันนี้ให้ก่อน แก้ได้ถ้าเป็นของเก่า
      : { ...EMPTY_FORM, acquired_at: today() },
  )
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [uploading, setUploading] = useState(false)
  const [tab, setTab] = useState('identity')
  const { user } = useAuthContext()
  // ตัวเลขทะเบียน/การเงินแก้ได้เฉพาะ superadmin ตอนแก้ไขของเดิม (backend กั้นด้วย — ดู FINANCE_FIELDS)
  // ตอนสร้างใหม่ผู้ดูแลคลังกรอกได้ตามปกติ เพราะของทุกชิ้นต้องมีราคา+วันที่ได้มาตั้งแต่รับเข้าทะเบียน
  const canEditFinance = !isEdit || isSuperadmin(user)

  // ค่าคุณภาพ (เฟส 10) — ปุ่ม "ประเมินคุณภาพ" เดี่ยว ๆ (ยิง API ทันที บังคับเหตุผล) แยกจากช่องประเมิน
  // ตอนซ่อมเสร็จ (ส่งไปพร้อม PATCH หลักตอนสถานะกลับเป็น available)
  const [defaultDrop, setDefaultDrop] = useState(2)
  const [showAssessDialog, setShowAssessDialog] = useState(false)
  const [assessValue, setAssessValue] = useState(null)
  const [assessReason, setAssessReason] = useState('')
  const [assessBusy, setAssessBusy] = useState(false)
  const [assessError, setAssessError] = useState('')
  const [qualityAfterRepair, setQualityAfterRepair] = useState(null)
  const [qualityReasonRepair, setQualityReasonRepair] = useState('')
  // ค่าคุณภาพที่แสดงในโมดัลนี้ — เก็บแยกจาก `initial` (props เดิมตอนเปิดโมดัล) เพื่อรีเฟรชได้หลังกดประเมิน
  // โดยไม่ต้องเรียก onSave() ของ parent (ซึ่งปิดโมดัล+โหลดใหม่ ทิ้งฟิลด์อื่นที่แก้ค้างอยู่ในฟอร์มเดียวกัน
  // ที่ยังไม่ได้กดบันทึกหลัก — แก้ตามรีวิวรอบ 3, MINOR-9)
  const [qualityInfo, setQualityInfo] = useState(() => (isEdit ? {
    current_quality: initial.current_quality,
    quality_baseline: initial.quality_baseline,
    quality_baseline_at: initial.quality_baseline_at,
    quality_age_drop: initial.quality_age_drop,
    quality_usage_drop: initial.quality_usage_drop,
    quality_needs_inspection: initial.quality_needs_inspection,
  } : null))

  useEffect(() => {
    if (!isEdit) return
    settingsApi.list().then((rows) => {
      const v = Number(rows.find((s) => s.key === 'quality_repair_default_drop')?.value)
      if (Number.isFinite(v)) setDefaultDrop(v)
    }).catch(() => {})
  }, [isEdit])

  const applyQuality = (eq) => setQualityInfo({
    current_quality: eq.current_quality,
    quality_baseline: eq.quality_baseline,
    quality_baseline_at: eq.quality_baseline_at,
    quality_age_drop: eq.quality_age_drop,
    quality_usage_drop: eq.quality_usage_drop,
    quality_needs_inspection: eq.quality_needs_inspection,
  })

  const submitAssess = async () => {
    if (!assessReason.trim() || assessValue == null) return
    setAssessBusy(true); setAssessError('')
    try {
      const updated = await equipmentApi.assessQuality(initial.id, assessValue, assessReason.trim())
      setShowAssessDialog(false)
      setAssessValue(null); setAssessReason('')
      // อัปเดตเฉพาะค่าคุณภาพที่แสดงผลในโมดัลนี้ (ไม่เรียก onSave() — ดูคอมเมนต์ตอนประกาศ qualityInfo ด้านบน)
      applyQuality(updated)
    } catch (err) {
      setAssessError(errMsg(err, 'ประเมินคุณภาพไม่สำเร็จ'))
    } finally {
      setAssessBusy(false)
    }
  }

  // สถานะเปลี่ยนออกจาก available เดิม → available ใหม่ (ซ่อมเสร็จ) — จุดเดียวกับ backend
  // update_equipment ที่รับ quality_after/quality_reason ไปพร้อม PATCH เดียวกัน
  const repairedToAvailable = isEdit && initial.status !== 'available' && form.status === 'available'

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
  // พิมพ์/วางรหัสครบ 15 หลัก (นับเฉพาะตัวเลข) ตอนเพิ่มใหม่ → เดาประเภทเป็น "ครุภัณฑ์" ให้อัตโนมัติ (แค่ค่าเริ่มต้น
  // แนะนำ ไม่ล็อก dropdown ยังกดเปลี่ยนเป็นวัสดุ/วัสดุสิ้นเปลืองได้ปกติ) — เฉพาะตอนสร้างใหม่ ไม่แตะของเดิมตอนแก้ไข
  const setCode = (e) => {
    const code = e.target.value
    setForm((f) => {
      const next = { ...f, code }
      // แปลงเข้า durable อัตโนมัติ ต้องเคลียร์ unit เดิม (ที่กรอกไว้ตอนยังเป็นวัสดุสิ้นเปลือง) ทิ้งเหมือนกับ
      // ตอนเปลี่ยน dropdown เอง (setItemType) ไม่งั้น unit ค้างที่ไม่มีความหมายกับครุภัณฑ์หลุดไปด้วย
      if (!isEdit && code.replace(/\D/g, '').length === 15) {
        next.item_type = 'durable'
        next.unit = ''
      }
      return next
    })
  }
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

  const statusChanged = isEdit && form.status !== initial.status

  // ฟิลด์บังคับอยู่คนละแท็บกัน → ตรวจเองแล้วพาไปแท็บที่ยังกรอกไม่ครบ (input ที่ไม่ได้ mount
  // จะไม่ถูก HTML validate ให้ ถ้าไม่ตรวจเองผู้ใช้จะเจอ 422 จาก backend โดยไม่รู้ว่าขาดอะไร)
  const missingField = () => {
    if (form.category_ids.length === 0) return ['identity', 'เลือกหมวดหมู่อย่างน้อย 1 หมวด']
    if (!isEdit && form.image_urls.length === 0) return ['identity', 'แนบรูปอุปกรณ์อย่างน้อย 1 รูป']
    if (!form.name?.trim()) return ['identity', 'กรอกชื่ออุปกรณ์']
    if (form.item_type !== 'consumable' && !form.code?.trim()) return ['identity', 'กรอกรหัสอุปกรณ์']
    if (!isEdit && !form.unit_value) return ['finance', 'กรอกมูลค่าแท้จริง / ราคาที่ซื้อ']
    if (!isEdit && !form.acquired_at) return ['finance', 'กรอกวันที่ได้มา']
    if (statusChanged && !form.status_reason?.trim()) return ['status', 'ระบุเหตุผลที่เปลี่ยนสถานะอุปกรณ์']
    return null
  }

  const submit = async (e) => {
    e.preventDefault()
    const missing = missingField()
    if (missing) { setTab(missing[0]); setError(missing[1]); return }
    // เทียบกับค่าตั้งต้นของฟอร์ม (initial) — ฟอร์มส่ง field คุณภาพทั้งก้อนซ้ำทุกครั้งที่บันทึก (เหมือน field
    // อื่นทั้งหมด) แต่ backend propagate 2 ฟิลด์นี้ไปทั้งรุ่นทุกครั้งที่ "มีอยู่ในคำขอ" ไม่ใช่แค่ตอนค่าเปลี่ยนจริง
    // ต้องกรองที่นี่ก่อนส่ง ไม่งั้นแก้แค่ location ของหน่วยเดียวก็ทำให้ backend ไป sync ทั้งรุ่นซ้ำทุกครั้ง
    // initial เป็น null ตอนเพิ่มใหม่ → ต้อง ?. (21 ก.ย. 69 เคย throw ตรงนี้ ปุ่มค้าง "กำลังบันทึก…" ตลอดไป
    // เพราะอยู่หลัง setLoading(true) แต่นอก try จึงไม่มี finally มาปลด — คำนวณก่อน setLoading กันซ้ำ)
    const qualityLifeYearsValue = form.quality_life_years === '' || form.quality_life_years == null
      ? null : Number(form.quality_life_years)
    const qualityTrackedChanged = !!form.quality_tracked !== !!initial?.quality_tracked
    const qualityLifeYearsChanged = qualityLifeYearsValue !== (initial?.quality_life_years ?? null)
    setError('')
    setLoading(true)
    try {
      // ตัด field คุณภาพออกจาก ...form ก่อนเลย — เดิม spread `...form` แบบไม่มีเงื่อนไขทำให้ conditional
      // spread ด้านล่าง (isEdit && qualityTrackedChanged ? {...} : {}) เป็น dead code จริง ๆ เพราะ ...form
      // ใส่ค่ามาก่อนหน้านั้นเสมออยู่แล้ว (initial ตอน isEdit มี quality_tracked/quality_life_years ติดมาด้วย)
      // ทำให้ save อะไรก็ตามในฟอร์มนี้ส่ง field คุณภาพไปทุกครั้งไม่ว่าจะเปลี่ยนจริงหรือไม่ — backend ก็ต้องไม่
      // พึ่งพาฝั่งนี้อยู่ดี (แก้คู่กับ MAJOR-1a ที่ backend) แต่ตัดออกจาก payload ที่ต้นทางด้วยให้ตรงกับ
      // คอมเมนต์ที่ตั้งใจไว้จริง ๆ (แก้ตามรีวิวรอบ 3, MAJOR-1c)
      const { quality_tracked: _formQualityTracked, quality_life_years: _formQualityLifeYears, ...formWithoutQuality } = form
      const payload = {
        ...formWithoutQuality,
        quantity_total: Number(form.quantity_total),
        // null (ไม่ใช่ undefined) เพื่อให้แก้ไขล้างค่าฟิลด์เดิมได้จริง (เช่น SN ที่กรอกผิด) — undefined ถูก
        // JSON.stringify ตัดคีย์ทิ้งไปเลย ฝั่ง backend (exclude_unset) จะเห็นเหมือนไม่ได้ส่งมา เลยล้างค่าไม่ได้
        description: form.description || null,
        serial_number: form.serial_number || null,
        location: form.location || null,
        unit: form.unit || null,
        unit_value: form.unit_value === '' || form.unit_value == null ? null : Number(form.unit_value),
        acquired_at: form.acquired_at || null,
        useful_life_years: form.useful_life_years === '' || form.useful_life_years == null ? null : Number(form.useful_life_years),
        // ส่ง null = ล้างค่าที่กรอกทับ กลับไปใช้มูลค่าที่ระบบคำนวณ (backend ตั้งใจให้ล้างได้ ต่างจาก unit_value)
        book_value_override: form.book_value_override === '' || form.book_value_override == null ? null : Number(form.book_value_override),
        image_urls: form.image_urls,
        manufacturer: form.manufacturer || null,
        model_number: form.model_number || null,
        low_stock_threshold: form.low_stock_threshold === '' || form.low_stock_threshold == null ? null : Number(form.low_stock_threshold),
        // ส่งเฉพาะตอนสถานะเปลี่ยนจริง — backend บังคับให้มีเหตุผลเฉพาะกรณีนั้น
        ...(statusChanged ? { status_reason: form.status_reason } : {}),
        // ค่าคุณภาพ (เฟส 10) — เปิด/ปิดติดตาม+อายุการใช้งาน ใช้กับทั้งรุ่นเสมอ (backend propagate เอง)
        // ส่งเฉพาะตอนแก้จริงเท่านั้น (เทียบกับค่าตั้งต้นของฟอร์ม) — ไม่งั้นทุกครั้งที่กดบันทึกฟอร์มนี้
        // (แม้ไม่ได้แตะแท็บ "สถานะ & การใช้งาน" เลย) จะสั่ง backend ไป sync ทั้งรุ่นซ้ำโดยไม่จำเป็น
        ...(isEdit && qualityTrackedChanged ? { quality_tracked: !!form.quality_tracked } : {}),
        ...(isEdit && qualityLifeYearsChanged ? { quality_life_years: qualityLifeYearsValue } : {}),
        // ซ่อมเสร็จกลับมาพร้อมใช้ — ประเมินคุณภาพใหม่พร้อมกันได้ (ไม่บังคับ)
        ...(repairedToAvailable && form.quality_tracked && qualityAfterRepair != null
          ? { quality_after: qualityAfterRepair, quality_reason: qualityReasonRepair || null } : {}),
      }
      if (isEdit) {
        await equipmentApi.update(initial.id, payload)
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
        <h2 className="font-bold text-gray-800 mb-3">{isEdit ? 'แก้ไขอุปกรณ์' : 'เพิ่มอุปกรณ์ใหม่'}</h2>
        {/* แยกแท็บตามความเสี่ยง — ฟอร์มเดิมเป็นกำแพงช่องกรอก 20 ช่องปนกันหมด (feedback ข้อ 15) */}
        <div className="flex gap-1 border-b border-gray-200 mb-4">
          {FORM_TABS.map((t) => (
            <button type="button" key={t.key} onClick={() => setTab(t.key)}
              className={`px-3 py-1.5 text-sm font-medium border-b-2 -mb-px transition-colors ${
                tab === t.key ? 'border-primary-600 text-primary-700' : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}>
              {t.label}
            </button>
          ))}
        </div>
        {error && <p className="mb-3 text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>}
        {/* ลำดับช่องตามทะเบียนพัสดุ/มาตรฐานสากล (Snipe-IT, ทะเบียนครุภัณฑ์ไทย): รหัส (ตัวระบุ) มาก่อนเสมอ
            แล้วค่อยชื่อที่คนอ่าน → ผู้ผลิต/รุ่น (ตัวตนของสินค้า) → SN (เฉพาะเครื่อง) → สถานที่
            ดู docs/naming-convention.md — คนกรอกจากเอกสารทะเบียนจะไล่ตามลำดับนี้พอดี ไม่ต้องกระโดดไปมา */}
        <form onSubmit={submit} className="grid grid-cols-1 md:grid-cols-2 gap-x-4 gap-y-3">
          {tab === 'identity' && <>
          {[
            { label: `รหัสอุปกรณ์${form.item_type === 'consumable' ? '' : ' *'}`, key: 'code',
              required: form.item_type !== 'consumable', disabled: false,
              placeholder: form.item_type === 'consumable' ? 'เว้นว่างได้ ระบบจะออกรหัสให้อัตโนมัติ' : undefined },
            { label: 'ชื่ออุปกรณ์ *', key: 'name', required: true,
              placeholder: 'เช่น เซ็นเซอร์อุณหภูมิและความชื้น DHT11',
              tip: 'ตั้งชื่อแบบ ประเภท + คุณสมบัติ + รุ่น เช่น «เซ็นเซอร์อุณหภูมิและความชื้น DHT11»\nไม่ใช่ «DHT11» เฉย ๆ — ไม่งั้นคนที่ไม่รู้จักรุ่นค้นหาไม่เจอ (ดู docs/naming-convention.md)' },
            { label: 'ผู้ผลิต', key: 'manufacturer', placeholder: 'เช่น Aosong, Dell (ไม่บังคับ)' },
            { label: 'รุ่น (Model)', key: 'model_number', placeholder: 'เช่น DHT11, Latitude 5400 (ไม่บังคับ)',
              tip: 'ชื่อรุ่นที่เหมือนกันทุกชิ้นของรุ่นนี้ — คนละอย่างกับ SN (ไม่ซ้ำรายชิ้น) และรหัสอุปกรณ์ (ระบบออกให้)\nกรอกไว้แล้วค้นด้วยชื่อรุ่นก็เจอ แม้ชื่ออุปกรณ์จะเป็นภาษาไทย' },
            { label: 'SN (Serial Number ผู้ผลิต)', key: 'serial_number', placeholder: 'เลขที่ผู้ผลิตติดมากับเครื่อง (ไม่บังคับ)',
              tip: 'เลขประจำเครื่องจากผู้ผลิต ไม่ซ้ำกันรายชิ้น — คนละอย่างกับรหัสอุปกรณ์ (ทะเบียนออกให้) และรุ่น (เหมือนกันทุกชิ้น)' },
            { label: 'สถานที่เก็บ', key: 'location', placeholder: 'เช่น 15312 ตู้A ชั้น3 (ไม่บังคับ)' },
          ].map(({ label, key, required, disabled, placeholder, tip }) => (
            <div key={key}>
              <label className="flex items-center gap-1.5 text-xs font-medium text-gray-600 mb-1">
                {label}
                {tip && <Tooltip text={tip} />}
              </label>
              <input type="text" required={required} disabled={disabled} value={form[key]} onChange={key === 'code' ? setCode : set(key)}
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

          <div className="md:col-span-2">
            <label className="block text-xs font-medium text-gray-600 mb-1">คำอธิบาย</label>
            <textarea rows={2} value={form.description} onChange={set('description')}
              className="w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-primary-500" />
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">ประเภท *</label>
            <select value={form.item_type} onChange={setItemType}
              className="w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:bg-gray-50">
              <option value="durable">ครุภัณฑ์</option>
              <option value="material">วัสดุใช้ซ้ำ</option>
              <option value="consumable">วัสดุสิ้นเปลือง</option>
            </select>
          </div>

          <div className={form.item_type === 'consumable' ? 'grid grid-cols-2 gap-3' : ''}>
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
          </div>

          </>}

          {tab === 'status' && <>
            {isEdit && <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">สถานะ</label>
              <select value={form.status} onChange={set('status')}
                className="w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500">
                <option value="available">พร้อมให้ยืม</option>
                <option value="unavailable">ไม่อนุญาตให้ยืม</option>
                <option value="damaged">เสียหาย</option>
                <option value="under_repair">ซ่อมอยู่</option>
                <option value="retired">ปลดระวาง</option>
              </select>
            </div>}
            {/* เปลี่ยนสถานะเป็น action ที่ต้องอธิบายได้ ไม่ใช่แค่แก้ค่าในฟอร์ม — เหตุผลลง audit (backend บังคับด้วย) */}
            {statusChanged && (
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">
                  เหตุผลที่เปลี่ยนสถานะ <span className="text-red-500">*</span>
                </label>
                <input type="text" value={form.status_reason ?? ''} onChange={set('status_reason')}
                  placeholder="เช่น ส่งซ่อมศูนย์บริการ / ชำรุดจากการใช้งาน"
                  className="w-full rounded-lg border border-amber-300 bg-amber-50 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400" />
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

          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">แจ้งเตือนของใกล้หมด (จำนวน)</label>
            <input type="number" min={0} value={form.low_stock_threshold ?? ''} onChange={set('low_stock_threshold')}
              placeholder="เว้นว่าง = ใช้ค่ากลางใน Settings"
              className="w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
          </div>

          {/* ค่าคุณภาพ (เฟส 10) — เปิดได้ทีละรุ่น สวิตช์นี้มีผลกับทุกหน่วยในรุ่นเดียวกัน (backend propagate เอง)
              ขอบเขตตามแผน: เฉพาะครุภัณฑ์/วัสดุใช้ซ้ำเท่านั้น — วัสดุสิ้นเปลืองหลายแถวมีชื่อซ้ำกันได้โดยตั้งใจ
              (คนละล็อต แยกกันจริงตาม _group_key) เปิดติดตามแล้ว propagate ตามชื่อจะไปแตะแถวที่ไม่เกี่ยวข้องกัน
              จริง ซ่อนสวิตช์นี้ไปเลยสำหรับ consumable (backend ก็ปฏิเสธ/เพิกเฉยด้วยอีกชั้น — แก้ตามรีวิวรอบ 3,
              MINOR-8) */}
          {isEdit && form.item_type !== 'consumable' && (
            <div className="md:col-span-2 rounded-lg border border-gray-200 p-3 space-y-3">
              <label className="flex items-start gap-2">
                <input type="checkbox" checked={!!form.quality_tracked} className="mt-0.5"
                  onChange={(e) => setForm({ ...form, quality_tracked: e.target.checked })} />
                <span className="text-xs text-gray-600">
                  <span className="font-medium text-gray-700">ติดตามค่าคุณภาพ (ทั้งรุ่น)</span>
                  <br />คุณภาพลดลงเองตามอายุและการถูกยืม ใช้จับคู่กับเวลาเรียนที่เหลือของผู้ยืมตอนจ่ายของ
                </span>
              </label>

              {form.quality_tracked && (
                <div className="space-y-2 pl-6">
                  <div className="flex items-center gap-2">
                    <label className="text-xs text-gray-600 shrink-0">อายุการใช้งานที่ใช้คิด (ปี)</label>
                    <input type="number" min={1} value={form.quality_life_years ?? ''}
                      onChange={set('quality_life_years')}
                      placeholder="เว้นว่าง = ใช้ค่ากลางใน Settings"
                      className="w-40 rounded-lg border border-gray-300 px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
                  </div>

                  <div className="rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-600">
                    {qualityInfo?.current_quality == null ? (
                      <p className="text-amber-600">ยังไม่ประเมิน</p>
                    ) : (
                      <>
                        <p className="font-medium text-gray-700">
                          คุณภาพปัจจุบัน {qualityInfo.current_quality}%
                          {qualityInfo.quality_needs_inspection && (
                            <span className="ml-2 rounded bg-rose-100 px-1.5 py-0.5 text-rose-700">ควรตรวจสภาพ</span>
                          )}
                        </p>
                        <p className="text-gray-400 mt-0.5">
                          ตั้งต้น {qualityInfo.quality_baseline}% เมื่อ {formatDate(qualityInfo.quality_baseline_at)}
                          {' '}· หักจากอายุ {qualityInfo.quality_age_drop} · หักจากการใช้งาน {qualityInfo.quality_usage_drop}
                        </p>
                      </>
                    )}
                  </div>

                  {/* ปุ่มประเมินยิง API ตรงไปที่แถวจริงใน DB (ไม่ผ่านฟอร์มนี้) — ต้องเช็คสถานะติดตามที่
                      "บันทึกแล้วจริง" (initial.quality_tracked) ไม่ใช่ form.quality_tracked ที่อาจเพิ่งติ๊ก
                      ในเซสชันนี้แต่ยังไม่ได้กดบันทึกหลัก ไม่งั้นกดแล้วเจอ 400 "รุ่นนี้ยังไม่เปิดติดตามคุณภาพ"
                      (แก้ตามรีวิวรอบ 3, MINOR-9) */}
                  {initial.quality_tracked && (!showAssessDialog ? (
                    <button type="button" onClick={() => { setShowAssessDialog(true); setAssessValue(null); setAssessReason(''); setAssessError('') }}
                      className="text-xs text-primary-600 hover:underline">+ ประเมินคุณภาพ</button>
                  ) : (
                    <div className="rounded-lg border border-primary-200 bg-primary-50/40 p-3 space-y-2">
                      <QualityAssessField
                        currentQuality={qualityInfo?.current_quality} defaultDrop={defaultDrop}
                        value={assessValue} onChange={setAssessValue} required
                      />
                      <input type="text" value={assessReason} onChange={(e) => setAssessReason(e.target.value)}
                        placeholder="เหตุผลที่ประเมิน (บังคับ)"
                        className="w-full rounded-lg border border-gray-300 px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
                      {assessError && <p className="text-xs text-rose-600">{assessError}</p>}
                      <div className="flex gap-2">
                        <button type="button" onClick={() => setShowAssessDialog(false)}
                          className="flex-1 rounded-full border border-gray-300 py-1.5 text-xs text-gray-600 hover:bg-gray-50">ยกเลิก</button>
                        <button type="button" onClick={submitAssess} disabled={assessBusy || !assessReason.trim() || assessValue == null}
                          className="flex-1 rounded-full bg-primary-600 py-1.5 text-xs font-medium text-white hover:bg-primary-700 disabled:opacity-50">
                          {assessBusy ? 'กำลังบันทึก…' : 'บันทึกการประเมิน'}
                        </button>
                      </div>
                    </div>
                  ))}

                  {/* ซ่อมเสร็จกลับมาพร้อมใช้ — เสนอประเมินพร้อมกันได้เลยในคำขอเดียว */}
                  {repairedToAvailable && (
                    <div className="rounded-lg border border-emerald-200 bg-emerald-50/50 p-3 space-y-2">
                      <p className="text-xs font-medium text-emerald-800">สถานะกลับมาพร้อมใช้ — ประเมินคุณภาพพร้อมกันได้ (ไม่บังคับ)</p>
                      <QualityAssessField
                        currentQuality={qualityInfo?.current_quality} defaultDrop={defaultDrop}
                        value={qualityAfterRepair} onChange={setQualityAfterRepair}
                      />
                      {qualityAfterRepair != null && (
                        <input type="text" value={qualityReasonRepair} onChange={(e) => setQualityReasonRepair(e.target.value)}
                          placeholder="เหตุผล เช่น ซ่อมเสร็จ เปลี่ยนจอใหม่ (ไม่บังคับ)"
                          className="w-full rounded-lg border border-gray-300 px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {isEdit && (
            // qualityTracked/currentQuality ต้องมาจากค่า "บันทึกแล้วจริง" เหมือนปุ่ม "+ ประเมินคุณภาพ" ด้านบน
            // (initial.quality_tracked ไม่ใช่ form.quality_tracked ที่อาจเพิ่งติ๊กในฟอร์มแต่ยังไม่กดบันทึกหลัก
            // — ติดตั้งชิ้นส่วนยิง API ตรงไปที่แถวจริง เช็คสถานะจริงจาก DB เหมือนกัน) และ qualityInfo?.current_quality
            // (ค่าที่รีเฟรชในโมดัลนี้ได้หลังกดประเมิน ไม่ใช่ initial.current_quality ที่ค้างค่าตอนเปิดโมดัลครั้งแรก
            // — แก้ตามรีวิวรอบ 4, M-f สอดคล้องกับ MINOR-9 รีวิวรอบ 3)
            <PartsPanel equipmentId={initial.id} equipmentValue={initial.unit_value}
              equipmentBookValue={initial.book_value}
              qualityTracked={!!initial.quality_tracked} currentQuality={qualityInfo?.current_quality}
              // ติดตั้งพร้อมประเมินใหม่ → ดึงค่าคุณภาพล่าสุด ไม่งั้นติดตั้งครั้งถัดไปเสนอค่าจากตัวเลขเก่า
              onQualityChanged={() => equipmentApi.get(initial.id).then(applyQuality).catch(() => {})} />
          )}

          {/* ชุดอุปกรณ์ถูกย้ายไปจัดการที่หน้า "ชุดอุปกรณ์" อย่างเดียว (8 ก.ย. 69) — มี 2 ทางเข้าที่แก้ของ
              เดียวกันแล้วสับสน และหน้าชุดอุปกรณ์เห็นภาพรวมทั้งชุดพร้อมตัวกระตุ้นได้ดีกว่าฟอร์มรายชิ้น */}
          </>}

          {tab === 'finance' && <>
            {!canEditFinance && (
              <p className="md:col-span-2 rounded-lg bg-amber-50 border border-amber-200 px-3 py-2 text-xs text-amber-800">
                ตัวเลขทะเบียน/การเงินแก้ได้เฉพาะ<b>ผู้ดูแลระบบสูงสุด</b> เพราะกระทบค่าเสื่อม มูลค่าในใบยืมเก่า
                และค่าเสียหายที่เรียกเก็บย้อนหลัง — ถ้าต้องแก้ ให้ยื่น "คำขอแก้ไขข้อมูล" พร้อมเหตุผล
              </p>
            )}
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">มูลค่าแท้จริง / ราคาที่ซื้อ (บาท) *</label>
              <input type="number" min={0} step="0.01" disabled={!canEditFinance}
                value={form.unit_value ?? ''} onChange={set('unit_value')} placeholder="เช่น 2000"
                className="w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:bg-gray-50 disabled:text-gray-500" />
            </div>
            <div>
              <label className="flex items-center gap-1.5 text-xs font-medium text-gray-600 mb-1">
                วันที่ได้มา *
                <Tooltip text={'วันที่ได้รับของเข้าทะเบียนจริง (คนละอย่างกับวันที่บันทึกเข้าระบบ)\nใช้คำนวณอายุอุปกรณ์และค่าเสื่อมราคา'} />
              </label>
              <DateInput type="date" disabled={!canEditFinance}
                value={(form.acquired_at ?? '').slice(0, 10)} onChange={set('acquired_at')}
                className="w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:bg-gray-50 disabled:text-gray-500" />
              {form.acquired_at && <p className="text-xs text-gray-400 mt-1">อายุ {formatAge(form.acquired_at)}</p>}
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">อายุการใช้งาน (ปี)</label>
              <input type="number" min={1} disabled={!canEditFinance}
                value={form.useful_life_years ?? ''} onChange={set('useful_life_years')}
                placeholder="เว้นว่าง = ใช้ค่ากลางใน Settings"
                className="w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:bg-gray-50 disabled:text-gray-500" />
            </div>
            <div>
              <label className="flex items-center gap-1.5 text-xs font-medium text-gray-600 mb-1">
                มูลค่าตามบัญชี (บาท)
                <Tooltip text={'ปกติระบบคำนวณให้เองแบบเส้นตรงจากราคาที่ซื้อ + วันที่ได้มา + อายุการใช้งาน\nกรอกช่องนี้เมื่อต้องการใช้ตัวเลขจากงานบัญชีแทน — ลบค่าออกเพื่อกลับไปใช้ค่าที่คำนวณ'} />
              </label>
              <input type="number" min={0} step="0.01" disabled={!canEditFinance}
                value={form.book_value_override ?? ''} onChange={set('book_value_override')}
                placeholder={isEdit && initial?.book_value != null ? `คำนวณได้ ${formatMoney(initial.book_value)}` : 'เว้นว่าง = ใช้ค่าที่คำนวณ'}
                className="w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:bg-gray-50 disabled:text-gray-500" />
            </div>
          </>}

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
// (ไม่รวม code/serial_number/quantity_*/รูป — ตั้งค่าเดียวกันทับหลายแถวพร้อมกันไม่มีความหมาย/ชน unique constraint
// ดู docstring EquipmentBulkUpdate ฝั่ง backend) · tab + ลำดับ ตรงกับฟอร์มแก้ไขรายชิ้น (FORM_TABS) เสมอ
// — สองฟอร์มนี้ต้องหน้าตา/ฟิลด์ไปทางเดียวกัน (21 ก.ย. 69 เคยต่างกันจนหาสวิตช์ติดตามคุณภาพในรายชิ้นไม่เจอ)
const BULK_FIELDS = [
  { key: 'name', tab: 'identity', label: 'ชื่ออุปกรณ์', type: 'text' },
  { key: 'manufacturer', tab: 'identity', label: 'ผู้ผลิต', type: 'text', placeholder: 'เช่น Aosong, Dell' },
  { key: 'model_number', tab: 'identity', label: 'รุ่น (Model)', type: 'text', placeholder: 'เช่น DHT11' },
  { key: 'location', tab: 'identity', label: 'สถานที่เก็บ', type: 'text', placeholder: 'เช่น 15312 ตู้A ชั้น3' },
  { key: 'category_ids', tab: 'identity', label: 'หมวดหมู่ (แทนที่ของเดิมทั้งหมด)', type: 'categories', full: true },
  { key: 'description', tab: 'identity', label: 'คำอธิบาย', type: 'textarea', full: true },
  {
    key: 'item_type', tab: 'identity', label: 'ประเภท', type: 'select',
    options: [['durable', 'ครุภัณฑ์'], ['material', 'วัสดุใช้ซ้ำ'], ['consumable', 'วัสดุสิ้นเปลือง']],
  },
  { key: 'unit', tab: 'identity', label: 'หน่วย (วัสดุสิ้นเปลือง)', type: 'text', placeholder: 'ชิ้น / ก้อน…' },
  {
    key: 'status', tab: 'status', label: 'สถานะ', type: 'select',
    options: [['available', 'พร้อมให้ยืม'], ['unavailable', 'ไม่อนุญาตให้ยืม'],
      ['damaged', 'เสียหาย'], ['under_repair', 'ซ่อมอยู่'], ['retired', 'ปลดระวาง']],
  },
  {
    key: 'is_borrowable', tab: 'status', label: 'การให้ยืม', type: 'bool',
    options: [[true, 'ยืมได้'], [false, 'ของประจำห้อง — ห้ามยืมออก']],
  },
  { key: 'low_stock_threshold', tab: 'status', label: 'แจ้งเตือนของใกล้หมด (จำนวน)', type: 'number' },
  {
    key: 'quality_tracked', tab: 'quality', label: 'ติดตามค่าคุณภาพ (ทั้งรุ่น)', type: 'bool',
    options: [[true, 'เปิดติดตามคุณภาพ'], [false, 'ปิดติดตามคุณภาพ']],
  },
  { key: 'quality_life_years', tab: 'quality', label: 'อายุการใช้งานที่ใช้คิดคุณภาพ (ปี)', type: 'number' },
  { key: 'unit_value', tab: 'finance', label: 'มูลค่าแท้จริง / ราคาที่ซื้อ (บาท)', type: 'number' },
  { key: 'acquired_at', tab: 'finance', label: 'วันที่ได้มา', type: 'date' },
  { key: 'useful_life_years', tab: 'finance', label: 'อายุการใช้งาน (ปี)', type: 'number' },
  { key: 'book_value_override', tab: 'finance', label: 'มูลค่าตามบัญชี (บาท)', type: 'number' },
]

// ประวัติการแก้ไขของอุปกรณ์ชิ้นเดียว — ตอบคำถามอาจารย์ว่า "ย้ายจากไหนไปไหน เมื่อไร ใครทำ"
function HistoryModal({ target, onClose }) {
  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50 px-4" onClick={onClose}>
      <div className="bg-white rounded-2xl p-6 w-full max-w-lg shadow-xl max-h-[80vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}>
        <h2 className="font-bold text-gray-800">ประวัติการเปลี่ยนแปลง</h2>
        <p className="mb-4 text-xs text-gray-500 font-mono">{target.code} · {target.name}</p>
        <AuditTimeline targetId={target.id} />
        <button onClick={onClose}
          className="mt-5 w-full rounded-full border py-2 text-sm text-gray-600 hover:bg-gray-50">ปิด</button>
      </div>
    </div>
  )
}

// แก้ไขหลายหน่วยพร้อมกัน — หน้าตาเดียวกับฟอร์มแก้ไขรายชิ้น (แท็บ/ลำดับ/2 คอลัมน์) แต่ทุกช่องมีสวิตช์ "แก้ไข"
// ไม่ติ๊ก = ช่องเป็นสีเทา "คงค่าเดิม" และไม่ส่งฟิลด์นั้น = ไม่แตะของเดิม · แสดงทุกช่องตลอด ติ๊กแล้วฟอร์มไม่ยืด
// ฟิลด์การเงินที่ผู้ดูแลคลังแก้ไม่ได้ (ต้องตรงกับ FINANCE_FIELDS ฝั่ง backend)
const FINANCE_BULK_KEYS = new Set(['unit_value', 'acquired_at', 'useful_life_years', 'book_value_override'])

function BulkEditModal({ count, categories, onClose, onSave }) {
  const { user: me } = useAuthContext()
  const canEditFinance = isSuperadmin(me)
  const [tab, setTab] = useState('identity')
  const [enabled, setEnabled] = useState({})
  const [values, setValues] = useState({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  // เปลี่ยนสถานะหลายรายการก็ต้องมีเหตุผลเหมือนแก้ทีละชิ้น (backend บังคับ) เหตุผลเดียวใช้กับทุกแถวที่เลือก
  const [statusReason, setStatusReason] = useState('')
  // ประเมินคุณภาพทั้งชุดพร้อมกัน (เฟส 10, ไม่บังคับ) — ข้ามแถวที่ไม่ได้เปิดติดตามอย่างเงียบ ๆ (backend เอง)
  const [assessGroup, setAssessGroup] = useState(false)
  const [qualityBaseline, setQualityBaseline] = useState('')
  const [qualityReason, setQualityReason] = useState('')

  const setVal = (key, v) => setValues((s) => ({ ...s, [key]: v }))
  // เปิดใช้ฟิลด์ select/bool ต้องตั้งค่าเริ่มต้นจริงลง values ทันที ไม่ปล่อยเป็น undefined รอ onChange
  // (undefined โดน JSON.stringify ตัดคีย์ทิ้งตอน submit → ติ๊กแล้วไม่ไปคลิก dropdown เอง กลายเป็นไม่ส่งฟิลด์
  // นี้ไปเลย แก้ไม่ได้ทั้งที่แอดมินคิดว่าติ๊กแล้ว — เจอบั๊กจริงกับ is_borrowable)
  const toggleField = (f) => {
    const turningOn = !enabled[f.key]
    setEnabled((e) => ({ ...e, [f.key]: turningOn }))
    if (turningOn && values[f.key] === undefined && f.options) setVal(f.key, f.options[0][0])
  }
  const toggleCategory = (id) => setVal(
    'category_ids',
    (values.category_ids ?? []).includes(id)
      ? values.category_ids.filter((c) => c !== id)
      : [...(values.category_ids ?? []), id],
  )

  const submit = async (e) => {
    e.preventDefault()
    if (enabled.category_ids && (values.category_ids ?? []).length === 0) {
      setTab('identity'); setError('เลือกหมวดหมู่อย่างน้อย 1 หมวด หรือไม่ติ๊กช่องนี้ถ้าไม่ต้องการแก้'); return
    }
    const update = {}
    for (const f of BULK_FIELDS) {
      if (!enabled[f.key]) continue
      const raw = values[f.key]
      update[f.key] = f.type === 'number' ? (raw === '' || raw == null ? null : Number(raw)) : raw
    }
    if (Object.keys(update).length === 0 && !assessGroup) { setError('ติ๊ก "แก้ไข" อย่างน้อย 1 ช่อง'); return }
    if (enabled.status && !statusReason.trim()) { setTab('status'); setError('ระบุเหตุผลที่เปลี่ยนสถานะอุปกรณ์'); return }
    if (assessGroup && (qualityBaseline === '' || !qualityReason.trim())) {
      setTab('status'); setError('กรอกค่าคุณภาพและเหตุผลให้ครบก่อนประเมินทั้งชุด'); return
    }
    setError('')
    setLoading(true)
    try {
      await onSave(
        update, statusReason.trim() || undefined,
        assessGroup ? Number(qualityBaseline) : undefined,
        assessGroup ? qualityReason.trim() : undefined,
      )
    } catch (err) {
      setError(errMsg(err, 'บันทึกไม่สำเร็จ'))
      setLoading(false)
    }
  }

  const inputCls = (on) => `w-full rounded-lg border px-3 py-1.5 text-sm focus:outline-none focus:ring-2
    focus:ring-primary-500 disabled:bg-gray-50 disabled:text-gray-400 disabled:cursor-not-allowed
    ${on ? 'border-primary-400 bg-primary-50/40' : 'border-gray-300'}`

  // render function (ไม่ใช่ component ย่อย) — component ที่ประกาศในนี้จะถูกสร้างใหม่ทุก render แล้ว input
  // หลุดโฟกัสทุกครั้งที่พิมพ์
  const control = (f, on) => {
    const value = values[f.key]
    if (f.type === 'categories') {
      return (
        <div className={`flex flex-wrap gap-1.5 rounded-lg border p-2 max-h-32 overflow-y-auto
          ${on ? 'border-primary-400 bg-primary-50/40' : 'border-gray-300 bg-gray-50 opacity-60'}`}>
          {categories.map((c) => (
            <button type="button" key={c.id} disabled={!on} onClick={() => toggleCategory(c.id)}
              className={`rounded-full px-2.5 py-1 text-xs font-medium transition-colors disabled:cursor-not-allowed ${
                (value ?? []).includes(c.id) ? 'bg-primary-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}>
              {c.name}
            </button>
          ))}
        </div>
      )
    }
    if (f.options) {
      return (
        <select disabled={!on} value={on ? String(value ?? f.options[0][0]) : ''}
          onChange={(e) => setVal(f.key, f.type === 'bool' ? e.target.value === 'true' : e.target.value)}
          className={`${inputCls(on)} bg-white`}>
          {!on && <option value="">— คงค่าเดิม —</option>}
          {f.options.map(([v, l]) => <option key={String(v)} value={String(v)}>{l}</option>)}
        </select>
      )
    }
    if (f.type === 'date') {
      return <DateInput type="date" disabled={!on} value={value ?? ''} onChange={(e) => setVal(f.key, e.target.value)}
        className={inputCls(on)} />
    }
    const common = {
      disabled: !on, value: value ?? '', onChange: (e) => setVal(f.key, e.target.value),
      placeholder: on ? f.placeholder : '— คงค่าเดิม —', className: inputCls(on),
    }
    if (f.type === 'textarea') return <textarea rows={2} {...common} className={`${common.className} resize-none`} />
    return <input type={f.type === 'number' ? 'number' : 'text'} {...(f.type === 'number' ? { step: '0.01', min: 0 } : {})} {...common} />
  }

  const field = (f) => {
    const on = !!enabled[f.key]
    const locked = FINANCE_BULK_KEYS.has(f.key) && !canEditFinance
    return (
      <div key={f.key} className={f.full ? 'md:col-span-2' : ''}>
        <label className="flex items-center justify-between gap-2 mb-1 text-xs font-medium text-gray-600">
          {f.label}
          <span className={`inline-flex items-center gap-1 font-normal ${on ? 'text-primary-700' : 'text-gray-400'}`}>
            <input type="checkbox" checked={on} disabled={locked} onChange={() => toggleField(f)} />
            แก้ไข
          </span>
        </label>
        {control(f, on)}
        {/* เปลี่ยนสถานะต้องอธิบายได้เสมอ (เฟส 8) — เหตุผลเดียวใช้กับทุกแถวที่เลือก เหมือนแก้รายชิ้น */}
        {f.key === 'status' && on && (
          <input type="text" value={statusReason} onChange={(e) => setStatusReason(e.target.value)}
            placeholder="เหตุผลที่เปลี่ยนสถานะ (บังคับ) เช่น ส่งซ่อมศูนย์บริการ"
            className="mt-1.5 w-full rounded-lg border border-amber-300 bg-amber-50 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400" />
        )}
      </div>
    )
  }
  const fieldsOf = (t) => BULK_FIELDS.filter((f) => f.tab === t).map(field)
  // จำนวนช่องที่ติ๊กในแต่ละแท็บ — แก้หลายแท็บพร้อมกันแล้วยังเห็นว่ากำลังจะเปลี่ยนอะไรบ้าง
  const tickedIn = (t) => BULK_FIELDS.filter((f) => enabled[f.key] &&
    (f.tab === t || (t === 'status' && f.tab === 'quality'))).length + (t === 'status' && assessGroup ? 1 : 0)

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50 px-4 overflow-y-auto py-8">
      {/* แถบสีอำพันด้านบน + ป้ายจำนวน = บอกให้รู้ทันทีว่าเป็นการแก้หลายรายการ ไม่ใช่ฟอร์มรายชิ้น */}
      <div className="bg-white rounded-2xl p-6 w-full max-w-2xl shadow-xl border-t-4 border-amber-400">
        <div className="flex items-center gap-2 mb-1">
          <h2 className="font-bold text-gray-800">แก้ไขหลายรายการ</h2>
          <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-800">{count} รายการ</span>
        </div>
        <p className="mb-3 text-xs text-gray-500">
          ติ๊ก <b>แก้ไข</b> เฉพาะช่องที่ต้องการเปลี่ยน — ค่าที่กรอกจะถูกตั้งให้<b>ทุกรายการที่เลือก</b>
          ช่องที่ไม่ติ๊กคงค่าเดิมของแต่ละรายการ
        </p>
        <div className="flex gap-1 border-b border-gray-200 mb-4">
          {FORM_TABS.map((t) => (
            <button type="button" key={t.key} onClick={() => setTab(t.key)}
              className={`px-3 py-1.5 text-sm font-medium border-b-2 -mb-px transition-colors ${
                tab === t.key ? 'border-primary-600 text-primary-700' : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}>
              {t.label}
              {tickedIn(t.key) > 0 && (
                <span className="ml-1.5 rounded-full bg-primary-600 px-1.5 py-0.5 text-[10px] text-white">{tickedIn(t.key)}</span>
              )}
            </button>
          ))}
        </div>
        {error && <p className="mb-3 text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>}
        <form onSubmit={submit} className="grid grid-cols-1 md:grid-cols-2 gap-x-4 gap-y-3">
          {tab === 'identity' && <>
            {fieldsOf('identity')}
            <p className="md:col-span-2 text-xs text-gray-400">
              รหัส · SN · จำนวน · รูปภาพ ไม่เหมือนกันรายชิ้น — แก้ได้จากปุ่ม "แก้ไข" ของแต่ละรายการ
            </p>
          </>}

          {tab === 'status' && <>
            {fieldsOf('status')}
            {/* ค่าคุณภาพ (เฟส 10) — กล่องเดียวกับฟอร์มรายชิ้น: เปิด/ปิดติดตาม + อายุที่ใช้คิด + ประเมินทั้งชุด
                ประเมินแยกจากฟิลด์ธรรมดาเพราะบังคับเหตุผลคู่กันเสมอ และข้ามแถวที่ไม่ได้เปิดติดตามอย่างเงียบ ๆ */}
            <div className="md:col-span-2 rounded-lg border border-gray-200 p-3 grid grid-cols-1 md:grid-cols-2 gap-x-4 gap-y-3">
              {fieldsOf('quality')}
              <div className="md:col-span-2">
                <label className="flex items-center gap-2 text-xs font-medium text-gray-600">
                  <input type="checkbox" checked={assessGroup} onChange={() => setAssessGroup((v) => !v)} />
                  ประเมินคุณภาพทั้งชุด (เฉพาะรายการที่เปิดติดตามคุณภาพอยู่)
                </label>
                <div className="mt-1.5 grid grid-cols-1 md:grid-cols-2 gap-2">
                  <input type="number" min={0} max={100} step="0.1" disabled={!assessGroup} value={qualityBaseline}
                    onChange={(e) => setQualityBaseline(e.target.value)}
                    placeholder={assessGroup ? 'ค่าคุณภาพใหม่ (%)' : '— ไม่ประเมิน —'} className={inputCls(assessGroup)} />
                  <input type="text" disabled={!assessGroup} value={qualityReason}
                    onChange={(e) => setQualityReason(e.target.value)}
                    placeholder={assessGroup ? 'เหตุผลที่ประเมิน (บังคับ)' : ''} className={inputCls(assessGroup)} />
                </div>
              </div>
            </div>
          </>}

          {tab === 'finance' && <>
            {!canEditFinance && (
              <p className="md:col-span-2 rounded-lg bg-amber-50 border border-amber-200 px-3 py-2 text-xs text-amber-800">
                ตัวเลขทะเบียน/การเงินแก้ได้เฉพาะ<b>ผู้ดูแลระบบสูงสุด</b> เพราะกระทบค่าเสื่อม มูลค่าในใบยืมเก่า
                และค่าเสียหายที่เรียกเก็บย้อนหลัง — ถ้าต้องแก้ ให้ยื่น "คำขอแก้ไขข้อมูล" พร้อมเหตุผล
              </p>
            )}
            {fieldsOf('finance')}
          </>}

          <div className="md:col-span-2 flex gap-3 pt-2">
            <button type="button" onClick={onClose} className="flex-1 rounded-full border py-2 text-sm text-gray-600 hover:bg-gray-50">ยกเลิก</button>
            <button type="submit" disabled={loading}
              className="flex-1 rounded-full bg-primary-600 py-2 text-sm font-semibold text-white hover:bg-primary-700 disabled:opacity-50">
              {loading ? 'กำลังบันทึก…' : `บันทึก (${count} รายการ)`}
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

// ป้ายคุณภาพต่อหน่วย (เฟส 10) — "คุณภาพ n%" / "ยังไม่ประเมิน" / "ควรตรวจสภาพ" ไม่แสดงอะไรเลยถ้ารุ่นนี้
// ไม่ได้เปิดติดตาม (eq.quality_tracked เป็น falsy) — ฟิลด์นี้มาจาก backend เฉพาะ viewer ที่เป็นเจ้าหน้าที่
// อยู่แล้ว (หน้านี้ require_admin ทั้งหน้า) จึงไม่ต้องกรองซ้ำฝั่งนี้
function QualityBadge({ eq }) {
  if (!eq?.quality_tracked) return null
  if (eq.current_quality == null) {
    return <div className="mt-0.5 text-[11px] text-amber-600">ยังไม่ประเมิน</div>
  }
  return (
    <div className={`mt-0.5 text-[11px] font-medium ${eq.quality_needs_inspection ? 'text-rose-600' : 'text-gray-400'}`}>
      คุณภาพ {eq.current_quality}%{eq.quality_needs_inspection && ' · ควรตรวจสภาพ'}
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
  const [qrTarget, setQrTarget] = useState(null) // { id, name } — โชว์ QR code ของหน่วยนี้
  const [adjustTarget, setAdjustTarget] = useState(null) // { id, name, available, total, groupId } — ปรับยอดคงเหลือ
  const [bulkAdjustStock, setBulkAdjustStock] = useState(false) // ปรับยอดคงเหลือหลายรายการพร้อมกัน (delta)
  const [showCats, setShowCats] = useState(false)
  const [showDocs, setShowDocs] = useState(false)
  const [showImport, setShowImport] = useState(false)
  // ช่วงวันที่ default = เดือนนี้ (ต้นเดือน → วันนี้)
  const _today = todayTH()
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

  // ส่งออกรายหน่วย (ไม่ใช่รายรุ่นแบบบนจอ) ตามตัวกรองปัจจุบัน — ฝ่ายพัสดุเอาไปเทียบทะเบียน/ทำรายงานต่อใน Excel
  const [exporting, setExporting] = useState(false)
  const exportCsv = async () => {
    setExporting(true)
    try {
      const rows = await fetchAllPages(equipmentApi.list, {
        search: search || undefined, category_id: filterCategory || undefined,
        item_type: filterType || undefined, status: filterStatus || undefined,
      })
      downloadCsv('equipment', [
        'รหัส', 'ชื่อ', 'ผู้ผลิต', 'รุ่น', 'Serial Number', 'สถานที่', 'ประเภท', 'หมวดหมู่', 'สถานะ',
        'จำนวนทั้งหมด', 'คงเหลือ', 'หน่วย', 'มูลค่าต่อหน่วย (บาท)', 'วันที่ได้มา', 'มูลค่าตามบัญชี (บาท)',
      ], rows.map((e) => [
        e.code, e.name, e.manufacturer, e.model_number, e.serial_number, e.location,
        TYPE_LABEL[e.item_type] ?? e.item_type, e.categories?.map((c) => c.name).join(', '),
        STATUS_LABEL[e.status] ?? e.status, e.quantity_total, e.quantity_available, e.unit,
        e.unit_value, e.acquired_at ? formatDate(e.acquired_at) : '', e.book_value,
      ]))
    } finally {
      setExporting(false)
    }
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
    let members = memberCache[eq.id]
    if (!members) {
      const detail = await equipmentApi.getGrouped(eq.id)
      members = cacheMembers(eq.id, detail.members)
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

  const [historyTarget, setHistoryTarget] = useState(null)
  // { [groupId]: EquipmentUnitSummary[] } — กลุ่มที่กำลัง "กางดู" หน่วยย่อยอยู่
  const [expanded, setExpanded] = useState({})
  // จำรายชื่อหน่วยของกลุ่มที่เคยโหลดแล้ว **ไม่ลบตอนยุบ** — สถานะติ๊กของแถวกลุ่มต้องรู้ว่ากลุ่มมีหน่วยอะไรบ้าง
  // เดิมอ่านจาก expanded ตรง ๆ พอยุบกลุ่มแล้ว checkbox เลยกลับไปเป็นไม่ติ๊ก ทั้งที่ยังเลือกอยู่จริง (บั๊กที่ผู้ใช้เจอ)
  const [memberCache, setMemberCache] = useState({})

  const cacheMembers = (groupId, members) => {
    setMemberCache((m) => ({ ...m, [groupId]: members }))
    return members
  }

  const toggleExpand = (groupId) => {
    if (expanded[groupId]) {
      setExpanded((e) => { const n = { ...e }; delete n[groupId]; return n })
      return
    }
    if (memberCache[groupId]) {
      setExpanded((e) => ({ ...e, [groupId]: memberCache[groupId] }))
    }
    equipmentApi.getGrouped(groupId).then((detail) => {
      cacheMembers(groupId, detail.members)
      setExpanded((e) => ({ ...e, [groupId]: detail.members }))
    })
  }

  const refreshExpanded = (groupId) => {
    if (!(groupId in expanded)) return
    equipmentApi.getGrouped(groupId).then((detail) => {
      cacheMembers(groupId, detail.members)
      setExpanded((e) => ({ ...e, [groupId]: detail.members }))
    })
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

  // equipment.status ฝั่ง backend คือสถานะ "ยืมได้ไหม" ของหน่วยเอง (available/damaged/...) ไม่ใช่ "ถูกยืมอยู่ไหม"
  // (ดู _apply_status_filter) — หน่วยที่ถูกยืมออกไปสถานะยังเป็น available เหมือนเดิม แค่ quantity_available ลดลง
  // เคยลอง derive "ถูกยืม" จาก quantity_available < quantity_total เฉยๆ แต่ผิด — ช่องว่างนั้นเกิดจากของ
  // เสีย/สูญหายที่คืนไปแล้ว (ไม่คืนสต็อก) ได้ด้วย ไม่ได้แปลว่ามีคนถือของอยู่จริงเสมอไป ต้องใช้ flag จริงจาก
  // backend (is_currently_borrowed มาจาก borrow_items ที่ยังไม่คืนจริง) แทน
  const unitDisplayStatus = (u) => (u.status === 'available' && u.is_currently_borrowed ? 'borrowed' : u.status)

  return (
    <div className="px-6 py-8">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-6">
        <div>
          <h1 className="text-2xl font-light text-gray-800">จัดการอุปกรณ์</h1>
          {/* ตารางยุบรุ่นเดียวกันเป็นแถวเดียว ตัวเลขแถวจึงไม่ใช่จำนวนของจริง — ต้องบอกจำนวน "ชิ้น" ควบคู่เสมอ
              ไม่งั้นอ่านว่า "187 รายการ" แล้วเข้าใจว่าคลังมีของแค่ 187 ชิ้น (8 ก.ย. 69) */}
          <p className="text-xs text-gray-500 mt-0.5">
            {data.summary
              ? <>
                  <b>{data.summary.pieces.toLocaleString('th-TH')} ชิ้น</b>
                  {' '}จาก {data.total.toLocaleString('th-TH')} รุ่น ·
                  {' '}ว่างให้ยืม {data.summary.available.toLocaleString('th-TH')} ชิ้น
                  {(search || filterCategory || filterType || filterStatus) && ' (ตามตัวกรองปัจจุบัน)'}
                </>
              : <>ทั้งหมด {data.total.toLocaleString('th-TH')} รุ่น</>}
          </p>
          {data.summary?.by_type?.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-1.5">
              {data.summary.by_type.map((t) => (
                <span key={t.item_type}
                  className="rounded-full bg-gray-100 px-2.5 py-0.5 text-xs text-gray-600">
                  {TYPE_LABEL[t.item_type] ?? t.item_type} {t.pieces.toLocaleString('th-TH')} ชิ้น
                  <span className="text-gray-400"> ({t.groups} รุ่น · ว่าง {t.available.toLocaleString('th-TH')})</span>
                </span>
              ))}
            </div>
          )}
          {/* สรุปคุณภาพ (เฟส 10) — นับจากรุ่นที่แสดงอยู่ในหน้านี้เท่านั้น (การ์ดยุบกลุ่มเห็นแค่หน่วยตัวแทน)
              ตัวเลขทั้งระบบดูที่ Dashboard ซึ่งคำนวณจากทุกหน่วยจริง */}
          {data.items?.some((c) => c.quality_tracked) && (
            <div className="flex flex-wrap gap-1.5 mt-1.5">
              {data.items.some((c) => c.quality_needs_inspection) && (
                <span className="rounded-full bg-rose-100 px-2.5 py-0.5 text-xs text-rose-700">
                  ควรตรวจสภาพ {data.items.filter((c) => c.quality_needs_inspection).length} รุ่น (ในหน้านี้)
                </span>
              )}
              {data.items.some((c) => c.quality_tracked && c.current_quality == null) && (
                <span className="rounded-full bg-amber-100 px-2.5 py-0.5 text-xs text-amber-700">
                  ยังไม่ประเมิน {data.items.filter((c) => c.quality_tracked && c.current_quality == null).length} รุ่น (ในหน้านี้)
                </span>
              )}
            </div>
          )}
        </div>
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
          <button onClick={exportCsv} disabled={exporting || data.total === 0}
            className="rounded-full border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50">
            {exporting ? 'กำลังสร้างไฟล์…' : 'ส่งออก CSV'}
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
              <DateInput type="date" value={docRange.from}
                onChange={(e) => setDocRange((r) => ({ ...r, from: e.target.value }))}
                className="mt-1 block rounded-lg border border-gray-300 px-3 py-2 text-sm" />
            </label>
            <label className="text-xs text-gray-600">
              ถึงวันที่
              <DateInput type="date" value={docRange.to}
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
          <option value="material">วัสดุใช้ซ้ำ</option>
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
          <option value="no_price">⚠ ยังไม่มีราคา</option>
          <option value="no_acquired_at">⚠ ยังไม่มีวันที่ได้มา</option>
        </select>
      </div>

      {selected.size > 0 && (
        <div className="mb-4 flex flex-wrap items-center gap-3 rounded-lg border border-primary-200 bg-primary-50 px-4 py-2.5">
          <span className="text-sm font-medium text-primary-800">เลือกอยู่ {selected.size} รายการ</span>
          <button onClick={() => setShowBulkEdit(true)}
            className="rounded-full border border-primary-300 bg-white px-3 py-1 text-xs font-medium text-primary-700 hover:bg-primary-100">
            แก้ไขหลายรายการ
          </button>
          <button onClick={() => setBulkAdjustStock(true)}
            className="rounded-full border border-rose-300 bg-white px-3 py-1 text-xs font-medium text-rose-600 hover:bg-rose-50">
            ปรับยอดคงเหลือ
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
        <EmptyState>กำลังโหลด…</EmptyState>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                {['', 'รูป', 'รหัส', 'ชื่อ', 'หมวดหมู่', 'ประเภท', 'คงเหลือ', 'อายุ', 'มูลค่า (ทุน/บัญชี)', 'สถานะ', ''].map((h, i) => (
                  <th key={i} className="px-4 py-2.5 text-left text-xs font-semibold text-gray-500">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {data.items.map((eq) => {
                const grouped = eq.unit_count > 1
                const members = memberCache[eq.id]   // ใช้ cache ไม่ใช่ expanded — ยุบกลุ่มแล้วติ๊กต้องไม่หาย
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
                            {expanded[eq.id] ? 'ซ่อนรายหน่วย ▲' : `${eq.unit_count} หน่วย ▾`}
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
                      <td className="px-4 py-2.5 text-gray-500">{TYPE_LABEL[eq.item_type] ?? eq.item_type}</td>
                      <td className="px-4 py-2.5 text-gray-600">{eq.quantity_available}/{eq.quantity_total} {eq.unit ?? ''}</td>
                      {/* การ์ดกลุ่มโชว์ค่าของหน่วยตัวแทน — หน่วยในกลุ่มอาจซื้อคนละล็อตคนละราคา กางดูรายหน่วยได้ */}
                      <td className="px-4 py-2.5 text-gray-500 text-xs whitespace-nowrap">{formatAge(eq.acquired_at)}</td>
                      <td className="px-4 py-2.5 text-xs whitespace-nowrap">
                        {eq.unit_value == null
                          ? <span className="text-rose-500">ยังไม่มีราคา</span>
                          : <span className="text-gray-600">{formatMoney(eq.unit_value)} / {formatMoney(eq.book_value)}</span>}
                      </td>
                      {/* การ์ดกลุ่มหลายหน่วย (grouped) สถานะ "available" มาจาก backend แปลว่ามีหน่วยว่างอย่างน้อย 1 ชิ้นอยู่แล้ว
                          (ดู _build_group_response) ไม่ derive ซ้ำตรงนี้ — derive เฉพาะแถวเดี่ยว 1 หน่วยที่ค่า quantity เป็นของหน่วยนั้นจริง */}
                      <td className="px-4 py-2.5">
                        <StatusBadge status={grouped ? eq.status : unitDisplayStatus(eq)} isBorrowable={eq.is_borrowable} />
                        {!grouped && <QualityBadge eq={eq} />}
                        {/* โชว์ผู้ยืมทุกคนที่ถืออยู่พร้อมกันได้ (holders มาจาก get_holders_map ที่คืนได้หลายคน
                            ต่อแถวเสมอ) — ไม่ gate ด้วย item_type: consumable ยืมพร้อมกันได้หลายคนคนละจำนวน
                            อยู่แล้ว แต่ material ที่ยังไม่แยกเป็นรายชิ้น (quantity_total > 1 อยู่แถวเดียว) ก็มี
                            หลายคนถือพร้อมกันได้เหมือนกัน ส่วน durable/หน่วยเดี่ยว holders จะมีแค่ 0-1 รายการ
                            พอดีอยู่แล้ว โค้ดเดียวจึงครอบคลุมทุกกรณีโดยไม่ต้องมี path เดี่ยวแยกอีก */}
                        {!grouped && eq.holders?.length > 0 && (
                          <div className="font-normal text-gray-400 text-xs">
                            {eq.holders.map((h, i) => {
                              // เกินกำหนดกี่วัน — แอดมินต้องเห็นตรงรายการอุปกรณ์เลยว่า "ชิ้นนี้ค้างอยู่ที่ใครและช้าแค่ไหน"
                              // ไม่ใช่ต้องไปไล่หาในหน้าประวัติการยืม (8 ก.ย. 69)
                              const late = h.due_date
                                ? daysSinceTH(h.due_date)
                                : 0
                              return (
                                <div key={i}>
                                  {h.holder_name}{h.student_number ? ` (${h.student_number})` : ''} ×{h.quantity}
                                  {late > 0 ? (
                                    <span className="ml-1 font-medium text-red-600">· เกินกำหนด {late} วัน</span>
                                  ) : h.due_date && (
                                    <span className="ml-1">· คืน {formatDate(h.due_date)}</span>
                                  )}
                                </div>
                              )
                            })}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-2.5">
                        {grouped ? (
                          <div className="flex gap-3">
                            <button onClick={() => toggleExpand(eq.id)} className="text-xs text-primary-600 hover:underline">
                              {expanded[eq.id] ? 'ปิด' : 'ดูรายหน่วย'}
                            </button>
                            <button onClick={() => setRestock({ id: eq.id, name: eq.name })} className="text-xs text-emerald-600 hover:underline">+ เพิ่มจำนวน</button>
                          </div>
                        ) : (
                          <div className="flex gap-3">
                            <button onClick={() => setModal(eq)} className="text-xs text-primary-600 hover:underline">แก้ไข</button>
                            <button onClick={() => setQrTarget({ id: eq.id, name: eq.name })} className="text-xs text-gray-500 hover:underline">QR</button>
                            <button onClick={() => setHistoryTarget({ id: eq.id, name: eq.name, code: eq.code })} className="text-xs text-gray-500 hover:underline">ประวัติ</button>
                            <button onClick={() => setRestock({ id: eq.id, name: eq.name })} className="text-xs text-emerald-600 hover:underline">+ เพิ่มจำนวน</button>
                            <button onClick={() => setAdjustTarget({ id: eq.id, name: eq.name, available: eq.quantity_available, total: eq.quantity_total })} className="text-xs text-rose-600 hover:underline">ปรับยอดคงเหลือ</button>
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

                    {grouped && expanded[eq.id]?.map((u) => (
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
                        {/* หน่วยในกลุ่มเดียวกันซื้อคนละล็อตคนละราคาได้ — ต้องเห็นอายุ/มูลค่าแยกรายหน่วย */}
                        <td className="px-4 py-1.5 text-xs text-gray-400 whitespace-nowrap">{formatAge(u.acquired_at)}</td>
                        <td className="px-4 py-1.5 text-xs whitespace-nowrap">
                          {u.unit_value == null
                            ? <span className="text-rose-500">ยังไม่มีราคา</span>
                            : <span className="text-gray-400">{formatMoney(u.unit_value)} / {formatMoney(u.book_value)}</span>}
                        </td>
                        <td className="px-4 py-1.5">
                          <StatusBadge status={unitDisplayStatus(u)} isBorrowable={u.is_borrowable} />
                          <QualityBadge eq={u} />
                          {u.holder && (
                            <div className="font-normal text-gray-400">
                              {u.holder.holder_name}{u.holder.student_number ? ` (${u.holder.student_number})` : ''}
                            </div>
                          )}
                        </td>
                        <td className="px-4 py-1.5">
                          <div className="flex gap-3">
                            <button onClick={() => editMember(u.id)} className="text-xs text-primary-600 hover:underline">แก้ไข</button>
                            <button onClick={() => setQrTarget({ id: u.id, name: eq.name })} className="text-xs text-gray-500 hover:underline">QR</button>
                            <button onClick={() => setHistoryTarget({ id: u.id, name: eq.name, code: u.code })} className="text-xs text-gray-500 hover:underline">ประวัติ</button>
                            <button onClick={() => setAdjustTarget({ id: u.id, name: eq.name, available: u.quantity_available, total: u.quantity_total, groupId: eq.id })} className="text-xs text-rose-600 hover:underline">ปรับยอดคงเหลือ</button>
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
          {data.items.length === 0 && <EmptyState className="py-10">ไม่พบอุปกรณ์</EmptyState>}
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

      {historyTarget && (
        <HistoryModal target={historyTarget} onClose={() => setHistoryTarget(null)} />
      )}
      {qrTarget && (
        <QrCodeModal id={qrTarget.id} name={qrTarget.name} onClose={() => setQrTarget(null)} />
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

      {adjustTarget && (
        <AdjustStockModal
          id={adjustTarget.id}
          name={adjustTarget.name}
          currentAvailable={adjustTarget.available}
          currentTotal={adjustTarget.total}
          onClose={() => setAdjustTarget(null)}
          onSave={async (newAvailable, reason, photoUrls) => {
            await equipmentApi.adjustStock(adjustTarget.id, newAvailable, reason, photoUrls)
            const groupId = adjustTarget.groupId
            setAdjustTarget(null)
            load()
            if (groupId) refreshExpanded(groupId)
          }}
        />
      )}

      {bulkAdjustStock && (
        <BulkAdjustStockModal
          count={selected.size}
          onClose={() => setBulkAdjustStock(false)}
          onSave={async (delta, reason) => {
            const result = await equipmentApi.bulkAdjustStock([...selected], delta, reason)
            setBulkAdjustStock(false)
            setSelected(new Set())
            // id ที่ไม่มีจริงถูกข้ามแบบ best-effort (ดู BulkAdjustStockResult.failed ฝั่ง backend) — โชว์สรุป
            // เหมือน bulk-delete/bulk-retire/bulk-update ให้รู้ว่าแถวไหนไม่ผ่านบ้าง ไม่ใช่แค่เงียบ ๆ หายไป
            if (result.failed?.length > 0) {
              setBulkResult({ title: 'ผลการปรับยอดคงเหลือหลายรายการ', succeeded: result.updated.map((u) => u.id), failed: result.failed })
            }
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
          onSave={async (update, statusReason, qualityBaseline, qualityReason) => {
            const result = await equipmentApi.bulkUpdate(
              [...selected], update, statusReason, qualityBaseline, qualityReason)
            setShowBulkEdit(false)
            setSelected(new Set())
            // เปลี่ยนเข้า durable ที่รหัสไม่ครบ 15 หลักถูกข้ามแบบ best-effort (ดู BulkUpdateResult.failed ฝั่ง
            // backend) — โชว์สรุปเหมือน bulk-delete/bulk-retire ให้รู้ว่าแถวไหน/รหัสอะไรไม่ผ่านบ้าง
            if (result.failed?.length > 0) {
              setBulkResult({ title: 'ผลการแก้ไขหลายรายการ', succeeded: result.updated.map((u) => u.id), failed: result.failed })
            }
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
  const today = formatDate(todayTH())
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
