import { useCallback, useEffect, useState } from 'react'

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
    setCart((prev) => {
      const exists = prev.find((i) => i.equipment.id === equipment.id)
      if (exists) return prev
      return [...prev, { equipment, quantity }]
    })
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

  return { cart, addItem, removeItem, updateQuantity, clearCart, purpose, setPurpose }
}
