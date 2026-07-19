/** กติกาของตะกร้าที่ทดสอบได้โดยไม่ต้องมี React — ดู cartRules.test.mjs (รันด้วย `node --test`) */

/**
 * เพิ่มของลงตะกร้า ถ้ามีอยู่แล้วให้บวกจำนวนรวมกัน (ไม่เกินของคงเหลือ)
 * ครุภัณฑ์ยืมได้ทีละ 1 ตัวเสมอ จึงไม่บวกเพิ่ม
 * เดิมโค้ดคืนตะกร้าเดิมเฉย ๆ ทำให้กด "เพิ่มทั้งชุด" แล้วของที่ซ้ำหายไปเงียบ ๆ
 */
export function mergeCartItem(cart, equipment, quantity = 1) {
  const exists = cart.find((i) => i.equipment.id === equipment.id)
  if (!exists) return [...cart, { equipment, quantity }]
  if (equipment.item_type === 'durable') return cart
  const max = equipment.quantity_available ?? Infinity
  const merged = Math.min(exists.quantity + quantity, max)
  return cart.map((i) => (i.equipment.id === equipment.id ? { ...i, quantity: merged } : i))
}

/** ของในชุดที่ยืมไม่ได้ตอนนี้ (ปลดระวาง/ของประจำห้อง/ของหมด) — ข้ามไปแล้วบอกผู้ใช้ */
export function isBundleItemAvailable(item) {
  return Boolean(item.is_borrowable) && Boolean(item.quantity_available)
}
