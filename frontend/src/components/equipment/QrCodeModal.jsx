import { useEffect, useState } from 'react'
import { equipmentApi } from '../../api/equipmentApi.js'

// โชว์ QR code ของอุปกรณ์ 1 หน่วย — สแกนแล้วเปิดหน้ารายละเอียดอุปกรณ์ชิ้นนั้นตรง ๆ (ดู equipment_service.generate_qr)
// ponytail: รูป + ลิงก์ดาวน์โหลดพอ ไม่ทำ print pipeline ในแอป
export default function QrCodeModal({ id, name, onClose }) {
  const [url, setUrl] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let objectUrl
    equipmentApi.qrcode(id)
      .then((blob) => { objectUrl = URL.createObjectURL(blob); setUrl(objectUrl) })
      .catch(() => setError('สร้าง QR code ไม่สำเร็จ'))
    return () => { if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [id])

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50 px-4" onClick={onClose}>
      <div className="bg-white rounded-2xl p-6 w-full max-w-xs shadow-xl text-center" onClick={(e) => e.stopPropagation()}>
        <h2 className="font-bold text-gray-800 mb-1">QR Code</h2>
        <p className="text-sm text-gray-500 mb-4">{name}</p>
        {error && <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2 mb-4">{error}</p>}
        {!error && (
          url ? (
            <>
              <img src={url} alt={`QR code ของ ${name}`} className="mx-auto rounded-lg border border-gray-200" />
              <a href={url} download={`qr-${name}.png`}
                className="mt-4 block w-full rounded-full bg-primary-600 py-2 text-sm font-semibold text-white hover:bg-primary-700">
                ดาวน์โหลด
              </a>
            </>
          ) : (
            <p className="text-gray-400 py-10">กำลังสร้าง…</p>
          )
        )}
        <button onClick={onClose} className="mt-3 w-full rounded-full border py-2 text-sm text-gray-600 hover:bg-gray-50">ปิด</button>
      </div>
    </div>
  )
}
