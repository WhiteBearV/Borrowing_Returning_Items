import { useEffect, useImperativeHandle, useRef, useState, forwardRef } from 'react'

/**
 * ช่องเซ็นลายมือชื่อบนหน้าจอ — ใช้ได้ทั้งเมาส์ นิ้ว และปากกา (pointer events ตัวเดียวครอบหมด)
 *
 * เขียนเองแทนติดตั้งไลบรารี เพราะตรรกะจริงมีแค่ "ลากแล้ววาดเส้น" ~60 บรรทัด
 * จุดที่พลาดง่ายและต้องคงไว้:
 *  - touchAction: 'none' ไม่งั้นนิ้วที่ลากบนจอมือถือจะเลื่อนหน้าแทนการเซ็น
 *  - คูณ devicePixelRatio ไม่งั้นเส้นแตกเป็นขั้นบันไดบนจอความละเอียดสูง
 *  - เก็บ isEmpty ไว้ให้ปุ่มยืนยันปิดตัวเองได้ กันส่งลายเซ็นเปล่า
 *
 * ผู้เรียกดึงรูปออกทาง ref: `await padRef.current.toBlob()` → PNG blob (null ถ้ายังไม่มีเส้น)
 */
const SignaturePad = forwardRef(function SignaturePad({ label, height = 180 }, ref) {
  const canvasRef = useRef(null)
  const drawing = useRef(false)
  const [isEmpty, setIsEmpty] = useState(true)

  useEffect(() => {
    const canvas = canvasRef.current
    const ratio = window.devicePixelRatio || 1
    const rect = canvas.getBoundingClientRect()
    canvas.width = rect.width * ratio
    canvas.height = rect.height * ratio
    const ctx = canvas.getContext('2d')
    ctx.scale(ratio, ratio)
    ctx.lineWidth = 2
    ctx.lineCap = 'round'
    ctx.lineJoin = 'round'
    ctx.strokeStyle = '#0b1f33'
  }, [height])

  const pos = (e) => {
    const rect = canvasRef.current.getBoundingClientRect()
    return { x: e.clientX - rect.left, y: e.clientY - rect.top }
  }

  const start = (e) => {
    e.currentTarget.setPointerCapture(e.pointerId)
    const { x, y } = pos(e)
    const ctx = canvasRef.current.getContext('2d')
    ctx.beginPath()
    ctx.moveTo(x, y)
    drawing.current = true
  }

  const move = (e) => {
    if (!drawing.current) return
    const { x, y } = pos(e)
    const ctx = canvasRef.current.getContext('2d')
    ctx.lineTo(x, y)
    ctx.stroke()
    if (isEmpty) setIsEmpty(false)
  }

  const end = () => { drawing.current = false }

  const clear = () => {
    const canvas = canvasRef.current
    canvas.getContext('2d').clearRect(0, 0, canvas.width, canvas.height)
    setIsEmpty(true)
  }

  useImperativeHandle(ref, () => ({
    isEmpty: () => isEmpty,
    clear,
    // PNG มีพื้นหลังโปร่งใส — วางทับใบยืมใน PDF ได้โดยไม่บังตาราง
    toBlob: () => new Promise((resolve) => {
      if (isEmpty) return resolve(null)
      canvasRef.current.toBlob(resolve, 'image/png')
    }),
  }), [isEmpty])

  return (
    <div>
      <div className="flex items-baseline justify-between mb-1">
        <span className="text-sm font-medium text-gray-700">{label}</span>
        <button type="button" onClick={clear} className="text-xs text-gray-500 hover:text-gray-700 hover:underline">
          ล้าง
        </button>
      </div>
      <canvas
        ref={canvasRef}
        onPointerDown={start}
        onPointerMove={move}
        onPointerUp={end}
        onPointerLeave={end}
        onPointerCancel={end}
        style={{ touchAction: 'none', height }}
        className="w-full rounded-lg border-2 border-dashed border-gray-300 bg-white cursor-crosshair"
      />
      <p className="text-xs text-gray-400 mt-1">
        {isEmpty ? 'เซ็นด้วยนิ้วหรือเมาส์ในกรอบนี้' : 'เซ็นแล้ว — กด "ล้าง" ถ้าต้องการเซ็นใหม่'}
      </p>
    </div>
  )
})

export default SignaturePad
