import { useEffect, useState } from 'react'

/**
 * ช่องเลือก/กรอกค่าคุณภาพใหม่ — ใช้ร่วมกันทุกจุดที่ให้ประเมินคุณภาพ (เฟส 10):
 * ปุ่มประเมินเดี่ยว ๆ ในหน้าอุปกรณ์ · ติดตั้งชิ้นส่วน · สถานะกลับเป็นพร้อมใช้ (ซ่อมเสร็จ) · รับคืนแบบชำรุด
 *
 * เลือกได้ 4 แบบ: คงเดิม (ไม่ประเมิน/ข้าม) · ลด 1 · ลดตามค่าเริ่มต้นจาก settings (ปกติ 2) · กรอกเอง
 * หน่วยที่ยังไม่เคยประเมิน (currentQuality == null) ไม่มี "คงเดิม/ลด N" ให้เลือก เพราะไม่มีฐานให้ลบ —
 * ขึ้นเป็นช่องกรอกเดียว "ประเมินครั้งแรก (ไม่บังคับ)"
 *
 * onChange ได้ค่า number (0-100) หรือ null (= ไม่แตะค่าคุณภาพเลย ข้ามจังหวะนี้ไป)
 */
export default function QualityAssessField({
  currentQuality = null,
  defaultDrop = 2,
  value,
  onChange,
  required = false,
  label,
}) {
  const notYetAssessed = currentQuality == null
  const [mode, setMode] = useState(required ? 'custom' : 'keep')
  const [customValue, setCustomValue] = useState(
    notYetAssessed ? '' : String(Math.max(0, Math.round((currentQuality - defaultDrop) * 100) / 100)),
  )

  const clamp = (n) => Math.min(100, Math.max(0, n))

  useEffect(() => {
    if (notYetAssessed) {
      onChange(customValue === '' ? null : clamp(Number(customValue)))
      return
    }
    if (mode === 'keep') onChange(null)
    else if (mode === 'minus1') onChange(clamp(Math.round((currentQuality - 1) * 100) / 100))
    else if (mode === 'minusDefault') onChange(clamp(Math.round((currentQuality - defaultDrop) * 100) / 100))
    else onChange(customValue === '' ? null : clamp(Number(customValue)))
    // ต้องมี currentQuality/defaultDrop ใน deps ด้วย — ทั้งคู่มาจาก props ที่โหลดช้ากว่า mount ได้
    // (defaultDrop มาจาก settingsApi.list() แบบ async ใน EquipmentManagePage, currentQuality มาจาก
    // initial ที่ refresh ได้หลังประเมิน) ถ้าแอดมินกด "-N" ก่อนค่าจริงโหลดเสร็จ effect เดิมไม่รันซ้ำ
    // เพราะ deps ไม่มีสองตัวนี้ → onChange ค้างค่าที่คำนวณจากของเก่า ทั้งที่ตัวเลขบนปุ่มอัปเดตแล้ว
    // (แก้ตามรีวิวรอบ 3, MINOR-5) — onChange ยังตั้งใจไม่ใส่ (parent ไม่ได้ memo มา ใส่แล้ววนลูป)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, customValue, notYetAssessed, currentQuality, defaultDrop])

  const btnCls = (active) =>
    `rounded-full px-2.5 py-1 text-xs font-medium border transition-colors ${
      active ? 'bg-primary-600 text-white border-primary-600' : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50'
    }`

  if (notYetAssessed) {
    // ป้าย/สถานะบังคับต้องตาม context ของแต่ละจุดที่เรียก (prop `required`) — เดิม hardcode "(ไม่บังคับ)"
    // เสมอแม้แต่ในไดอะล็อก "ประเมินคุณภาพ" เดี่ยว ๆ ที่บังคับกรอกจริง (required=true) ทำให้ป้ายโกหกผู้ใช้
    return (
      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">
          {label || `ประเมินครั้งแรก${required ? '' : ' (ไม่บังคับ)'}`}
        </label>
        <input
          type="number" min={0} max={100} step="0.1" value={customValue} required={required}
          onChange={(e) => setCustomValue(e.target.value)}
          placeholder="เช่น 90 (%)"
          className="w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
        />
      </div>
    )
  }

  return (
    <div>
      <label className="block text-xs font-medium text-gray-600 mb-1">
        {label || `ประเมินคุณภาพใหม่${required ? '' : ' (ไม่บังคับ)'} — ปัจจุบัน ${currentQuality}%`}
      </label>
      <div className="flex flex-wrap gap-1.5 mb-1.5">
        {!required && (
          <button type="button" onClick={() => setMode('keep')} className={btnCls(mode === 'keep')}>คงเดิม</button>
        )}
        <button type="button" onClick={() => setMode('minus1')} className={btnCls(mode === 'minus1')}>-1</button>
        <button type="button" onClick={() => setMode('minusDefault')} className={btnCls(mode === 'minusDefault')}>
          -{defaultDrop}
        </button>
        <button type="button" onClick={() => setMode('custom')} className={btnCls(mode === 'custom')}>กรอกเอง</button>
      </div>
      {mode === 'custom' && (
        <input
          type="number" min={0} max={100} step="0.1" autoFocus value={customValue}
          onChange={(e) => setCustomValue(e.target.value)}
          placeholder="เช่น 75 (%)"
          className="w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
        />
      )}
      {mode !== 'custom' && mode !== 'keep' && (
        <p className="text-xs text-gray-400">
          ตั้งเป็น {mode === 'minus1' ? clamp(Math.round((currentQuality - 1) * 100) / 100)
            : clamp(Math.round((currentQuality - defaultDrop) * 100) / 100)}%
        </p>
      )}
    </div>
  )
}
