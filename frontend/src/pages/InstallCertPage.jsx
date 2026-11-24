import { Link } from 'react-router-dom'

const STEPS = {
  ios: {
    title: 'iPhone / iPad',
    steps: [
      'เปิดหน้านี้ด้วย Safari แล้วกดปุ่ม "ดาวน์โหลดใบรับรอง" ด้านบน → กด "อนุญาต"',
      'ไปที่ ตั้งค่า → "ดาวน์โหลดโปรไฟล์แล้ว" (ใต้ชื่อบัญชีด้านบนสุด) → ติดตั้ง → ใส่รหัสเครื่อง → ติดตั้ง',
      'ไปที่ ตั้งค่า → ทั่วไป → เกี่ยวกับ → การตั้งค่าความเชื่อถือใบรับรอง (เลื่อนลงล่างสุด) → เปิดสวิตช์ "CDTI Equipment Borrowing Local CA"',
      'ปิด Safari ให้หมด แล้วเปิดเว็บใหม่ — แถบที่อยู่ต้องไม่มีคำเตือน และปุ่มสแกนจะเปิดกล้องได้',
    ],
    note: 'ข้อ 3 ข้ามไม่ได้ — ติดตั้งโปรไฟล์อย่างเดียวกล้องยังไม่เปิด',
  },
  android: {
    title: 'Android',
    steps: [
      'กดปุ่ม "ดาวน์โหลดใบรับรอง" ด้านบน (ไฟล์ cdti-borrow-ca.crt จะอยู่ในโฟลเดอร์ ดาวน์โหลด)',
      'ไปที่ ตั้งค่า → ความปลอดภัยและความเป็นส่วนตัว → การตั้งค่าความปลอดภัยเพิ่มเติม (หรือ "การเข้ารหัสและข้อมูลเข้าสู่ระบบ") → ติดตั้งใบรับรอง → ใบรับรอง CA',
      'กด "ติดตั้งต่อไป" → เลือกไฟล์ cdti-borrow-ca.crt',
      'ปิด Chrome แล้วเปิดเว็บใหม่ — ไม่มีหน้าเตือน และปุ่มสแกนเปิดกล้องได้',
    ],
    note: 'ชื่อเมนูต่างกันเล็กน้อยตามยี่ห้อ — ค้นคำว่า "ใบรับรอง" หรือ "CA" ในช่องค้นหาของแอปตั้งค่าได้',
  },
}

/** หน้าสาธารณะ: ติดตั้งใบรับรอง CA ของคณะบนมือถือ — เว็บยังเข้าด้วย IP ไม่มีโดเมน/ใบรับรองจริง
 *  มือถือจึงไม่เชื่อถือ https และไม่ให้หน้าเว็บเปิดกล้องสแกน QR จนกว่าจะติดตั้งครั้งเดียว (ดู gen-lan-ca.sh) */
export default function InstallCertPage() {
  const isApple = /iPhone|iPad|Macintosh/.test(navigator.userAgent) && 'ontouchend' in document
  const order = isApple ? ['ios', 'android'] : ['android', 'ios']

  return (
    <div className="min-h-screen bg-gray-50 px-4 py-8">
      <div className="mx-auto w-full max-w-lg space-y-5">
        <div className="rounded-2xl bg-white p-6 shadow space-y-3">
          <h1 className="text-lg font-bold text-gray-800">ติดตั้งใบรับรองเพื่อใช้กล้องสแกน QR</h1>
          <p className="text-sm text-gray-600">
            ทำครั้งเดียวต่อเครื่อง — มือถือ/แท็บเล็ตจะยอมให้หน้าเว็บเปิดกล้องได้เฉพาะเว็บที่เชื่อถือ
            ใบรับรองนี้ออกโดยระบบยืม-คืนอุปกรณ์ของคณะ ใช้กับเว็บนี้เท่านั้น
          </p>
          <a href="/ca.crt" download="cdti-borrow-ca.crt"
            className="block w-full rounded-full bg-primary-600 py-2.5 text-center text-sm font-medium text-white hover:bg-primary-700">
            ดาวน์โหลดใบรับรอง
          </a>
        </div>

        {order.map((k) => (
          <div key={k} className="rounded-2xl bg-white p-6 shadow space-y-3">
            <h2 className="font-bold text-gray-800">{STEPS[k].title}</h2>
            <ol className="list-decimal space-y-2 pl-5 text-sm text-gray-700">
              {STEPS[k].steps.map((s) => <li key={s}>{s}</li>)}
            </ol>
            <p className="text-xs text-amber-700">{STEPS[k].note}</p>
          </div>
        ))}

        <p className="text-center text-xs text-gray-500">
          ยังไม่สะดวกติดตั้ง? ปุ่ม "ถ่ายรูป / เลือกรูป QR" ในหน้าสแกนใช้ได้ทันทีโดยไม่ต้องติดตั้ง ·{' '}
          <Link to="/" className="text-primary-600 underline">กลับหน้าหลัก</Link>
        </p>
      </div>
    </div>
  )
}
