// เปิด PDF/รูปในแท็บใหม่แทนการบังคับดาวน์โหลด — ผู้ใช้ดูก่อน แล้วกดบันทึกเองจาก viewer ได้
// รับ Promise ของ blob ไม่ใช่ blob: ต้องเปิดแท็บ "ตอนกด" ก่อน await ไม่งั้น Safari ถือว่าไม่ใช่การกดของผู้ใช้
// แล้วบล็อกเป็นป็อปอัป (10 พ.ย. 69 — Chrome ผ่อนผันจึงไม่เห็นบนเครื่อง dev)
// เรียกแบบ `await openPdf(api.x())` ห้าม `openPdf(await api.x())`
export async function openPdf(blobPromise) {
  const win = window.open('', '_blank')
  let blob
  try {
    blob = await blobPromise
  } catch (err) {
    win?.close()
    throw err
  }
  const url = URL.createObjectURL(blob)
  if (win) {
    win.location.href = url
  } else { // ponytail: ปิดป็อปอัปหมดทุกเว็บ → ดาวน์โหลดแทน
    const a = document.createElement('a')
    a.href = url
    a.download = ''
    a.click()
  }
  setTimeout(() => URL.revokeObjectURL(url), 60000) // เผื่อแท็บใหม่โหลดไฟล์เสร็จก่อน
}
