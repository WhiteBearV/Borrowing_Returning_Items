/** ข้อความ error จาก axios -> string เสมอ
 *
 * 422 ของ FastAPI ส่ง detail มาเป็น "array ของ object" ไม่ใช่ข้อความ ถ้าเอาไปใส่ state
 * แล้ว render ตรง ๆ React จะพังทั้งหน้า ("Objects are not valid as a React child")
 * อาการที่ผู้ใช้เห็นคือกดปุ่มแล้วไม่ไปไหน โดยไม่มี error ให้อ่าน
 */
export function apiErrorMessage(err, fallback = 'ทำรายการไม่สำเร็จ') {
  const detail = err?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((d) => d?.msg).filter(Boolean).join(' · ') || fallback
  return fallback
}
