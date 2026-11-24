import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { parseScan } from '../../utils/scan.js'

// QR ที่ระบบพิมพ์ + บาร์โค้ดสติกเกอร์ทะเบียนที่พบบ่อย — จำกัดชนิดให้ตัวถอดรหัสบน iPhone ทำงานเร็ว
const FORMATS = ['qr_code', 'code_128', 'code_39', 'ean_13']

/** ตัวถอดรหัส: ใช้ของเบราว์เซอร์ถ้ามี (Chrome Android) ไม่มี (iPhone/iPad/Firefox/Chrome Linux) → zxing-wasm
 *  ที่เสิร์ฟจากเซิร์ฟเวอร์เราเอง (ไม่ดึง CDN — เซิร์ฟเวอร์อยู่ในวงคณะ) · โหลดแบบ dynamic เฉพาะเครื่องที่ต้องใช้ */
let detectorPromise
function getDetector() {
  detectorPromise ??= (async () => {
    const Native = window.BarcodeDetector
    if (Native) {
      try {
        if ((await Native.getSupportedFormats()).includes('qr_code')) return new Native({ formats: FORMATS })
      } catch { /* มีชื่อแต่ใช้ไม่ได้จริง — ตกไปใช้ wasm */ }
    }
    const [{ BarcodeDetector, prepareZXingModule }, { default: wasmUrl }] = await Promise.all([
      import('barcode-detector/ponyfill'),
      import('zxing-wasm/reader/zxing_reader.wasm?url'),
    ])
    prepareZXingModule({ overrides: { locateFile: (path, prefix) => (path.endsWith('.wasm') ? wasmUrl : prefix + path) } })
    return new BarcodeDetector({ formats: FORMATS })
  })()
  detectorPromise.catch(() => { detectorPromise = undefined }) // โหลดพลาด (เน็ตสะดุด) เปิดโมดัลใหม่ลองอีกรอบได้
  return detectorPromise
}

/** แปลง error ของ getUserMedia เป็นทางแก้ที่ผู้ใช้ทำได้จริง */
function cameraError(err) {
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) return 'insecure'
  switch (err?.name) {
    case 'NotAllowedError':
      return 'ไม่ได้รับอนุญาตให้ใช้กล้อง — iPhone/iPad: ตั้งค่า > Safari > กล้อง > อนุญาต · Android: แตะไอคอนแม่กุญแจข้างช่อง URL > สิทธิ์ > กล้อง แล้วเปิดหน้านี้ใหม่'
    case 'NotFoundError':
    case 'OverconstrainedError':
      return 'ไม่พบกล้องบนเครื่องนี้ — ใช้ปุ่มถ่ายรูป/เลือกรูป QR หรือพิมพ์รหัสแทน'
    case 'NotReadableError':
      return 'กล้องถูกแอปอื่นใช้อยู่ — ปิดแอปกล้อง/วิดีโอคอลก่อน แล้วเปิดหน้านี้ใหม่'
    default:
      return 'เปิดกล้องไม่ได้ — ใช้ปุ่มถ่ายรูป QR หรือพิมพ์รหัสแทน'
  }
}

/** โมดัลสแกน QR/บาร์โค้ดด้วยกล้อง — onResult รับ { equipmentId } หรือ { code } (ดู utils/scan.js) */
/** continuous = สแกนต่อเนื่องไม่ปิดกล้อง (ตรวจครุภัณฑ์ทั้งห้อง) — ชิ้นเดิมติดกันไม่ส่งซ้ำ · children โชว์ใต้กล้อง */
export default function QrScanModal({ title = 'สแกน QR อุปกรณ์', onResult, onClose, continuous = false, children }) {
  const videoRef = useRef(null)
  const [error, setError] = useState('')
  const [live, setLive] = useState(false) // กล้องสดเปิดสำเร็จแล้ว
  const [photoMsg, setPhotoMsg] = useState('')
  const [manual, setManual] = useState('')
  // ref กันกล้องปิด-เปิดใหม่ทุกครั้งที่ parent re-render แล้วส่ง onResult ตัวใหม่มา
  const onResultRef = useRef(onResult)
  onResultRef.current = onResult

  useEffect(() => {
    let stream
    let timer
    let stopped = false
    let last = ''

    // http (ไม่ใช่ https ที่เชื่อถือได้) เบราว์เซอร์ไม่ให้ใช้กล้องสดเลย — ไม่ต้องลอง
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      setError('insecure')
      return undefined
    }
    Promise.all([
      navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' }, audio: false }),
      getDetector(),
    ])
      .then(async ([s, detector]) => {
        if (stopped) { s.getTracks().forEach((t) => t.stop()); return }
        stream = s
        const video = videoRef.current
        video.srcObject = s
        await video.play()
        setLive(true)
        // ถี่พอให้รู้สึกทันที แต่ไม่กิน CPU แท็บเล็ตเหมือนสแกนทุกเฟรม · busy กัน wasm ช้า (iPhone) แล้วงานซ้อนกัน
        let busy = false
        timer = setInterval(async () => {
          if (busy || stopped || video.readyState < 2) return
          busy = true
          try {
            const [hit] = await detector.detect(video)
            const parsed = hit && parseScan(hit.rawValue)
            if (!parsed || stopped) return
            if (!continuous) { stopped = true; onResultRef.current(parsed); return }
            if (hit.rawValue === last) return // กล้องค้างที่ชิ้นเดิม — ไม่ยิงซ้ำทุก 250 มิลลิวินาที
            last = hit.rawValue
            onResultRef.current(parsed)
          } catch { /* เฟรมยังไม่พร้อม — รอบถัดไป */ } finally { busy = false }
        }, 250)
      })
      .catch((err) => {
        stream?.getTracks().forEach((t) => t.stop())
        if (!stopped) setError(err?.name ? cameraError(err) : 'โหลดตัวอ่าน QR ไม่สำเร็จ — ตรวจการเชื่อมต่อแล้วเปิดใหม่ หรือพิมพ์รหัสแทน')
      })

    return () => {
      stopped = true
      clearInterval(timer)
      stream?.getTracks().forEach((t) => t.stop())
    }
  }, [continuous])

  // ถ่ายรูป/เลือกรูป — ใช้ได้แม้ไม่มี https เพราะไม่ได้เปิดกล้องผ่านหน้าเว็บ (แอปกล้องของเครื่องถ่ายให้)
  const onPhoto = async (e) => {
    const file = e.target.files?.[0]
    e.target.value = '' // เลือกรูปเดิมซ้ำได้
    if (!file) return
    setPhotoMsg('กำลังอ่าน QR ในรูป…')
    try {
      const detector = await getDetector()
      const [hit] = await detector.detect(await createImageBitmap(file))
      const parsed = hit && parseScan(hit.rawValue)
      if (!parsed) { setPhotoMsg('อ่าน QR ในรูปไม่ได้ — ลองถ่ายใกล้ขึ้นให้ QR เต็มกรอบและไม่เบลอ'); return }
      setPhotoMsg('')
      onResultRef.current(parsed)
    } catch {
      setPhotoMsg('อ่านรูปไม่สำเร็จ — ลองถ่ายใหม่ หรือพิมพ์รหัสแทน')
    }
  }

  const submitManual = (e) => {
    e.preventDefault()
    const parsed = parseScan(manual)
    if (parsed) onResult(parsed)
    if (continuous) setManual('')
  }

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50 px-4 py-6 overflow-y-auto">
      <div className="bg-white rounded-2xl p-6 w-full max-w-md shadow-xl space-y-4">
        <h2 className="font-bold text-gray-800">{title}</h2>

        {!error && (
          <div className="relative overflow-hidden rounded-xl bg-black aspect-square">
            <video ref={videoRef} muted playsInline autoPlay className="h-full w-full object-cover" />
            <div className="pointer-events-none absolute inset-10 rounded-lg border-2 border-white/70" />
            {!live && <p className="absolute inset-0 flex items-center justify-center text-sm text-white/80">กำลังเปิดกล้อง…</p>}
          </div>
        )}
        {error === 'insecure' && (
          <p className="text-sm text-amber-700 bg-amber-50 rounded-lg px-3 py-2">
            เครื่องนี้ยังเปิดกล้องสดในหน้าเว็บไม่ได้ (ต้องเข้าผ่าน https ที่เครื่องเชื่อถือ) —{' '}
            <Link to="/install-cert" className="font-medium underline">ติดตั้งใบรับรองครั้งเดียว</Link>{' '}
            หรือใช้ปุ่มถ่ายรูป QR ด้านล่างแทนได้เลย
          </p>
        )}
        {error && error !== 'insecure' && <p className="text-sm text-amber-700 bg-amber-50 rounded-lg px-3 py-2">{error}</p>}
        {children}

        <label className="flex w-full cursor-pointer items-center justify-center gap-2 rounded-full border border-primary-600 py-2 text-sm font-medium text-primary-700 hover:bg-primary-50">
          ถ่ายรูป / เลือกรูป QR
          <input type="file" accept="image/*" capture="environment" onChange={onPhoto} className="hidden" />
        </label>
        {photoMsg && <p className="text-sm text-gray-600">{photoMsg}</p>}

        <form onSubmit={submitManual} className="flex gap-2">
          <input autoFocus={!!error} value={manual} onChange={(e) => setManual(e.target.value)}
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
