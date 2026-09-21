import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { borrowApi } from '../../api/borrowApi.js'
import { useCart } from '../../context/CartContext.jsx'
import { openPdf } from '../../utils/openPdf.js'
import Tooltip from '../../components/common/Tooltip.jsx'
import DateInput from '../../components/common/DateInput.jsx'
import { todayTH } from '../../utils/formatDate.js'

// วัตถุประสงค์สำเร็จรูป — กดแล้วเติมทั้งข้อความและวันคืนโดยประมาณให้ แต่ผู้ใช้ยังแก้วันเองได้ก่อนส่ง
// ponytail: const ในไฟล์นี้พอ ยังไม่ต้องทำเป็น setting ให้แอดมินแก้ ถ้าอาจารย์อยากแก้เองค่อยย้ายเข้า settings
const PURPOSE_PRESETS = [
  { label: 'ทำโปรเจกต์จบ / ปริญญานิพนธ์', days: 60 },
  { label: 'งานในรายวิชา', days: 14 },
  { label: 'งานวิจัย / ผู้ช่วยวิจัย', days: 90 },
  { label: 'กิจกรรม / ชมรม', days: 7 },
  { label: 'อื่น ๆ (ระบุเอง)', days: null },  // ไม่เติมวันให้ ผู้ใช้เลือกเอง
]
const OTHER_PURPOSE = PURPOSE_PRESETS[PURPOSE_PRESETS.length - 1].label

const tomorrow = () => todayTH(1)
const daysFromToday = (n) => todayTH(n)
// กันพิมพ์วันที่เพี้ยน (เช่น อีก 100 ปี) — ต้องตรงกับ MAX_REQUESTED_DUE_DATE_YEARS ฝั่ง backend
const maxDueDate = () => todayTH(365 * 3)  // backend: date.today() + timedelta(days=365 * 3)

export default function BorrowRequestPage() {
  const navigate = useNavigate()
  const { cart, removeItem, updateQuantity, clearCart, purpose, setPurpose } = useCart()
  const [dueDate, setDueDate] = useState('')
  // กำหนดวันคืนแยกรายชิ้น (เฟส 3) — ค่าเริ่มต้นคือวันเดียวกันทั้งใบเหมือนเดิม
  // ponytail: state ในหน้านี้พอ ไม่ต้อง persist ลงตะกร้า ผู้ใช้ตั้งวันตอนกำลังจะกดส่งอยู่แล้ว
  const [splitDates, setSplitDates] = useState(false)
  const [itemDues, setItemDues] = useState({})   // { equipmentId: 'YYYY-MM-DD' }
  // จำว่าผู้ใช้เลือก "อื่น ๆ" ไว้ — ข้อความว่างเปล่าอย่างเดียวแยกไม่ออกว่ายังไม่ได้เลือก หรือเลือกอื่น ๆ แล้วแต่ยังไม่พิมพ์
  const [customPurpose, setCustomPurpose] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const cartPayload = () => ({
    purpose: purpose.trim(),
    requested_due_date: dueDate,
    items: cart.map((c) => ({
      equipment_id: c.equipment.id,
      quantity: c.quantity,
      // ไม่ติ๊กแยกวัน หรือแถวนั้นยังไม่ได้เลือกวัน = ใช้วันของทั้งใบ (backend เติมให้เอง)
      ...(splitDates && itemDues[c.equipment.id] ? { requested_due_date: itemDues[c.equipment.id] } : {}),
    })),
  })

  // ปุ่มที่ถูกเลือกอ่านจากข้อความปัจจุบัน ไม่เก็บ state แยก — สลับหน้าไปเลือกของแล้วกลับมา ปุ่มยังค้างถูกต้อง
  // (purpose ถูก persist ลง localStorage แล้ว ดู useBorrowCart)
  const activePreset = PURPOSE_PRESETS.find((p) => p.label === purpose)

  const pickPreset = (preset) => {
    if (preset.days === null) {
      // "อื่น ๆ" — ล้างเฉพาะข้อความที่มาจากตัวเลือกสำเร็จรูป ข้อความที่ผู้ใช้พิมพ์เองต้องไม่หาย
      // และไม่แตะวันที่ ให้ผู้ใช้เลือกเองตามที่ตกลงไว้
      setCustomPurpose(true)
      if (activePreset) setPurpose('')
      return
    }
    setCustomPurpose(false)
    setPurpose(preset.label)
    setDueDate(daysFromToday(preset.days))
  }

  const validate = () => {
    if (!purpose.trim()) { setError('กรุณาระบุวัตถุประสงค์การยืม'); return false }
    if (!dueDate) { setError('กรุณาระบุวันที่คาดว่าจะคืนก่อน'); return false }
    return true
  }

  const previewDraft = async () => {
    if (!validate()) return
    setError('')
    try {
      openPdf(await borrowApi.previewPdf(cartPayload()))
    } catch (err) {
      setError(err.response?.data?.detail ?? 'สร้างตัวอย่างไม่สำเร็จ')
    }
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (cart.length === 0) return
    if (!validate()) return
    setError('')
    setLoading(true)
    try {
      await borrowApi.create(cartPayload())
      clearCart()
      navigate('/my-borrows')
    } catch (err) {
      setError(err.response?.data?.detail ?? 'ยื่นคำขอไม่สำเร็จ')
    } finally {
      setLoading(false)
    }
  }

  const renderRow = ({ equipment: eq, quantity }) => (
    <div key={eq.id} className="flex flex-wrap items-center gap-3 p-4">
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-gray-800 truncate">{eq.name}</p>
        {/* ซ่อนรหัสหน่วยเจาะจงถ้ามีมากกว่า 1 หน่วย — รวมของที่มาจากชุดอุปกรณ์ด้วย (backend เติม
            unit_count ให้แล้ว) ไม่รู้ค่าแน่ชัด (undefined) ถือว่าไม่ปลอดภัย ไม่โชว์ไว้ก่อน และซ่อนสำหรับ
            consumable เสมอ — รหัสวัสดุสิ้นเปลืองเป็นเลขที่ระบบตั้งเองอัตโนมัติ ไม่มีความหมายในตะกร้า */}
        {eq.unit_count === 1 && eq.item_type !== 'consumable' && (
          <p className="text-xs text-gray-400">{eq.code}</p>
        )}
      </div>
      {/* การ์ดที่ยุบรวมหลายหน่วยรุ่นเดียวกันขอเกิน 1 ได้ ไม่ได้ล็อกตาม item_type อีกต่อไป */}
      {eq.quantity_available > 1 ? (
        <div className="flex items-center gap-1.5">
          <input
            type="number"
            min={1}
            max={eq.quantity_available}
            value={quantity}
            onChange={(e) => updateQuantity(eq.id, Number(e.target.value))}
            className="w-16 rounded border border-gray-300 px-2 py-1 text-sm text-center"
          />
          {/* หน่วยฐาน เช่น "ซม." — วัสดุที่ตัดแบ่งได้ตั้งหน่วยเล็กสุดไว้ ต้องเห็นตอนกรอกจำนวน */}
          <span className="text-sm text-gray-500 w-10">{eq.unit ?? 'ชิ้น'}</span>
        </div>
      ) : (
        <span className="text-sm text-gray-500">1 ชิ้น</span>
      )}
      <button
        type="button"
        onClick={() => removeItem(eq.id)}
        className="text-gray-300 hover:text-red-500 text-lg leading-none"
      >
        ×
      </button>
      {splitDates && (
        <div className="w-full flex items-center gap-2 pl-1">
          <span className="text-xs text-gray-500">คืนวันที่</span>
          <DateInput
            type="date"
            min={tomorrow()}
            max={maxDueDate()}
            value={itemDues[eq.id] ?? dueDate}
            onChange={(e) => setItemDues((m) => ({ ...m, [eq.id]: e.target.value }))}
            className="rounded border border-gray-300 px-2 py-1 text-sm"
          />
        </div>
      )}
    </div>
  )

  if (cart.length === 0) {
    return (
      <div className="max-w-lg mx-auto px-4 py-16 text-center">
        <button onClick={() => navigate(-1)} className="mb-6 text-sm text-gray-500 hover:text-gray-700 hover:underline">
          ← ย้อนกลับ
        </button>
        <p className="text-gray-400 mb-4">ตะกร้าว่างเปล่า</p>
        <Link to="/equipment" className="text-primary-600 hover:underline text-sm font-medium">
          ← เลือกอุปกรณ์
        </Link>
      </div>
    )
  }

  return (
    <div className="px-6 py-8">
      <button onClick={() => navigate(-1)} className="mb-3 text-sm text-gray-500 hover:text-gray-700 hover:underline">
        ← ย้อนกลับ
      </button>
      <h1 className="text-2xl font-light text-gray-800 mb-6">ยื่นคำขอยืมอุปกรณ์</h1>

      {error && (
        <div className="mb-4 rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* 2 คอลัมน์บนจอกว้าง — รายการของฝั่งซ้าย ฟอร์มฝั่งขวา ไม่ต้องเลื่อนลงไปหาปุ่มส่งเมื่อของเยอะ
          จอเล็กยุบเป็นคอลัมน์เดียวตามลำดับเดิม */}
      <form onSubmit={handleSubmit} className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_400px] items-start">
        {/* Cart items */}
        <div className="bg-white rounded-xl border border-gray-200 divide-y">
          {cart.map(renderRow)}
        </div>

        <div className="space-y-6 lg:sticky lg:top-20">
          {/* Purpose */}
          <div>
            <label className="flex items-center gap-1.5 text-sm font-medium text-gray-700 mb-2">
              วัตถุประสงค์การยืม <span className="text-red-500">*</span>
              <Tooltip text="เลือกหัวข้อสำเร็จรูปเพื่อเติมวันที่คาดว่าจะคืนให้อัตโนมัติ — แก้วันเองได้ก่อนกดส่ง" side="top" />
            </label>
            <select
              value={activePreset ? activePreset.label : (customPurpose || purpose ? OTHER_PURPOSE : '')}
              onChange={(e) => {
                const preset = PURPOSE_PRESETS.find((p) => p.label === e.target.value)
                if (preset) pickPreset(preset)
                else { setCustomPurpose(false); setPurpose('') }   // กลับไปที่ "— เลือกวัตถุประสงค์ —"
              }}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500 mb-2"
            >
              <option value="">— เลือกวัตถุประสงค์ —</option>
              {PURPOSE_PRESETS.map((p) => (
                <option key={p.label} value={p.label}>
                  {p.days === null ? p.label : `${p.label} · คืนใน ${p.days} วัน`}
                </option>
              ))}
            </select>
            <textarea
              rows={3}
              required
              value={purpose}
              onChange={(e) => setPurpose(e.target.value)}
              placeholder="อธิบายสั้น ๆ ว่าจะนำอุปกรณ์ไปใช้ทำอะไร"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 resize-none"
            />
          </div>

          {/* วันที่คาดว่าจะคืน — นักศึกษาระบุเอง แอดมินพิจารณาอนุมัติ/ปฏิเสธตามวันนี้ */}
          <div>
            <label className="flex items-center gap-1.5 text-sm font-medium text-gray-700 mb-1">
              วันที่คาดว่าจะคืน <span className="text-red-500">*</span>
              <Tooltip text={'วันที่นี้จะกลายเป็นวันครบกำหนดคืนจริงทันทีที่แอดมินอนุมัติคำขอ — เลือกให้ตรงกับที่ตั้งใจใช้งานจริง'} side="top" />
            </label>
            <DateInput
              type="date"
              required
              min={tomorrow()}
              max={maxDueDate()}
              value={dueDate}
              onChange={(e) => setDueDate(e.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
            />
            {cart.length > 1 && (
              <label className="mt-2 flex items-center gap-2 text-sm text-gray-600">
                <input
                  type="checkbox"
                  checked={splitDates}
                  onChange={(e) => setSplitDates(e.target.checked)}
                  className="rounded border-gray-300"
                />
                กำหนดวันคืนแยกรายชิ้น
                <Tooltip text="ของแต่ละชิ้นไม่จำเป็นต้องคืนพร้อมกัน — ติ๊กแล้วเลือกวันคืนของแต่ละรายการได้เอง (ไม่เลือก = ใช้วันด้านบน)" side="top" />
              </label>
            )}
          </div>

          <div className="flex flex-wrap gap-3">
            <Link
              to="/equipment"
              className="flex-1 text-center rounded-full border border-gray-300 py-2 text-sm text-gray-600 hover:bg-gray-50"
            >
              + เพิ่มอุปกรณ์
            </Link>
            <button
              type="button"
              onClick={previewDraft}
              className="flex-1 rounded-full border border-primary-300 py-2 text-sm font-medium text-primary-700 hover:bg-primary-50"
            >
              ดูตัวอย่างใบยืม
            </button>
            <button
              type="submit"
              disabled={loading}
              className="flex-1 rounded-full bg-primary-600 py-2 text-sm font-semibold text-white hover:bg-primary-700 disabled:opacity-50"
            >
              {loading ? 'กำลังส่ง…' : 'ยื่นคำขอ'}
            </button>
          </div>
        </div>
      </form>
    </div>
  )
}
