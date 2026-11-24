import { useRef, useState } from 'react'
import { borrowApi } from '../../api/borrowApi.js'
import { formatDateTime } from '../../utils/formatDate.js'

/** ป้ายไทยของลายเซ็นแต่ละชนิด — ใช้ร่วมกันทุกที่ที่โชว์ลายเซ็น (ต้องตรงกับ SIGNATURE_FIELDS ฝั่ง backend) */
export const SIGNATURE_LABEL = {
  handover_borrower: 'ลายเซ็นผู้ยืม',
  handover_staff: 'ลายเซ็นผู้อนุมัติ',
  return_borrower: 'ลายเซ็นผู้คืน',
  return_staff: 'ลายเซ็นผู้รับคืน',
}

/** ข้อความสั้นของการลงนามอิเล็กทรอนิกส์ 1 รายการ (จาก `esignatures` ของคำขอ) */
export const esignText = (e) =>
  `${SIGNATURE_LABEL[e.kind]}: ${e.signer_name ?? '-'} · ${formatDateTime(e.signed_at)} · อ้างอิง ${e.ref}`

/** ฝั่งนี้ลงนามแล้วหรือยัง — รูปแบบเก่า (signatures = มีรูป) หรือ E-sign (esignatures) */
export const isSigned = (req, kind) =>
  !!(req.signatures?.includes(kind) || req.esignatures?.some((e) => e.kind === kind))

const COPY = {
  handover: {
    title: 'จ่ายของ + ลงชื่อใบยืม',
    hint: 'ผู้ยืมยังไม่ได้ลงชื่อใบยืม — ยื่นจอให้ผู้ยืมพิมพ์รหัสผ่านของตัวเอง',
    borrower: 'รหัสผ่านผู้ยืม',
    staff: 'รหัสผ่านเจ้าหน้าที่ (เว้นได้)',
    submit: 'ลงนามและบันทึกการจ่ายของ',
    call: borrowApi.handover,
  },
  return: {
    title: 'ลงชื่อใบคืน',
    hint: 'ใช้หลังสรุปสภาพอุปกรณ์แล้ว — ผู้คืนลงชื่อเองจากหน้า "การยืมของฉัน" ได้ ไม่ต้องลงที่นี่',
    borrower: 'รหัสผ่านผู้คืน (เว้นได้)',
    staff: 'รหัสผ่านผู้รับคืน',
    submit: 'ลงนามและบันทึกการรับคืน',
    call: borrowApi.signReturn,
  },
}

const INPUT = 'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500'

/** ลงนามรับของ / รับคืน ด้วยรหัสผ่าน (E-sign — 16 พ.ย. 69)
 *
 *  แทนการวาดลายเซ็นเก็บเป็นรูป: เซิร์ฟเวอร์ถูกแฮ็กเมื่อไหร่ รูปลายมือหลุดเอาไปปลอมเอกสารอื่นได้
 *  ตอนนี้ระบบเก็บแค่ "ใครยืนยันตัวตนลงนามเนื้อหาอะไรเมื่อไหร่" และประทับตราดิจิทัลบน PDF
 */
export function SignatureModal({ requestId, requestCode, borrowerName, mode = 'handover', signed = [], onClose, onDone }) {
  // ฝั่งที่ลงชื่อแล้ว (เช่น ผู้คืนลงชื่อเองจากมือถือ) ไม่ต้องโชว์ช่องรหัส — ลงซ้ำ backend ตอบ 400
  const askBorrower = !signed.includes(mode === 'return' ? 'return_borrower' : 'handover_borrower')
  const askStaff = !signed.includes(mode === 'return' ? 'return_staff' : 'handover_staff')
  const copy = COPY[mode]
  const [borrowerPw, setBorrowerPw] = useState('')
  const [staffPw, setStaffPw] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const busy = useRef(false) // กันดับเบิลคลิก (QA-23)

  const submit = async (e) => {
    e.preventDefault()
    if (busy.current) return
    if (mode === 'handover' && askBorrower && !borrowerPw) { setError('ผู้ยืมต้องพิมพ์รหัสผ่านก่อนจึงจะบันทึกได้'); return }
    if (mode === 'return' && !borrowerPw && !staffPw) { setError('พิมพ์รหัสผ่านอย่างน้อย 1 ฝั่ง'); return }
    busy.current = true
    setLoading(true)
    setError('')
    try {
      await copy.call(requestId, borrowerPw, staffPw)
      onDone()
    } catch (err) {
      setError(err.response?.data?.detail ?? 'ลงนามไม่สำเร็จ')
      busy.current = false
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50 px-4 py-6 overflow-y-auto">
      <form onSubmit={submit} autoComplete="off"
        className="bg-white rounded-2xl p-6 w-full max-w-md shadow-xl space-y-4">
        <div>
          <h2 className="font-bold text-gray-800">{copy.title}</h2>
          <p className="text-sm text-gray-500">{requestCode}{borrowerName && ` · ${borrowerName}`} — {copy.hint}</p>
        </div>

        {askBorrower ? (
          <label className="block text-sm font-medium text-gray-700">
            {copy.borrower}
            <input type="password" autoFocus autoComplete="new-password" maxLength={72} value={borrowerPw}
              onChange={(e) => setBorrowerPw(e.target.value)} className={`mt-1 ${INPUT}`} />
          </label>
        ) : <p className="text-sm text-emerald-700">✔ ผู้ยืมลงชื่อแล้ว</p>}
        {askStaff ? (
          <label className="block text-sm font-medium text-gray-700">
            {copy.staff}
            <input type="password" autoComplete="new-password" maxLength={72} value={staffPw}
              onChange={(e) => setStaffPw(e.target.value)} className={`mt-1 ${INPUT}`} />
          </label>
        ) : <p className="text-sm text-emerald-700">✔ เจ้าหน้าที่ลงชื่อแล้ว</p>}
        <p className="text-xs text-gray-500">
          ระบบไม่เก็บรหัสผ่านและไม่เก็บรูปลายเซ็น — บันทึกเฉพาะผู้ลงนาม เวลา และเลขอ้างอิงที่พิมพ์บนเอกสาร
        </p>

        {error && <p className="text-sm text-red-600">{error}</p>}

        <div className="flex gap-2 pt-1">
          <button type="button" onClick={onClose} disabled={loading}
            className="flex-1 rounded-full border border-gray-300 py-2 text-sm font-medium text-gray-600 hover:bg-gray-50">
            ยกเลิก
          </button>
          <button type="submit" disabled={loading}
            className="flex-1 rounded-full bg-primary-600 py-2 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-50">
            {loading ? 'กำลังบันทึก…' : copy.submit}
          </button>
        </div>
      </form>
    </div>
  )
}

export default SignatureModal
