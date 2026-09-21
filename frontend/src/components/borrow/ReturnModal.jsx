import { useEffect, useMemo, useState } from 'react'
import { borrowApi } from '../../api/borrowApi.js'
import { equipmentApi } from '../../api/equipmentApi.js'
import { settingsApi } from '../../api/settingsApi.js'
import { fineMoney, previewFine } from '../../utils/fine.js'
import QualityAssessField from '../equipment/QualityAssessField.jsx'

// สถานะสรุปผลแยกตามชนิด + สถานะที่ต้องแนบรูป
const DURABLE_OPTIONS = [{ value: 'ok', label: 'ปกติ' }, { value: 'damaged', label: 'เสียหาย' }, { value: 'lost', label: 'สูญหาย' }]
const CONSUMABLE_OPTIONS = [{ value: 'returned_full', label: 'คืนครบ (ไม่ได้ใช้)' }, { value: 'used_up', label: 'ใช้หมด' }, { value: 'discarded', label: 'เสียหาย/ทิ้ง' }]
const PHOTO_REQUIRED = new Set(['damaged', 'lost', 'discarded'])
export const CONDITION_LABEL = {
  ok: 'ปกติ', damaged: 'เสียหาย', lost: 'สูญหาย',
  returned_full: 'คืนครบ', used_up: 'ใช้หมด', discarded: 'เสียหาย/ทิ้ง',
}
const imgSrc = (url) => (url?.startsWith('/') ? `${import.meta.env.VITE_API_URL || 'http://localhost:8000'}${url}` : url)

// ยืนยันรับคืน/สรุปผลอุปกรณ์ทีละชิ้น — ใช้ร่วมกันทั้งหน้า "ประวัติการยืมทั้งหมด" และ "อนุมัติคำขอ"
// (แยกออกมาจาก AllBorrowsPage.jsx เดิมที่นิยามในไฟล์เดียวไม่ได้ export)
export function ReturnModal({ item, req, requestId, onClose, onDone }) {
  const isConsumable = item.item_type_snapshot === 'consumable'
  const options = isConsumable ? CONSUMABLE_OPTIONS : DURABLE_OPTIONS
  const [condition, setCondition] = useState(options[0].value)
  const [note, setNote] = useState('')
  const [photos, setPhotos] = useState([])
  const [uploading, setUploading] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [settings, setSettings] = useState(null)
  // ยอดที่แอดมินกรอกทับ ('' = ใช้ยอดที่ระบบคิดให้)
  const [lateOverride, setLateOverride] = useState('')
  const [damageOverride, setDamageOverride] = useState('')
  // ค่าคุณภาพ (เฟส 10) — จังหวะที่ 4 ของ 4 จังหวะให้ประเมิน: รับคืนแบบชำรุด มีผลเฉพาะเครื่องที่เปิดติดตามอยู่
  const [eqQuality, setEqQuality] = useState(null) // { tracked, current }
  const [qualityAfter, setQualityAfter] = useState(null)

  const needPhoto = PHOTO_REQUIRED.has(condition)

  // อัตราค่าปรับอ่านจาก settings เพื่อพรีวิวยอดก่อนกดยืนยัน — ยอดจริงคำนวณและ freeze ที่ backend
  useEffect(() => { settingsApi.list().then(setSettings).catch(() => setSettings([])) }, [])
  const defaultDrop = (() => {
    const v = Number(settings?.find?.((s) => s.key === 'quality_repair_default_drop')?.value)
    return Number.isFinite(v) ? v : 2
  })()

  // ดึงข้อมูลคุณภาพของเครื่องเฉพาะตอนเลือก "เสียหาย" — ไม่โหลดล่วงหน้าทุกครั้งเพราะส่วนใหญ่คืนปกติ
  useEffect(() => {
    if (condition !== 'damaged' || !item.equipment_id) { setEqQuality(null); return }
    equipmentApi.get(item.equipment_id)
      .then((eq) => setEqQuality({ tracked: !!eq.quality_tracked, current: eq.current_quality ?? null }))
      .catch(() => setEqQuality(null))
  }, [condition, item.equipment_id])
  const fine = useMemo(
    () => previewFine(item, req, condition, settings), [item, req, condition, settings])
  const shownLate = lateOverride === '' ? fine.lateAmount : Number(lateOverride) || 0
  const shownDamage = damageOverride === '' ? fine.damageAmount : Number(damageOverride) || 0
  const hasFine = fine.lateAmount > 0 || fine.damageAmount > 0 || shownLate > 0 || shownDamage > 0

  const uploadPhotos = async (e) => {
    const files = Array.from(e.target.files ?? [])
    if (!files.length) return
    setUploading(true)
    setError('')
    try {
      const results = await Promise.all(files.map((f) => equipmentApi.uploadImage(f)))
      setPhotos((p) => [...p, ...results.map((r) => r.image_url)])
    } catch (err) {
      setError(err.response?.data?.detail ?? 'อัปโหลดรูปไม่สำเร็จ')
    } finally {
      setUploading(false)
    }
  }

  const submit = async () => {
    if (needPhoto && photos.length === 0) {
      setError('กรุณาถ่าย/แนบรูปหลักฐานอย่างน้อย 1 รูป')
      return
    }
    setLoading(true)
    setError('')
    try {
      await borrowApi.returnItem(requestId, item.id, {
        condition_on_return: condition,
        damage_note: note || undefined,
        damage_photo_urls: photos.length ? photos : undefined,
        fine_late_amount_override: lateOverride === '' ? undefined : Number(lateOverride),
        fine_damage_amount_override: damageOverride === '' ? undefined : Number(damageOverride),
        // ประเมินคุณภาพใหม่ (ไม่บังคับ) — มีผลเฉพาะเครื่องที่เปิดติดตามคุณภาพและเลือก "เสียหาย"
        ...(condition === 'damaged' && eqQuality?.tracked && qualityAfter != null
          ? { quality_after: qualityAfter } : {}),
      })
      onDone()
    } catch (err) {
      setError(err.response?.data?.detail ?? 'บันทึกไม่สำเร็จ')
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50 px-4">
      <div className="bg-white rounded-2xl p-6 w-full max-w-sm shadow-xl space-y-4">
        <h2 className="font-bold text-gray-800">{isConsumable ? 'สรุปผลวัสดุสิ้นเปลือง' : 'ยืนยันรับคืนอุปกรณ์'}</h2>
        <p className="text-sm text-gray-500">{item.equipment_name ?? item.equipment_id} ×{item.quantity}</p>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">{isConsumable ? 'ผลการใช้งาน' : 'สภาพอุปกรณ์'}</label>
          <select value={condition} onChange={(e) => setCondition(e.target.value)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500">
            {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
        {needPhoto && (
          <>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                รูปหลักฐานความเสียหาย <span className="text-red-500">*</span>
              </label>
              <input type="file" accept="image/*" capture="environment" multiple onChange={uploadPhotos} disabled={uploading}
                className="block w-full text-xs text-gray-500 file:mr-3 file:rounded-lg file:border-0 file:bg-primary-50 file:px-3 file:py-1.5 file:text-primary-600" />
              {uploading && <p className="mt-1 text-xs text-gray-400">กำลังอัปโหลด…</p>}
              {photos.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-2">
                  {photos.map((url, i) => (
                    <div key={url} className="relative">
                      <img src={imgSrc(url)} alt="" className="w-14 h-14 rounded-lg object-cover border" />
                      <button onClick={() => setPhotos((p) => p.filter((_, j) => j !== i))}
                        className="absolute -top-1.5 -right-1.5 bg-red-500 text-white rounded-full w-4 h-4 text-xs leading-none">×</button>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">บันทึกความเสียหาย</label>
              <textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-primary-500"
                placeholder="อธิบายความเสียหาย…" />
            </div>
            {condition === 'damaged' && eqQuality?.tracked && (
              <QualityAssessField
                currentQuality={eqQuality.current} defaultDrop={defaultDrop}
                value={qualityAfter} onChange={setQualityAfter}
              />
            )}
          </>
        )}
        {hasFine && (
          <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2.5 space-y-2">
            <p className="text-sm font-medium text-amber-800">
              ค่าปรับที่ระบบคิดได้ {fineMoney(shownLate + shownDamage)} บาท
            </p>
            <p className="text-xs text-amber-700 leading-relaxed">
              {fine.daysLate > 0
                ? `ล่าช้า ${fine.daysLate} วัน × ${fineMoney(fine.rate)} บาท = ${fineMoney(fine.lateAmount)} บาท`
                : 'ไม่มีค่าปรับล่าช้า (คืนภายในกำหนด)'}
              {fine.grace > 0 && ` · ผ่อนผัน ${fine.grace} วัน`}
              {fine.cap > 0 && ` · เพดาน ${fineMoney(fine.cap)} บาท`}
              {fine.damageAmount > 0 &&
                ` · ค่าเสียหายตามมูลค่าทางบัญชี ${fineMoney(fine.damageAmount)} บาท`}
            </p>
            <div className="grid grid-cols-2 gap-2">
              <label className="text-xs text-amber-800">
                แก้ยอดค่าปรับล่าช้า
                <input type="number" min="0" step="0.01" value={lateOverride}
                  onChange={(e) => setLateOverride(e.target.value)}
                  placeholder={String(fine.lateAmount)}
                  className="mt-1 w-full rounded-lg border border-amber-300 px-2 py-1 text-sm bg-white" />
              </label>
              <label className="text-xs text-amber-800">
                แก้ยอดค่าเสียหาย
                <input type="number" min="0" step="0.01" value={damageOverride}
                  onChange={(e) => setDamageOverride(e.target.value)}
                  placeholder={String(fine.damageAmount)}
                  className="mt-1 w-full rounded-lg border border-amber-300 px-2 py-1 text-sm bg-white" />
              </label>
            </div>
            <p className="text-[11px] text-amber-600">เว้นว่าง = ใช้ยอดที่ระบบคิดให้ · ยกเว้นค่าปรับทำได้ที่หน้า "ค่าปรับ"</p>
          </div>
        )}
        {error && <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>}
        <div className="flex gap-3">
          <button onClick={onClose} className="flex-1 rounded-full border py-2 text-sm text-gray-600 hover:bg-gray-50">ยกเลิก</button>
          <button onClick={submit} disabled={loading || uploading}
            className="flex-1 rounded-full bg-primary-600 py-2 text-sm font-semibold text-white hover:bg-primary-700 disabled:opacity-50">
            {loading ? 'กำลังบันทึก…' : 'ยืนยัน'}
          </button>
        </div>
      </div>
    </div>
  )
}
