import { formatDate } from '../../utils/formatDate.js'

/**
 * ใช้แทน <input type="date"> / <input type="datetime-local"> ทุกที่ — โชว์ วว/ดด/ปปปป เสมอ
 *
 * ช่องวันที่ของเบราว์เซอร์แสดงผลตามภาษาของเครื่อง (Chrome ภาษาอังกฤษ = เดือน/วัน/ปี) และไม่สน attribute
 * `lang` จึงบังคับรูปแบบผ่าน input ตรง ๆ ไม่ได้ ตัวนี้เขียนข้อความเอง แล้ววาง input จริงแบบโปร่งใสทับไว้ทั้งกล่อง
 * — value/onChange/min/max/required ยังเป็นของ input จริงทั้งหมด ผู้เรียกใช้เหมือน input เดิมทุกอย่าง
 */
export default function DateInput({ type = 'date', value, className = '', disabled, ...props }) {
  const time = type === 'datetime-local'
  const text = value ? `${formatDate(value)}${time ? ` ${value.slice(11, 16)}` : ''}` : ''
  return (
    <div className={`relative flex items-center justify-between gap-2 ${className.includes('w-full') ? '' : 'w-fit'}
      ${className} focus-within:ring-2 focus-within:ring-primary-500 ${disabled ? 'bg-gray-50 text-gray-500' : 'bg-white'}`}>
      <span className={text ? '' : 'text-gray-400'}>{text || (time ? 'วว/ดด/ปปปป --:--' : 'วว/ดด/ปปปป')}</span>
      <svg className="h-4 w-4 shrink-0 text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
        <rect x="3" y="5" width="18" height="16" rx="2" /><path d="M3 10h18M8 3v4M16 3v4" />
      </svg>
      <input type={type} value={value} disabled={disabled} {...props}
        // เปิดปฏิทินทันทีที่คลิกตรงไหนก็ได้ (ไม่งั้นต้องเล็งไอคอนเล็ก ๆ ของเบราว์เซอร์ซึ่งมองไม่เห็นแล้ว)
        onClick={(e) => { try { e.currentTarget.showPicker() } catch { /* เบราว์เซอร์เก่า — ยังใช้คีย์บอร์ดได้ */ } }}
        className="absolute inset-0 h-full w-full cursor-pointer opacity-0 disabled:cursor-not-allowed" />
    </div>
  )
}
