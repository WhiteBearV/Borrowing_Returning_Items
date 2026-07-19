import { useCallback, useEffect, useState } from 'react'
import { isBundleItemAvailable, mergeCartItem } from './cartRules.js'

const KEY = 'borrowCart'
const PURPOSE_KEY = 'borrowPurpose'

export function useBorrowCart() {
  // ponytail: localStorage พอ — ตะกร้าเป็นของ client ล้วน ยังไม่ต้องเก็บลง DB
  const [cart, setCart] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem(KEY)) || []
    } catch {
      return []
    }
  })  // [{ equipment, quantity }]

  // วัตถุประสงค์อยู่คู่กับตะกร้า — สลับหน้าไปเลือกของเพิ่มแล้วกลับมา ข้อความที่พิมพ์ไว้ต้องยังอยู่
  const [purpose, setPurpose] = useState(() => localStorage.getItem(PURPOSE_KEY) ?? '')

  useEffect(() => {
    localStorage.setItem(KEY, JSON.stringify(cart))
  }, [cart])

  useEffect(() => {
    localStorage.setItem(PURPOSE_KEY, purpose)
  }, [purpose])

  const addItem = useCallback((equipment, quantity = 1) => {
    setCart((prev) => mergeCartItem(prev, equipment, quantity))
  }, [])

  /** เพิ่มทั้งชุดลงตะกร้า — คืนรายการที่เพิ่มไม่ได้ (ของหมด/ของประจำห้อง) ให้หน้าเว็บแจ้งผู้ใช้ */
  const addBundle = useCallback((bundle) => {
    const skipped = []
    // อัปเดตครั้งเดียวจบ — เรียก addItem ทีละชิ้นจะอ่าน state เก่าถ้าของในชุดซ้ำกัน
    setCart((prev) => bundle.items.reduce((acc, it) => {
      if (!isBundleItemAvailable(it)) {
        skipped.push(it.equipment_name ?? it.equipment_id)
        return acc
      }
      return mergeCartItem(acc, {
        id: it.equipment_id, name: it.equipment_name, code: it.equipment_code,
        item_type: it.item_type, unit: it.unit, quantity_available: it.quantity_available,
      }, it.quantity)
    }, prev))
    return skipped
  }, [])

  const removeItem = useCallback((equipmentId) => {
    setCart((prev) => prev.filter((i) => i.equipment.id !== equipmentId))
  }, [])

  const updateQuantity = useCallback((equipmentId, quantity) => {
    setCart((prev) =>
      prev.map((i) => (i.equipment.id === equipmentId ? { ...i, quantity } : i)),
    )
  }, [])

  const clearCart = useCallback(() => {
    setCart([])
    setPurpose('')
  }, [])

  return { cart, addItem, addBundle, removeItem, updateQuantity, clearCart, purpose, setPurpose }
}
