// เปิด PDF ในแท็บใหม่แทนการบังคับดาวน์โหลด — ผู้ใช้ดูก่อน แล้วกดบันทึกเองจาก viewer ได้
// ponytail: blob URL + window.open พอ ไม่ต้องมี viewer ในแอป
export function openPdf(blob) {
  const url = URL.createObjectURL(blob)
  window.open(url, '_blank')
  setTimeout(() => URL.revokeObjectURL(url), 60000) // เผื่อแท็บใหม่โหลดไฟล์เสร็จก่อน
}
