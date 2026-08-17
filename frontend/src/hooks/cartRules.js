/** กติกาของตะกร้าที่ทดสอบได้โดยไม่ต้องมี React — ดู cartRules.test.mjs (รันด้วย `node --test`) */

/**
 * เพิ่มของลงตะกร้า ถ้ามีอยู่แล้วให้บวกจำนวนรวมกัน (ไม่เกินของคงเหลือ)
 * เดิมล็อกครุภัณฑ์ (item_type==='durable') ไว้ที่ 1 เสมอเพราะการ์ดเดิม = หน่วยเดียวจริง
 * ตอนนี้การ์ดยุบรวมหลายหน่วยรุ่นเดียวกันแล้ว (ดู equipment_service.list_equipment_grouped)
 * จึงอิง quantity_available ของการ์ดแทน ไม่อิง item_type — รุ่นที่เหลือหน่วยเดียวก็ยังล็อกที่ 1 เองโดยธรรมชาติ
 * เดิมโค้ดคืนตะกร้าเดิมเฉย ๆ ทำให้กด "เพิ่มทั้งชุด" แล้วของที่ซ้ำหายไปเงียบ ๆ
 */
export function mergeCartItem(cart, equipment, quantity = 1) {
  const exists = cart.find((i) => i.equipment.id === equipment.id)
  const max = equipment.quantity_available ?? Infinity
  if (!exists) return [...cart, { equipment, quantity: Math.min(quantity, max) }]
  const merged = Math.min(exists.quantity + quantity, max)
  return cart.map((i) => (i.equipment.id === equipment.id ? { ...i, quantity: merged } : i))
}

/** ของในชุดที่ยืมไม่ได้ตอนนี้ (ปลดระวาง/ของประจำห้อง/ของหมด) — ข้ามไปแล้วบอกผู้ใช้ */
export function isBundleItemAvailable(item) {
  return Boolean(item.is_borrowable) && Boolean(item.quantity_available)
}
