import { createContext, useContext, useEffect } from 'react'
import { useBorrowCart } from '../hooks/useBorrowCart.js'
import { useAuthContext } from './AuthContext.jsx'

const CartContext = createContext(null)

export function CartProvider({ children }) {
  const cart = useBorrowCart()
  const { user, loading } = useAuthContext()

  // ล้างตะกร้าเมื่อออกจากระบบ (รอ loading จบก่อน ไม่งั้นจะลบตะกร้าที่เพิ่ง restore มา)
  useEffect(() => {
    if (!loading && !user) cart.clearCart()
  }, [loading, user, cart.clearCart])

  return <CartContext.Provider value={cart}>{children}</CartContext.Provider>
}

export function useCart() {
  const ctx = useContext(CartContext)
  if (!ctx) throw new Error('useCart must be used inside CartProvider')
  return ctx
}
