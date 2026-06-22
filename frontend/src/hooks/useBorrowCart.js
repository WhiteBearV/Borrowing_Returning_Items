import { useCallback, useState } from 'react'

export function useBorrowCart() {
  const [cart, setCart] = useState([])  // [{ equipment, quantity }]

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

  const clearCart = useCallback(() => setCart([]), [])

  return { cart, addItem, removeItem, updateQuantity, clearCart }
}
