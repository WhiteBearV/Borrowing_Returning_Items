import { useEffect, useRef, useState } from 'react'
import { parseScan } from '../../utils/scan.js'

// ponytail: ใช้ BarcodeDetector ของเบราว์เซอร์ ไม่เพิ่ม dependency — รองรับ Chrome/Edge บน Android, macOS, ChromeOS
// แต่ไม่มีบน iPhone/Firefox/Chrome บน Windows-Linux บางรุ่น → เหลือช่องพิมพ์รหัส (หรือเปิดกล้องมือถือสแกน QR
// ซึ่งเป็นลิงก์อยู่แล้ว) ถ้าเจ้าหน้าที่ต้องใช้บน iPhone จริงค่อยเพิ่ม lib ถอดรหัส QR (เช่น jsQR) เป็น fallback
const SUPPORTED = typeof window !== 'undefined' && 'BarcodeDetector' in window

/** โมดัลสแกน QR/บาร์โค้ดด้วยกล้อง — onResult รับ { equipmentId } หรือ { code } (ดู utils/scan.js) */
export default function QrScanModal({ title = 'สแกน QR อุปกรณ์', onResult, onClose }) {
  const videoRef = useRef(null)
  const [error, setError] = useState(SUPPORTED ? '' : 'เบราว์เซอร์นี้สแกนด้วยกล้องไม่ได้ — พิมพ์รหัสอุปกรณ์แทน')
  const [manual, setManual] = useState('')
  // ref กันกล้องปิด-เปิดใหม่ทุกครั้งที่ parent re-render แล้วส่ง onResult ตัวใหม่มา
  const onResultRef = useRef(onResult)
  onResultRef.current = onResult

  useEffect(() => {
    if (!SUPPORTED) return undefined
    let stream
    let timer
    let stopped = false
    let detector
    try {
      detector = new window.BarcodeDetector()
    } catch {
      setError('เบราว์เซอร์นี้สแกนด้วยกล้องไม่ได้ — พิมพ์รหัสอุปกรณ์แทน')
      return undefined
    }

    navigator.mediaDevices?.getUserMedia({ video: { facingMode: 'environment' } })
      .then(async (s) => {
        if (stopped) { s.getTracks().forEach((t) => t.stop()); return }
        stream = s
        const video = videoRef.current
        video.srcObject = s
        await video.play()
        // ถี่พอให้รู้สึกทันที แต่ไม่กิน CPU แท็บเล็ตเหมือนสแกนทุกเฟรม
        timer = setInterval(async () => {
          try {
            const [hit] = await detector.detect(video)
            const parsed = hit && parseScan(hit.rawValue)
            if (parsed && !stopped) { stopped = true; onResultRef.current(parsed) }
          } catch { /* เฟรมยังไม่พร้อม — รอบถัดไป */ }
        }, 250)
      })
      .catch(() => setError('เปิดกล้องไม่ได้ — อนุญาตสิทธิ์กล้อง (ต้องเปิดผ่าน https) หรือพิมพ์รหัสแทน'))

    return () => {
      stopped = true
      clearInterval(timer)
      stream?.getTracks().forEach((t) => t.stop())
    }
  }, [])

  const submitManual = (e) => {
    e.preventDefault()
    const parsed = parseScan(manual)
    if (parsed) onResult(parsed)
  }

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50 px-4 py-6 overflow-y-auto">
      <div className="bg-white rounded-2xl p-6 w-full max-w-md shadow-xl space-y-4">
        <h2 className="font-bold text-gray-800">{title}</h2>

        {SUPPORTED && !error && (
          <div className="relative overflow-hidden rounded-xl bg-black aspect-square">
            <video ref={videoRef} muted playsInline className="h-full w-full object-cover" />
            <div className="pointer-events-none absolute inset-10 rounded-lg border-2 border-white/70" />
          </div>
        )}
        {error && <p className="text-sm text-amber-700 bg-amber-50 rounded-lg px-3 py-2">{error}</p>}

        <form onSubmit={submitManual} className="flex gap-2">
          <input autoFocus={!SUPPORTED} value={manual} onChange={(e) => setManual(e.target.value)}
            placeholder="หรือพิมพ์/ยิงบาร์โค้ดรหัสอุปกรณ์"
            className="flex-1 min-w-0 rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
          <button type="submit" disabled={!manual.trim()}
            className="rounded-full bg-primary-600 px-4 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-50">
            ค้นหา
          </button>
        </form>

        <button type="button" onClick={onClose}
          className="w-full rounded-full border border-gray-300 py-2 text-sm font-medium text-gray-600 hover:bg-gray-50">
          ปิด
        </button>
      </div>
    </div>
  )
}
