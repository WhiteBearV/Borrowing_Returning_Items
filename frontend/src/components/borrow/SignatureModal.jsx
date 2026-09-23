import { useRef, useState } from 'react'
import { borrowApi } from '../../api/borrowApi.js'
import SignaturePad from '../common/SignaturePad.jsx'

/** ป้ายไทยของลายเซ็นแต่ละชนิด — ใช้ร่วมกันทุกที่ที่โชว์ปุ่มดูลายเซ็น (ต้องตรงกับ SIGNATURE_FIELDS ฝั่ง backend) */
export const SIGNATURE_LABEL = {
  handover_borrower: 'ลายเซ็นผู้รับของ',
  handover_staff: 'ลายเซ็นผู้จ่ายของ',
  return_borrower: 'ลายเซ็นผู้คืน',
  return_staff: 'ลายเซ็นผู้รับคืน',
}

const COPY = {
  handover: {
    title: 'จ่ายของ + เซ็นรับ',
    hint: 'ยื่นจอให้ผู้ยืมเซ็นยืนยันว่ารับอุปกรณ์ครบแล้ว',
    borrower: 'ลายเซ็นผู้รับของ',
    staff: 'ลายเซ็นผู้จ่ายของ (เว้นได้)',
    submit: 'บันทึกการจ่ายของ',
    call: borrowApi.handover,
  },
  return: {
    title: 'เซ็นรับคืน',
    hint: 'ใช้หลังสรุปสภาพอุปกรณ์ครบแล้ว — ลายเซ็นจะขึ้นบนใบคืน',
    borrower: 'ลายเซ็นผู้คืน',
    staff: 'ลายเซ็นผู้รับคืน (เว้นได้)',
    submit: 'บันทึกการรับคืน',
    call: borrowApi.signReturn,
  },
}

/** เซ็นรับของ / เซ็นรับคืน บนหน้าจอ (เฟส 11)
 *
 *  ใช้โมดัลตัวเดียวทั้งสองจังหวะ เพราะหน้าตาและกติกาเหมือนกันทุกอย่าง ต่างแค่ป้ายกับ endpoint
 *  เจ้าหน้าที่เป็นคนเปิดที่เคาน์เตอร์แล้วยื่นจอให้ผู้ยืมเซ็น — ลายเซ็นเจ้าหน้าที่เว้นได้
 */
export function SignatureModal({ requestId, requestCode, mode = 'handover', onClose, onDone }) {
  const copy = COPY[mode]
  const borrowerRef = useRef(null)
  const staffRef = useRef(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const submit = async () => {
    const borrower = await borrowerRef.current?.toBlob()
    if (!borrower) {
      setError('ต้องมีลายเซ็นผู้ยืมก่อนจึงจะบันทึกได้')
      return
    }
    setLoading(true)
    setError('')
    try {
      await copy.call(requestId, borrower, await staffRef.current?.toBlob())
      onDone()
    } catch (err) {
      setError(err.response?.data?.detail ?? 'บันทึกลายเซ็นไม่สำเร็จ')
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50 px-4 py-6 overflow-y-auto">
      <div className="bg-white rounded-2xl p-6 w-full max-w-lg shadow-xl space-y-4">
        <div>
          <h2 className="font-bold text-gray-800">{copy.title}</h2>
          <p className="text-sm text-gray-500">{requestCode} — {copy.hint}</p>
        </div>

        <SignaturePad ref={borrowerRef} label={copy.borrower} />
        <SignaturePad ref={staffRef} label={copy.staff} height={140} />

        {error && <p className="text-sm text-red-600">{error}</p>}

        <div className="flex gap-2 pt-1">
          <button type="button" onClick={onClose} disabled={loading}
            className="flex-1 rounded-full border border-gray-300 py-2 text-sm font-medium text-gray-600 hover:bg-gray-50">
            ยกเลิก
          </button>
          <button type="button" onClick={submit} disabled={loading}
            className="flex-1 rounded-full bg-primary-600 py-2 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-50">
            {loading ? 'กำลังบันทึก…' : copy.submit}
          </button>
        </div>
      </div>
    </div>
  )
}

export default SignatureModal
